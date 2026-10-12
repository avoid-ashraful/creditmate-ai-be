"""Post-extraction quality validation for crawled content.

Phase 1.2 of ``docs/improvements.md``. After a document has been extracted and
parsed, this service scores how trustworthy the result is and records the score
on the :class:`banks.models.CrawledContent` row.

The score is bounded to ``0.0 - 1.0`` and every penalty is documented in
:mod:`banks.services.quality_scoring`. Two failures make a crawl go to manual
review:

* confidence below 0.5, or
* more than one distinct issue (e.g. OCR source *and* a missing critical field).

Zero-versus-missing is preserved end to end: a card with ``annual_fee = 0`` is
treated as a complete extraction, while a card whose document never mentioned
the fee keeps ``None`` (``null``) and is counted as missing.
"""

import logging

from banks.services.quality_scoring import (
    ExtractionQuality,
    clamp_confidence,
    coalesce_cards,
    score_extraction,
)

logger = logging.getLogger(__name__)

MANUAL_REVIEW_CONFIDENCE_THRESHOLD = 0.5
MANUAL_REVIEW_ISSUE_LIMIT = 1


class ExtractionQualityValidator:
    """Validate and score the quality of crawled content."""

    @staticmethod
    def validate_extraction_quality(crawled_content):
        """Score a crawled content record without saving it.

        Parameters
        ----------
        crawled_content : CrawledContent
            Record to validate.

        Returns
        -------
        tuple of (float, list of str)
            Bounded confidence (0.0-1.0) and the list of issue codes.
        """
        cards = coalesce_cards(getattr(crawled_content, "parsed_json", None))
        method = getattr(crawled_content, "extraction_method", "") or "unknown"
        quality = score_extraction(
            getattr(crawled_content, "extracted_content", "") or "", cards, method
        )
        return quality.confidence, list(quality.issues)

    @staticmethod
    def score_crawled_content(crawled_content, cards=None, extraction_passes=None):
        """Score a crawled content record and persist the quality fields.

        Parameters
        ----------
        crawled_content : CrawledContent
            Record to score and update.
        cards : list of dict, optional
            Cards to score. Defaults to the cards in ``parsed_json``.
        extraction_passes : list of dict, optional
            Multi-pass provenance records to store.

        Returns
        -------
        ExtractionQuality
            The quality outcome that was stored on the record.
        """
        if cards is None:
            cards = coalesce_cards(crawled_content.parsed_json)

        method = crawled_content.extraction_method or "unknown"
        quality = score_extraction(
            crawled_content.extracted_content or "", cards, method
        )
        if extraction_passes:
            quality.passes = list(extraction_passes)

        crawled_content.apply_quality_score(
            confidence=quality.confidence,
            missing_critical_fields=quality.missing_critical_fields,
            needs_manual_review=quality.needs_manual_review,
            extraction_passes=extraction_passes,
        )

        if crawled_content.needs_manual_review:
            logger.warning(
                "Crawled content %s flagged for manual review (confidence %.3f, issues %s)",
                crawled_content.id,
                quality.confidence,
                quality.issues,
            )

        return quality

    @staticmethod
    def needs_manual_review(confidence, issues):
        """Decide whether an extraction must be reviewed by a human.

        Parameters
        ----------
        confidence : float
            Bounded confidence score.
        issues : list of str
            Issue codes from scoring.

        Returns
        -------
        bool
            True when the extraction should be reviewed.
        """
        bounded = clamp_confidence(confidence)
        return bounded < MANUAL_REVIEW_CONFIDENCE_THRESHOLD or len(issues or []) > (
            MANUAL_REVIEW_ISSUE_LIMIT
        )

    @staticmethod
    def quality_summary(crawled_content):
        """Build a serialisable quality summary for APIs and logs.

        Parameters
        ----------
        crawled_content : CrawledContent
            Record to summarise.

        Returns
        -------
        dict
            Quality summary (confidence, missing fields, method, review flag).
        """
        return {
            "extraction_confidence": crawled_content.extraction_confidence,
            "missing_critical_fields": list(
                crawled_content.missing_critical_fields or []
            ),
            "extraction_method": crawled_content.extraction_method,
            "needs_manual_review": crawled_content.needs_manual_review,
            "extraction_passes": list(crawled_content.extraction_passes or []),
            "quality_scored_at": (
                crawled_content.quality_scored_at.isoformat()
                if crawled_content.quality_scored_at
                else None
            ),
        }


__all__ = [
    "ExtractionQualityValidator",
    "ExtractionQuality",
    "MANUAL_REVIEW_CONFIDENCE_THRESHOLD",
]
