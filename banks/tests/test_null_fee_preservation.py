"""Genuine zero versus missing data must never be conflated (Phase 1.1).

A free card (fee 0) is a value; a fee the document never stated is NULL; a
malformed value ("abc", booleans, NaN, negative numbers) is also NULL and is
reported as invalid - never silently converted into a 0 that would invent a
"free card".
"""

import math

import pytest

from banks.factories import BankFactory
from banks.services.credit_card_data_service import CreditCardDataService
from banks.validators.credit_card_validator import CreditCardDataValidator
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard


def sanitize(card):
    """Run the real validation stage's sanitize step on one card dict."""
    return CreditCardDataValidator.sanitize_credit_card_data([card])[0]


class TestSanitizeKeepsZeroDistinctFromMissing:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (0, 0.0),
            (0.0, 0.0),
            ("Free", 0.0),
            ("Nil", 0.0),
            ("No annual fee", 0.0),
            (95, 95.0),
            ("TK 5,000", 5000.0),
            ("BDT 500", 500.0),
        ],
    )
    def test_valid_values_including_zero(self, raw, expected):
        card = sanitize({"name": "Gold", "annual_fee": raw})
        assert card["annual_fee"] == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "$95.00",  # foreign currency must not be relabeled as BDT
            "USD 100",
            "20% p.a.",  # a rate is not an annual fee amount
            "100 per month",  # a monthly amount is not an annual fee
            "Waived",  # a waiver may be conditional, so it stays unknown
        ],
    )
    def test_unit_and_period_values_stay_null(self, raw):
        card = sanitize({"name": "Gold", "annual_fee": raw})
        assert card["annual_fee"] is None

    @pytest.mark.parametrize(
        "raw",
        [None, "", "   ", "N/A", "unknown", "-", "not mentioned", "Not specified"],
    )
    def test_missing_stays_null(self, raw):
        card = sanitize({"name": "Gold", "annual_fee": raw})
        assert card["annual_fee"] is None

    @pytest.mark.parametrize(
        "raw",
        [
            "abc",
            "12abc",
            True,
            False,
            float("nan"),
            float("inf"),
            -50,
            120000,
            [5000],
        ],
    )
    def test_invalid_stays_null_not_zero(self, raw):
        card = sanitize({"name": "Gold", "annual_fee": raw})
        assert card["annual_fee"] is None

    def test_nan_never_survives_sanitize(self):
        card = sanitize(
            {"name": "Gold", "annual_fee": math.nan, "interest_rate_apr": math.inf}
        )
        assert card["annual_fee"] is None
        assert card["interest_rate_apr"] is None

    def test_missing_fields_are_still_created_as_null(self):
        card = sanitize({"name": "Gold"})
        assert card["annual_fee"] is None
        assert card["interest_rate_apr"] is None


class TestValidationStageAcceptsZeroRejectsGarbage:
    @pytest.mark.parametrize("fee", [0, 0.0, "Free", "Nil"])
    def test_genuine_zero_is_valid(self, fee):
        is_valid, errors = CreditCardDataValidator.validate_credit_card_data(
            {"name": "Free Card", "annual_fee": fee, "interest_rate_apr": 18.0}
        )
        assert is_valid, errors

    @pytest.mark.parametrize("fee", [None, ""])
    def test_missing_fee_is_allowed_but_flagged_by_scoring(self, fee):
        # The validator must not invent a value; absence is the scorer's job.
        is_valid, errors = CreditCardDataValidator.validate_credit_card_data(
            {"name": "Card", "annual_fee": fee, "interest_rate_apr": None}
        )
        assert is_valid, errors

    @pytest.mark.parametrize(
        "fee,expected_fragment",
        [(-50, "negative"), (True, "Invalid"), (float("nan"), "Invalid")],
    )
    def test_invalid_fee_is_rejected(self, fee, expected_fragment):
        _, errors = CreditCardDataValidator.validate_credit_card_data(
            {"name": "Card", "annual_fee": fee, "interest_rate_apr": 18.0}
        )
        assert any(expected_fragment in error for error in errors), errors

    @pytest.mark.parametrize("apr", [150, -1, float("inf"), True])
    def test_invalid_apr_is_rejected(self, apr):
        _, errors = CreditCardDataValidator.validate_credit_card_data(
            {"name": "Card", "annual_fee": 100, "interest_rate_apr": apr}
        )
        assert errors

    @pytest.mark.parametrize("apr", [0, 0.0, 18.99, 100])
    def test_valid_apr_is_accepted(self, apr):
        is_valid, errors = CreditCardDataValidator.validate_credit_card_data(
            {"name": "Card", "annual_fee": 100, "interest_rate_apr": apr}
        )
        assert is_valid, errors

    def test_missing_name_is_rejected(self):
        is_valid, errors = CreditCardDataValidator.validate_credit_card_data(
            {"name": "", "annual_fee": 100}
        )
        assert not is_valid
        assert any("name" in error.lower() for error in errors)


