"""Multi-pass LLM extraction with validation and confidence scoring.

Phase 2.1 of ``docs/improvements.md``. Extraction runs as up to three passes:

1. **standard pass** - bank-specific prompt (see
   :mod:`banks.services.prompt_templates`) over the document, truncated to
   ``max_content_chars`` characters to stay inside the model context window.
2. **focused pass** - only triggered when pass 1 scores below
   ``confidence_threshold``; asks the model for the two critical fields
   (``annual_fee``, ``interest_rate_apr``) only, which is cheap and usually
   recovers the values lost in a large schedule of charges.
3. **validation pass** - merges the results of the previous passes and produces
   the final bounded confidence score.

Every pass is recorded in the result's ``passes`` list so the stored
``CrawledContent.extraction_passes`` preserves provenance (which provider
answered, how many cards it found, what the per-pass confidence was).

The LLM is reached through :class:`banks.services.extraction_provider.ExtractionProvider`
so tests can inject an offline fake provider; no live/paid model call is needed
to exercise the pipeline.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from banks.exceptions import AIParsingError
from banks.services.extraction_provider import OrchestratorExtractionProvider
from banks.services.prompt_templates import BankSpecificPrompts
from banks.services.quality_scoring import (
    STATUS_VALID,
    critical_field_states,
    score_extraction,
)
from banks.validators import CreditCardDataValidator
from banks.validators.numeric_fields import (
    CRITICAL_FIELDS,
    STATUS_INVALID,
    critical_field_status,
    is_missing_marker,
    normalize_critical_fields,
)

logger = logging.getLogger(__name__)

STANDARD_PASS = "standard"
FOCUSED_PASS = "focused"
VALIDATION_PASS = "validation"

DEFAULT_CONFIDENCE_THRESHOLD = 0.8


@dataclass
class MultiPassExtractionResult:
    """Result of a multi-pass extraction run.

    Attributes
    ----------
    credit_cards : list of dict
        Merged credit card dictionaries.
    confidence : float
        Bounded final confidence in the inclusive range 0.0-1.0.
    missing_critical_fields : list of str
        Critical fields still missing after all passes.
    passes : list of dict
        Ordered provenance records, one per pass.
    provider_used : str or None
        Name of the provider that produced the standard pass.
    issues : list of str
        Machine-readable issue codes.
    details : dict
        Per-pass intermediate scores for auditing.
    """

    credit_cards: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    missing_critical_fields: List[str] = field(default_factory=list)
    passes: List[Dict[str, Any]] = field(default_factory=list)
    provider_used: Optional[str] = None
    issues: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class MultiPassLLMExtractor:
    """Run multi-pass LLM extraction for a single document."""

    def __init__(
        self,
        provider=None,
        prompt_templates=None,
        validator=None,
        confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
        max_content_chars=12000,
        focused_content_chars=3000,
    ):
        """Initialize the extractor.

        Parameters
        ----------
        provider : ExtractionProvider, optional
            LLM provider used for every pass. Defaults to
            :class:`OrchestratorExtractionProvider`.
        prompt_templates : BankSpecificPrompts, optional
            Template registry used to build per-bank prompts.
        validator : CreditCardDataValidator, optional
            Real validation stage applied to merged cards before the final
            score is computed and the result is returned.
        confidence_threshold : float, optional
            Standard-pass confidence below which the focused pass runs.
        max_content_chars : int, optional
            Truncation limit for the standard pass.
        focused_content_chars : int, optional
            Truncation limit for the focused pass (kept small and cheap).
        """
        self.provider = provider or OrchestratorExtractionProvider()
        self.prompt_templates = prompt_templates or BankSpecificPrompts()
        self.validator = validator or CreditCardDataValidator()
        self.confidence_threshold = confidence_threshold
        self.max_content_chars = max_content_chars
        self.focused_content_chars = focused_content_chars

    def is_provider_available(self):
        """Return True when the configured LLM provider can serve requests."""
        return bool(self.provider.is_available())

    def extract(self, content, bank_name, method="unknown"):
        """Run the multi-pass extraction for one document.

        Parameters
        ----------
        content : str
            Extracted document text.
        bank_name : str
            Bank name used to select the prompt template.
        method : str, optional
            Extraction method that produced ``content`` (used for scoring).

        Returns
        -------
        MultiPassExtractionResult
            Merged cards, bounded confidence, missing fields and pass provenance.

        Raises
        ------
        AIParsingError
            When the provider is unavailable or every pass failed.
        """
        if not self.is_provider_available():
            raise AIParsingError(
                "Multi-pass extraction unavailable: no LLM provider is configured"
            )

        content = content or ""
        passes: List[Dict[str, Any]] = []
        issues: List[str] = []

        cards, provider_used = self._run_standard_pass(
            content, bank_name, method, passes, issues
        )

        standard_quality = score_extraction(content, cards, method)
        focused_pass_ran = False
        if standard_quality.confidence < self.confidence_threshold:
            logger.info(
                "Standard pass confidence %.3f below threshold %.3f for %s, "
                "running focused pass",
                standard_quality.confidence,
                self.confidence_threshold,
                bank_name,
            )
            focused_cards = self._run_focused_pass(
                content, bank_name, method, passes, issues
            )
            cards = self.merge_cards(cards, focused_cards)
            focused_pass_ran = True
        else:
            logger.info(
                "Standard pass confidence %.3f meets threshold for %s",
                standard_quality.confidence,
                bank_name,
            )

        # Pass 3: real validation stage (sanitize + validate) before the final
        # score is computed, so stored values are always normalized numbers or
        # NULL and validation problems reduce the confidence.
        cards, validation_issues = self._validate_cards(cards)
        issues.extend(validation_issues)

        final_quality = score_extraction(content, cards, method)
        passes.append(self._build_pass_record(VALIDATION_PASS, None, cards, final_quality))

        # Report a field as "invalid" (cause) rather than also as "missing"
        # when its value was rejected by the normalization rules.
        invalid_fields = {
            code[len("invalid_") :]
            for code in issues
            if code.startswith("invalid_")
        }
        final_issues = [
            issue
            for issue in final_quality.issues
            if not (
                issue.startswith("missing_")
                and issue[len("missing_") :] in invalid_fields
            )
        ]

        return MultiPassExtractionResult(
            credit_cards=cards,
            confidence=final_quality.confidence,
            missing_critical_fields=final_quality.missing_critical_fields,
            passes=passes,
            provider_used=provider_used,
            issues=sorted(set(issues + final_issues)),
            details={
                "standard_pass_confidence": standard_quality.confidence,
                "final": final_quality.details,
                "threshold": self.confidence_threshold,
                "focused_pass_ran": focused_pass_ran,
            },
        )

    # ------------------------------------------------------------------
    # Passes
    # ------------------------------------------------------------------
    def _run_standard_pass(self, content, bank_name, method, passes, issues):
        """Run pass 1 (bank-specific prompt).

        Parameters
        ----------
        content : str
            Extracted document text.
        bank_name : str
            Bank name for template selection.
        method : str
            Extraction method used for scoring.
        passes : list of dict
            Provenance list to append the pass record to.
        issues : list of str
            Issue list to append to.

        Returns
        -------
        tuple of (list of dict, str or None)
            Parsed cards and the provider that produced them.
        """
        prompt = self.prompt_templates.get_prompt_for_bank(
            bank_name, content[: self.max_content_chars]
        )
        response, provider_used, error = self._call_provider(prompt, "standard")

        if error is not None:
            issues.append(f"standard_pass_error: {error}")
            passes.append(
                {
                    "pass": STANDARD_PASS,
                    "provider": provider_used,
                    "cards_found": 0,
                    "confidence": 0.0,
                    "error": error,
                }
            )
            return [], provider_used

        cards = self._parse_cards(response, issues)
        quality = score_extraction(content, cards, method)
        passes.append(
            self._build_pass_record(STANDARD_PASS, provider_used, cards, quality)
        )
        return cards, provider_used

    def _run_focused_pass(self, content, bank_name, method, passes, issues):
        """Run pass 2 (critical fields only).

        Parameters
        ----------
        content : str
            Extracted document text.
        bank_name : str
            Bank name for context.
        method : str
            Extraction method used for scoring.
        passes : list of dict
            Provenance list to append the pass record to.
        issues : list of str
            Issue list to append to.

        Returns
        -------
        list of dict
            Focused cards (usually partial dictionaries).
        """
        prompt = self.prompt_templates.get_focused_prompt(
            bank_name, content[: self.focused_content_chars]
        )
        response, provider_used, error = self._call_provider(prompt, "focused")

        if error is not None:
            issues.append(f"focused_pass_error: {error}")
            passes.append(
                {
                    "pass": FOCUSED_PASS,
                    "provider": provider_used,
                    "cards_found": 0,
                    "confidence": 0.0,
                    "error": error,
                }
            )
            return []

        cards = self._parse_focused_cards(response, issues)
        quality = score_extraction(content, cards, method)
        passes.append(
            self._build_pass_record(FOCUSED_PASS, provider_used, cards, quality)
        )
        return cards

    # ------------------------------------------------------------------
    # Validation stage
    # ------------------------------------------------------------------
    def _validate_cards(self, cards):
        """Run the real validation stage on the merged card list.

        Every card is passed through :class:`CreditCardDataValidator`, which
        normalizes critical numbers to a valid float or ``None`` (genuine zero
        fees stay ``0``, missing/invalid values become ``NULL``) and validates
        the remaining fields. Extra document columns are preserved.

        Parameters
        ----------
        cards : list of dict
            Merged card dictionaries.

        Returns
        -------
        tuple of (list of dict, list of str)
            Validated cards and any validation error messages.
        """
        validated_cards = []
        issues = []

        for card in cards or []:
            if not isinstance(card, dict):
                continue
            sanitized = self.validator.sanitize_credit_card_data(card)
            sanitized = {**card, **sanitized}
            is_valid, errors = self.validator.validate_credit_card_data(sanitized)
            validated_cards.append(sanitized)
            if not is_valid:
                issues.extend(f"validation_error: {error}" for error in errors)

        return validated_cards, issues

    # ------------------------------------------------------------------
    # Provider interaction
    # ------------------------------------------------------------------
    def _call_provider(self, prompt, pass_name):
        """Call the LLM provider for one pass.

        Parameters
        ----------
        prompt : str
            Prompt for this pass.
        pass_name : str
            Pass name for logging.

        Returns
        -------
        tuple of (str or None, str or None, str or None)
            Raw response text, provider name, and error message. Exactly one of
            the response and the error is set.
        """
        try:
            result = self.provider.generate_response(
                prompt=prompt,
                max_retries=1,
                temperature=0.1,
                max_tokens=4000,
            )
        except Exception as exc:  # noqa: BLE001 - provider failures are recorded, not raised per pass
            logger.warning("%s pass failed: %s", pass_name, exc)
            return None, None, str(exc)

        if not isinstance(result, dict):
            return None, None, f"Unexpected provider response type: {type(result)!r}"

        provider_used = result.get("provider")
        response_text = result.get("response")
        if not isinstance(response_text, str):
            return None, provider_used, "Provider returned no response text"
        return response_text, provider_used, None

    # ------------------------------------------------------------------
    # Response parsing / merging
    # ------------------------------------------------------------------
    def _parse_cards(self, response_text, issues=None):
        """Parse a standard-pass response into normalized card dictionaries.

        Parameters
        ----------
        response_text : str
            Raw model output (JSON array, or an object with ``cards``).
        issues : list of str, optional
            Issue list that receives ``invalid_<field>`` codes whenever a
            critical field held a malformed value, so the cause survives the
            normalization to ``None``.

        Returns
        -------
        list of dict
            Card dictionaries with critical numeric fields normalized to a
            float (valid) or ``None`` (missing/invalid); empty when the
            response cannot be parsed.
        """
        payload = self._load_json(response_text)
        if payload is None:
            logger.warning("Could not parse standard pass response as JSON")
            return []

        return self._normalize_cards(self._coerce_to_cards(payload), issues=issues)

    def _parse_focused_cards(self, response_text, issues=None):
        """Parse a focused-pass response into partial card dictionaries.

        Parameters
        ----------
        response_text : str
            Raw model output, expected to be ``{"cards": [...]}``.
        issues : list of str, optional
            Issue list that receives ``invalid_<field>`` codes for malformed
            critical values found in the focused pass.

        Returns
        -------
        list of dict
            Partial card dictionaries limited to the critical fields.
        """
        payload = self._load_json(response_text)
        if payload is None:
            logger.warning("Could not parse focused pass response as JSON")
            return []

        focused_cards = []
        for card in self._coerce_to_cards(payload):
            if not isinstance(card, dict):
                continue
            normalized, statuses = normalize_critical_fields(
                {
                    "name": card.get("name", ""),
                    "annual_fee": card.get("annual_fee"),
                    "interest_rate_apr": card.get("interest_rate_apr"),
                }
            )
            self._record_invalid_fields(statuses, issues)
            focused_cards.append(normalized)
        return focused_cards

    @staticmethod
    def _record_invalid_fields(statuses, issues):
        """Append ``invalid_<field>`` codes for malformed critical values.

        Parameters
        ----------
        statuses : dict
            Mapping of field name to normalization status.
        issues : list of str, optional
            Issue list to append to; ``None`` disables recording.

        Returns
        -------
        None
        """
        if issues is None:
            return
        for name, status in statuses.items():
            code = f"invalid_{name}"
            if status == STATUS_INVALID and code not in issues:
                issues.append(code)

    @staticmethod
    def _normalize_cards(cards, issues=None):
        """Normalize critical numeric fields of every card.

        Parameters
        ----------
        cards : list of dict
            Raw card dictionaries.
        issues : list of str, optional
            Issue list that receives ``invalid_<field>`` codes.

        Returns
        -------
        list of dict
            Copies of the cards with ``annual_fee``/``interest_rate_apr``
            replaced by a valid float or ``None``.
        """
        normalized_cards = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            normalized, statuses = normalize_critical_fields(card)
            MultiPassLLMExtractor._record_invalid_fields(statuses, issues)
            normalized_cards.append(normalized)
        return normalized_cards

    @staticmethod
    def _load_json(response_text):
        """Load JSON from a model response, tolerating markdown fences.

        Parameters
        ----------
        response_text : str
            Raw model output.

        Returns
        -------
        object or None
            Parsed JSON payload, or None when nothing could be parsed.
        """
        if not response_text or not isinstance(response_text, str):
            return None

        cleaned = re.sub(r"```json\s*|\s*```", "", response_text.strip()).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"([\[\{].*[\]\}])", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    return None
            return None

    @staticmethod
    def _coerce_to_cards(payload):
        """Coerce a parsed JSON payload into a list of card dictionaries.

        Parameters
        ----------
        payload : object
            Parsed JSON payload (list, dict with ``cards``/``credit_cards``,
            or a single card dict).

        Returns
        -------
        list of dict
            Card dictionaries.
        """
        if isinstance(payload, list):
            cards = payload
        elif isinstance(payload, dict):
            for key in ("cards", "credit_cards", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    cards = value
                    break
            else:
                cards = [payload]
        else:
            return []
        return [card for card in cards if isinstance(card, dict)]

    @classmethod
    def merge_cards(cls, base_cards, focused_cards):
        """Merge a standard-pass result with a focused-pass result.

        Merge rules (all preserve source data):

        * cards are matched by normalized card name when both sides have one;
        * otherwise positionally, when the standard pass has no usable names;
        * focused values only fill fields that are missing in the base card,
          so a standard-pass value is never overwritten;
        * focused cards that match nothing are appended (their data is kept).

        Parameters
        ----------
        base_cards : list of dict
            Cards from the standard pass.
        focused_cards : list of dict
            Cards from the focused pass.

        Returns
        -------
        list of dict
            Merged cards.
        """
        base = [dict(card) for card in (base_cards or []) if isinstance(card, dict)]
        focused = [dict(card) for card in (focused_cards or []) if isinstance(card, dict)]

        if not base:
            return focused
        if not focused:
            return base

        merged = [dict(card) for card in base]
        used_indexes = set()

        for focused_card in focused:
            index = cls._match_index(merged, used_indexes, focused_card)
            if index is None:
                merged.append(focused_card)
                continue

            used_indexes.add(index)
            merged[index] = cls._fill_missing(merged[index], focused_card)

        return merged

    @classmethod
    def _match_index(cls, merged, used_indexes, focused_card):
        """Find the base card a focused card belongs to.

        Matching order:

        1. by normalized card name, when both sides have a usable name;
        2. positionally, against the first base card without a usable name.

        Parameters
        ----------
        merged : list of dict
            Cards accumulated from the standard pass.
        used_indexes : set of int
            Indexes already merged into another focused card.
        focused_card : dict
            Partial card from the focused pass.

        Returns
        -------
        int or None
            Index of the matching base card, or ``None`` when there is none.
        """
        focused_name = cls._card_key(focused_card.get("name"))
        if focused_name:
            for i, base_card in enumerate(merged):
                if i in used_indexes:
                    continue
                if cls._card_key(base_card.get("name")) == focused_name:
                    return i

        for i, base_card in enumerate(merged):
            if i in used_indexes:
                continue
            if not cls._card_key(base_card.get("name")):
                return i
        return None

    @staticmethod
    def _fill_missing(base_card, focused_card):
        """Copy focused values into a base card without overwriting data.

        For critical numeric fields "fillable" means the base value is not a
        *valid* number (missing **or** invalid); for every other key the normal
        missing-marker rule applies.

        Parameters
        ----------
        base_card : dict
            Card from the standard pass.
        focused_card : dict
            Partial card from the focused pass.

        Returns
        -------
        dict
            Base card with missing values filled from the focused card.
        """
        merged = dict(base_card)
        for key, value in focused_card.items():
            if key == "name":
                # Only adopt a focused name when the base card has none.
                if is_missing_marker(merged.get("name")):
                    merged["name"] = value
                continue
            if key in CRITICAL_FIELDS:
                if critical_field_status(merged, key) != STATUS_VALID:
                    merged[key] = value
                continue
            if key not in merged or is_missing_marker(merged.get(key)):
                merged[key] = value
        return merged

    @staticmethod
    def _card_key(name):
        """Normalize a card name for matching.

        Parameters
        ----------
        name : str
            Card name.

        Returns
        -------
        str
            Normalized name (lowercase, alphanumeric only).
        """
        if not name or not isinstance(name, str):
            return ""
        return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()

    # ------------------------------------------------------------------
    # Provenance helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_pass_record(pass_name, provider_used, cards, quality):
        """Build a provenance record for one pass.

        Parameters
        ----------
        pass_name : str
            Pass name (``standard``, ``focused``, ``validation``).
        provider_used : str or None
            Provider that answered the pass.
        cards : list of dict
            Cards produced by the pass.
        quality : ExtractionQuality
            Quality outcome for the pass.

        Returns
        -------
        dict
            Provenance record stored on ``CrawledContent.extraction_passes``.
        """
        return {
            "pass": pass_name,
            "provider": provider_used,
            "cards_found": len(cards),
            "confidence": quality.confidence,
            "missing_critical_fields": list(quality.missing_critical_fields),
            "issues": list(quality.issues),
        }

    def unextracted_critical_fields(self, cards):
        """List critical fields that were not extracted across a set of cards.

        Parameters
        ----------
        cards : list of dict
            Cards to inspect.

        Returns
        -------
        list of str
            Field names that are missing or hold an invalid value.
        """
        missing = []
        for card in cards or []:
            if not isinstance(card, dict):
                continue
            states = critical_field_states(card)
            for name in CRITICAL_FIELDS:
                if states[name] != STATUS_VALID and name not in missing:
                    missing.append(name)
        return missing
