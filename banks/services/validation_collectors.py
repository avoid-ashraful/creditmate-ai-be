"""Django-aware collectors and crawler wiring for multi-source validation.

This module turns persisted content and external payloads into
:class:`banks.services.multi_source_validation.Observation` records and
runs the validation service against them:

* ``observations_from_crawled_content`` - reads the cards out of one
  ``CrawledContent.parsed_json`` and builds observations whose ``source_key``
  is the data source URL, so two crawls of the same URL are the *same*
  source and never count as independent; a webpage source (``webpage``)
  becomes ``bank_website`` and a PDF source becomes ``bank_pdf``.
* ``latest_observations_for_bank`` - the most recent completed crawl record
  per **active** data source of a bank, giving one representative observation
  set per concrete source in a stable (URL-ordered) way.
* ``observations_from_user_submissions`` - accepts external submission
  payloads (dictionaries or objects) without requiring a submission model;
  live user-submission ingestion depends on the account/submission model that
  tasks outside this stream own.
* ``validate_crawled_content`` / ``run_multi_source_validation`` - combine
  current + historical + optional user observations, validate them, persist
  the JSON-safe summary on the crawl record and raise ``needs_manual_review``
  when a real conflict or same-source inconsistency is found.

No live crawling or external submissions happen here; the functions only
consume data the caller already has.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from banks.enums import ContentType, ProcessingStatus, SourceType
from banks.models import CrawledContent
from banks.services.multi_source_validation import (
    VALIDATED_FIELDS,
    MultiSourceValidator,
    Observation,
    ValidationBatch,
    batch_summary,
)
from banks.services.quality_scoring import coalesce_cards

logger = logging.getLogger(__name__)


def content_type_to_source_type(content_type) -> str:
    """Map a data source content type to its broad source class.

    PDF sources are ``bank_pdf``, webpage sources ``bank_website``, csv
    sources ``bank_csv`` and image sources ``bank_image`` (scanned fee
    tables behave like documents, not like user submissions).

    Parameters
    ----------
    content_type : str
        ``ContentType`` value (``pdf``, ``webpage``, ``csv``, ``image``).

    Returns
    -------
    str
        A ``SourceType`` value.
    """
    return {
        ContentType.PDF: SourceType.BANK_PDF,
        ContentType.WEBPAGE: SourceType.BANK_WEBSITE,
        ContentType.CSV: SourceType.BANK_CSV,
        ContentType.IMAGE: SourceType.BANK_IMAGE,
    }.get(content_type, SourceType.USER_SUBMISSION)


def _card_key(card, index):
    """Return a usable card identity for a parsed card, or ``""``.

    A card name is preferred; when the document only produced one unnamed
    card (the data service invents a fallback name) the positional identity
    ``card-1`` is used so the card can still be compared *within* the same
    document set without merging unrelated named cards.
    """
    name = card.get("name")
    if name and str(name).strip():
        return str(name).strip()
    if index == 0:
        return "card-1"
    return f"card-{index + 1}"


def observations_from_crawled_content(content) -> List[Observation]:
    """Build observations from one ``CrawledContent`` record.

    Only :data:`VALIDATED_FIELDS` are compared across sources; free-text
    fields cannot be compared safely. The source identity is the data source
    URL, and the observation confidence defaults to the content's extraction
    confidence when one is stored.

    Parameters
    ----------
    content : CrawledContent
        Completed (or completed-able) crawl record.

    Returns
    -------
    list of Observation
        One observation per card/field found in ``parsed_json``.
    """
    cards = coalesce_cards(getattr(content, "parsed_json", None))
    source_url = content.data_source.url
    source_type = content_type_to_source_type(content.data_source.content_type)
    bank_key = content.data_source.bank.name
    confidence = content.extraction_confidence

    observations: List[Observation] = []
    for index, card in enumerate(cards):
        identity = _card_key(card, index)
        if not identity:
            continue
        for field in VALIDATED_FIELDS:
            if field not in card:
                continue
            observations.append(
                Observation(
                    field=field,
                    value=card.get(field),
                    source_type=source_type,
                    source_key=source_url,
                    card_key=identity,
                    bank_key=bank_key,
                    confidence=confidence,
                )
            )
    return observations


def latest_observations_for_bank(
    bank, exclude_content_id: Optional[int] = None
) -> List[Observation]:
    """Collect the newest completed crawl observations per active data source.

    One representative record per data source URL keeps the source set stable
    and deterministic: the same URL crawled ten times is still one source.

    Parameters
    ----------
    bank : Bank
        Bank whose active data sources are inspected.
    exclude_content_id : int, optional
        ``CrawledContent`` id to skip (normally the record being validated).

    Returns
    -------
    list of Observation
        Observations from the latest completed crawl of each active source.
    """
    observations: List[Observation] = []
    queryset = CrawledContent.objects.filter(
        data_source__bank=bank,
        data_source__is_active=True,
        processing_status=ProcessingStatus.COMPLETED,
    )
    if exclude_content_id is not None:
        queryset = queryset.exclude(pk=exclude_content_id)

    latest_by_source: Dict[int, CrawledContent] = {}
    for record in queryset.order_by("-crawled_at"):
        latest_by_source.setdefault(record.data_source_id, record)
    for record in latest_by_source.values():
        observations.extend(observations_from_crawled_content(record))
    return observations


def observations_from_user_submissions(submissions) -> List[Observation]:
    """Build observations from user-submission payloads.

    Each payload is a mapping (or object with the same attributes) carrying:
    ``card_key`` (required), ``field`` (required), ``value`` (required) and
    optionally ``bank_key``, ``source_key``, ``confidence`` and ``unit``.
    ``source_key`` defaults to a per-submission counter so distinct
    submissions are independent unless the caller supplies a shared identity.

    Parameters
    ----------
    submissions : iterable
        External submission payloads.

    Returns
    -------
    list of Observation
        ``user_submission`` observations with explicit card provenance.
    """
    observations: List[Observation] = []
    for index, submission in enumerate(submissions or []):
        payload = _payload_to_dict(submission)
        card_key = payload.get("card_key") or payload.get("card_name")
        field = payload.get("field")
        if not card_key or not field:
            logger.warning("Dropping user submission without card/field: %r", payload)
            continue
        observations.append(
            Observation(
                field=field,
                value=payload.get("value"),
                source_type=SourceType.USER_SUBMISSION,
                source_key=payload.get("source_key") or f"submission-{index + 1}",
                card_key=str(card_key),
                bank_key=payload.get("bank_key", ""),
                confidence=payload.get("confidence"),
                unit=payload.get("unit"),
            )
        )
    return observations


def validate_crawled_content(
    content: CrawledContent,
    user_submissions=(),
    validator: Optional[MultiSourceValidator] = None,
) -> ValidationBatch:
    """Run multi-source validation for one crawl record against the bank.

    Combines the record's own observations, the latest observations of the
    bank's other active sources, and any caller-supplied user submissions.

    Parameters
    ----------
    content : CrawledContent
        The crawl record being validated (its own observations are included).
    user_submissions : iterable, optional
        External user-submission payloads (see
        :func:`observations_from_user_submissions`).
    validator : MultiSourceValidator, optional
        Pure validator instance; a default one is created when omitted.

    Returns
    -------
    ValidationBatch
        Validation outcome; the record itself is **not** modified here.
    """
    validator = validator or MultiSourceValidator()
    observations = list(observations_from_crawled_content(content))
    observations.extend(
        latest_observations_for_bank(content.data_source.bank, exclude_content_id=content.pk)
    )
    observations.extend(observations_from_user_submissions(user_submissions))
    return validator.validate(observations)


def run_multi_source_validation(
    content: CrawledContent,
    user_submissions=(),
    validator: Optional[MultiSourceValidator] = None,
) -> ValidationBatch:
    """Validate a crawl record and persist the outcome on it.

    Stores the JSON-safe summary in ``CrawledContent.multi_source_validation``
    and sets ``needs_manual_review`` to ``True`` when a real conflict or
    same-source inconsistency is detected (it never clears an existing flag).

    Parameters
    ----------
    content : CrawledContent
        Record to validate and update.
    user_submissions : iterable, optional
        External user-submission payloads.
    validator : MultiSourceValidator, optional
        Pure validator instance.

    Returns
    -------
    ValidationBatch
        The computed validation outcome.
    """
    batch = validate_crawled_content(content, user_submissions=user_submissions, validator=validator)
    summary = batch_summary(batch)
    if batch.has_comparison:
        # Only persist an outcome once there is something to compare: a
        # single-source crawl carries no cross-source report and keeps the
        # default empty summary until a second independent source arrives.
        content.apply_multi_source_validation(summary)
        if summary["conflict_field_count"]:
            logger.warning(
                "Multi-source validation found %d conflicting field(s) on crawl "
                "record %s; flagged for manual review",
                summary["conflict_field_count"],
                content.pk,
            )
    return batch


def _payload_to_dict(payload) -> Dict[str, Any]:
    """Normalize a mapping or object payload into a dictionary."""
    if isinstance(payload, dict):
        return dict(payload)
    return {key: getattr(payload, key) for key in (
        "card_key", "card_name", "field", "value", "bank_key",
        "source_key", "confidence", "unit",
    ) if hasattr(payload, key)}


__all__ = [
    "content_type_to_source_type",
    "latest_observations_for_bank",
    "observations_from_crawled_content",
    "observations_from_user_submissions",
    "run_multi_source_validation",
    "validate_crawled_content",
]