@pytest.mark.django_db
class TestDataServiceStoresNullNotZero:
    """The write path must keep NULL for unknown/invalid values."""

    @pytest.mark.parametrize(
        "raw_fee,expected",
        [
            (0, 0),
            (0.0, 0),
            ("Free", 0),
            ("TK 5,000", 5000),
            (None, None),
            ("N/A", None),
            ("invalid_decimal", None),
            ("not_a_number", None),
            (True, None),
            (-50, None),
        ],
    )
    def test_update_writes_expected_fee(self, raw_fee, expected):
        bank = BankFactory()
        service = CreditCardDataService()
        service.update_credit_card_data(
            bank.id,
            [
                {
                    "name": "Zero vs Null Card",
                    "annual_fee": raw_fee,
                    "interest_rate_apr": None,
                }
            ],
        )
        card = CreditCard.objects.get(bank=bank, name="Zero vs Null Card")
        if expected is None:
            assert card.annual_fee is None
        else:
            assert card.annual_fee == expected

    def test_invalid_values_do_not_create_free_cards(self):
        bank = BankFactory()
        service = CreditCardDataService()
        service.update_credit_card_data(
            bank.id,
            [
                {"name": "Broken Card", "annual_fee": "invalid_decimal"},
                {"name": "Free Card", "annual_fee": 0},
            ],
        )
        broken = CreditCard.objects.get(bank=bank, name="Broken Card")
        free = CreditCard.objects.get(bank=bank, name="Free Card")

        assert broken.annual_fee is None  # NULL, not 0.00
        assert free.annual_fee == 0  # genuine zero preserved

    def test_fallback_name_does_not_invent_a_fee(self):
        bank = BankFactory()
        service = CreditCardDataService()
        service.update_credit_card_data(bank.id, [{"name": "", "annual_fee": "bogus"}])
        card = CreditCard.objects.get(bank=bank)
        assert "Credit Card (Annual Fee:" in card.name
        assert "bogus" not in card.name
        assert card.annual_fee is None

    def test_existing_card_keeps_null_when_new_value_is_invalid(self):
        bank = BankFactory()
        card = CreditCardFactory(bank=bank, name="Platinum", annual_fee=5000)
        service = CreditCardDataService()
        service.update_credit_card_data(
            bank.id, [{"name": "Platinum", "annual_fee": "not-a-number"}]
        )
        card.refresh_from_db()
        assert card.annual_fee is None

    def test_parse_decimal_rules_match_sanitize_rules(self):
        service = CreditCardDataService()
        assert service._parse_decimal(0) == 0.0
        assert service._parse_decimal("Free") == 0.0
        assert service._parse_decimal("N/A") is None
        assert service._parse_decimal("abc") is None
        assert service._parse_decimal(None) is None
        assert service._parse_decimal("TK 5,000") == 5000.0
        # APR uses its own bounds and does not accept "free" wording
        assert service._parse_decimal("Free", field="interest_rate_apr") is None
        assert service._parse_decimal("20%", field="interest_rate_apr") == 20.0
        assert service._parse_decimal(150, field="interest_rate_apr") is None
