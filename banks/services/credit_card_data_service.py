import logging
import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from banks.enums import ReviewPriority, ReviewSource, ReviewStatus
from banks.models import Bank, ReviewQueue
from banks.validators.numeric_fields import (
    REASON_OUT_OF_RANGE,
    parse_numeric_value,
    parse_numeric_value_detailed,
)
from credit_cards.constants import MAX_INTEREST_RATE_APR, CardNetwork, VerificationStatus
from credit_cards.models import CreditCard

logger = logging.getLogger(__name__)

#: Proposed values that mean "not stated" and must never replace a known value.
EMPTY_VALUES = (None, "", [], {})

#: Product words that mean the "card" is not a credit card (shared fee schedules
#: list debit and prepaid cards next to the credit cards).
NON_CREDIT_WORDS = {"debit", "prepaid"}

#: Words that carry no card identity when comparing card names.
NAME_NOISE_WORDS = {"credit", "card", "cards", "the", "plc", "ltd", "limited"}


class CreditCardDataService:
    """Service for updating credit card data in the database.

    This service handles the conversion of parsed credit card data from
    various sources into database records, including data normalization,
    validation, and creation/update operations.
    """

    def update_credit_card_data(self, bank_id, parsed_data):
        """Update credit card data in the database.

        Parameters
        ----------
        bank_id : int
            ID of the bank to associate credit cards with
        parsed_data : dict or list
            Parsed credit card data from LLM processing, can be single
            card dict or list of card dicts

        Returns
        -------
        int
            Number of credit cards successfully updated or created
        """
        logger.info(f"Raw parsed data received for bank {bank_id}: {parsed_data}")
        normalized_data = self._normalize_parsed_data(parsed_data)
        logger.info(f"Normalized data: {normalized_data}")
        updated_count = 0

        logger.info(f"Processing {len(normalized_data)} credit cards for bank {bank_id}")
        for i, card_data in enumerate(normalized_data):
            try:
                logger.info(f"Processing card {i+1}: {card_data}")
                updated_count += self._update_single_card(bank_id, card_data)
            except Exception as e:
                logger.error(f"Error updating credit card data: {str(e)}")
                continue

        logger.info(f"Total cards processed: {updated_count}")
        return updated_count

    def _normalize_parsed_data(self, parsed_data):
        """Normalize parsed data to a list format.

        Parameters
        ----------
        parsed_data : dict or list
            Raw parsed data that may be in various formats

        Returns
        -------
        list
            Normalized list of credit card data dictionaries
        """
        if isinstance(parsed_data, list):
            return parsed_data
        elif isinstance(parsed_data, dict):
            # Handle validation error structure: {"validation_errors": [...], "data": [...]}
            if "data" in parsed_data:
                logger.info("Processing data despite validation warnings")
                data_to_process = parsed_data["data"]
                if isinstance(data_to_process, list):
                    return data_to_process
                else:
                    return self._normalize_parsed_data(data_to_process)
            # Handle standard structure: {"credit_cards": [...]}
            elif "credit_cards" in parsed_data:
                return parsed_data["credit_cards"]
            else:
                logger.warning("Parsed data dict does not contain expected keys")
                return []
        else:
            logger.warning("Parsed data is not in expected format")
            return []

    def _update_single_card(self, bank_id, card_data):
        """Create or safely update a single credit card record.

        New cards are created as drafts (not public). A verified card is never
        modified: every differing proposed value becomes a review queue item
        for staff. Draft/needs-review cards are updated, but a known value is
        never replaced with an empty one and ``is_active`` is never changed.

        Parameters
        ----------
        bank_id : int
            ID of the bank to associate the card with
        card_data : dict
            Dictionary containing credit card information and attributes

        Returns
        -------
        int
            1 if the card was created, updated or proposed against, 0 if it
            was skipped (no usable name)
        """
        card_name = (card_data.get("name") or "").strip()
        if (
            not card_name
            or self._looks_like_fee(card_name)
            or NON_CREDIT_WORDS & set(re.findall(r"[a-z]+", card_name.lower()))
        ):
            logger.warning(
                f"Skipping credit card without a usable name for bank {bank_id}: {card_data}"
            )
            return 0

        proposed = {
            field: value
            for field, value in self._prepare_card_defaults(card_data).items()
            if value not in EMPTY_VALUES
        }
        problems = self._sanity_problems(card_data)
        if problems:
            logger.warning(f"Card '{card_name}' failed sanity checks: {problems}")

        card = self._find_card(bank_id, card_name)
        if card is None:
            status = (
                VerificationStatus.NEEDS_REVIEW if problems else VerificationStatus.DRAFT
            )
            card = CreditCard.objects.create(
                bank_id=bank_id, name=card_name, verification_status=status, **proposed
            )
            logger.info(f"Created draft credit card: {card.name} (ID: {card.id})")
        elif card.verification_status == VerificationStatus.VERIFIED:
            self._propose_changes(card, proposed, problems)
        else:
            changed = [
                field
                for field, value in proposed.items()
                if self._differs(getattr(card, field), value)
            ]
            for field in changed:
                setattr(card, field, proposed[field])
            if problems and card.verification_status != VerificationStatus.NEEDS_REVIEW:
                card.verification_status = VerificationStatus.NEEDS_REVIEW
                changed.append("verification_status")
            if changed:
                card.save(update_fields=changed + ["modified"])
            logger.info(f"Updated credit card {card.name} (ID: {card.id}): {changed}")
        return 1

    @staticmethod
    def _name_key(name, bank_name):
        """Return the identity of a card name: lowercase words minus noise and bank name."""
        ignored = NAME_NOISE_WORDS | set(re.findall(r"[a-z0-9]+", bank_name.lower()))
        return frozenset(re.findall(r"[a-z0-9]+", name.lower())) - ignored

    def _find_card(self, bank_id, card_name):
        """Find the bank's card for a crawled name, tolerating naming variants.

        An exact name wins. Otherwise a card whose name only differs by case,
        word order, the bank's own name or "Credit Card" matches, but only when
        exactly one card does; an ambiguous name stays a new draft.

        Parameters
        ----------
        bank_id : int
            ID of the bank the crawl belongs to
        card_name : str
            Card name as extracted

        Returns
        -------
        CreditCard or None
            The matching card, ``None`` when there is no unambiguous match
        """
        exact = CreditCard.objects.filter(bank_id=bank_id, name=card_name).first()
        if exact is not None:
            return exact
        bank_name = Bank.objects.values_list("name", flat=True).get(pk=bank_id)
        key = self._name_key(card_name, bank_name)
        if not key:
            return None
        matches = [
            card
            for card in CreditCard.objects.filter(bank_id=bank_id)
            if self._name_key(card.name, bank_name) == key
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _looks_like_fee(name):
        """Return True when a "name" is really an annual fee value."""
        return (
            name.startswith("TK.")
            or name.startswith("US$")
            or name.replace(",", "").replace(".", "").isdigit()
        )

    @staticmethod
    def _differs(current, proposed):
        """Compare a stored value with a proposed one, treating Decimals numerically."""
        if isinstance(current, Decimal):
            return current != Decimal(str(proposed))
        return current != proposed

    def _propose_changes(self, card, proposed, problems):
        """Queue each differing proposed value for staff review.

        Parameters
        ----------
        card : CreditCard
            Verified card that must not be modified by the crawler
        proposed : dict
            Non-empty proposed field values
        problems : list of str
            Sanity problems found in the extraction (added to the message)

        Returns
        -------
        None
        """
        for field, value in proposed.items():
            current = getattr(card, field)
            if not self._differs(current, value):
                continue
            if ReviewQueue.objects.filter(
                credit_card=card,
                source=ReviewSource.CRAWLER_PROPOSAL,
                status=ReviewStatus.PENDING,
                field_name=field,
                proposed_value=value,
            ).exists():
                continue
            message = f"Crawler proposes {field}: {str(current)!r} -> {value!r}"
            if problems:
                message += f" (sanity: {'; '.join(problems)})"
            ReviewQueue.objects.create(
                bank_id=card.bank_id,
                credit_card=card,
                source=ReviewSource.CRAWLER_PROPOSAL,
                priority=ReviewPriority.MEDIUM,
                field_name=field,
                proposed_value=value,
                message=message,
            )

    def _sanity_problems(self, card_data):
        """Return reasons an extraction must not be published without review.

        Parameters
        ----------
        card_data : dict
            Raw credit card data from parsing

        Returns
        -------
        list of str
            Human readable problems; empty when the values look sane
        """
        problems = list(card_data.get("sanity_flags") or [])
        for field in ("annual_fee", "interest_rate_apr"):
            value, _, reason = parse_numeric_value_detailed(card_data.get(field), field)
            too_high = field == "interest_rate_apr" and (
                value is not None and value > MAX_INTEREST_RATE_APR
            )
            message = f"{field} out of range"
            if (reason == REASON_OUT_OF_RANGE or too_high) and message not in problems:
                problems.append(message)
        return problems

    def _prepare_card_defaults(self, card_data):
        """Prepare normalized field values for credit card creation/update.

        Unknown values come back empty (``None``, ``""`` or ``[]``) so callers
        can avoid overwriting known data; nothing is invented. ``is_active``
        and the verification fields are deliberately not part of the result.

        Parameters
        ----------
        card_data : dict
            Raw credit card data from parsing

        Returns
        -------
        dict
            Normalized values keyed by CreditCard field name
        """
        text = self._text
        return {
            "annual_fee": self._parse_decimal(card_data.get("annual_fee")),
            "interest_rate_apr": self._parse_decimal(
                card_data.get("interest_rate_apr"), field="interest_rate_apr"
            ),
            "lounge_access_international": text(card_data, "lounge_access_international"),
            "lounge_access_domestic": text(card_data, "lounge_access_domestic"),
            "cash_advance_fee": text(card_data, "cash_advance_fee"),
            "late_payment_fee": text(card_data, "late_payment_fee"),
            "annual_fee_waiver_policy": card_data.get("annual_fee_waiver_policy"),
            "reward_points_policy": text(card_data, "reward_points_policy"),
            "additional_features": card_data.get("additional_features") or [],
            "source_url": self._parse_url(card_data.get("source_url")),
            "apply_url": self._parse_url(card_data.get("apply_url")),
            "card_network": self._parse_network(card_data.get("card_network")),
            "is_islamic": self._parse_bool(card_data.get("is_islamic")),
            "is_dual_currency": self._parse_bool(card_data.get("is_dual_currency")),
            "min_monthly_income": self._parse_decimal(
                card_data.get("min_monthly_income"), field="min_monthly_income"
            ),
            "supplementary_card_fee": text(card_data, "supplementary_card_fee"),
            "foreign_transaction_fee": text(card_data, "foreign_transaction_fee"),
        }

    @staticmethod
    def _text(card_data, key):
        """Return a stripped string value, ``""`` when null or missing.

        The value is cut to the model field's ``max_length`` so an over-long
        extraction cannot make the database reject (and drop) the whole card.
        """
        value = str(card_data.get(key) or "").strip()
        max_length = CreditCard._meta.get_field(key).max_length
        return value[:max_length] if max_length else value

    @staticmethod
    def _parse_bool(value):
        """Return True/False for explicit yes/no values, else None (unknown)."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "y", "1"}:
                return True
            if lowered in {"false", "no", "n", "0"}:
                return False
        return None

    @staticmethod
    def _parse_url(value):
        """Return a valid http(s) URL of at most 500 characters, else ``""``."""
        url = str(value or "").strip()
        try:
            URLValidator(schemes=["http", "https"])(url)
        except ValidationError:
            return ""
        return url if len(url) <= 500 else ""

    @staticmethod
    def _parse_network(value):
        """Map a network name to a CardNetwork value, else ``""`` (unknown)."""
        lowered = str(value or "").strip().lower()
        for network in CardNetwork:
            if lowered in {network.value, network.label.lower()}:
                return network.value
        return ""

    def _parse_decimal(self, value, field="annual_fee"):
        """Parse a critical numeric value, preserving zero and NULL semantics.

        Uses the shared normalization rules in
        :mod:`banks.validators.numeric_fields`: valid numbers (including a
        genuine ``0``) become floats, while missing markers and malformed
        values become ``None`` so the database column stays NULL. No default
        value is ever invented.

        Parameters
        ----------
        value : str, int, float, or None
            Value to parse, may contain currency symbols or percentages
        field : str, optional
            Critical field being parsed; selects the allowed bounds and the
            field-specific "free / nil" wording.

        Returns
        -------
        float or None
            Normalized float for valid input, ``None`` for missing/invalid
            input
        """
        normalized, _ = parse_numeric_value(value, field)
        return normalized
