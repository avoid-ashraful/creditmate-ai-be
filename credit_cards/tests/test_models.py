from decimal import Decimal

import pytest

from django.core.exceptions import ValidationError
from django.db import IntegrityError

from banks.factories import BankFactory
from credit_cards.factories import (
    CreditCardFactory,
    NormalCreditCardFactory,
    PremiumCreditCardFactory,
)
from credit_cards.models import CreditCard


@pytest.mark.django_db
class TestCreditCardModel:
    """Test CreditCard model functionality."""

    def test_credit_card_creation(self):
        """Test that a credit card can be created successfully."""
        card = CreditCardFactory()
        assert card.id is not None
        assert card.name
        assert card.bank_id is not None
        assert card.is_active is True
        assert card.created is not None
        assert card.modified is not None

    def test_credit_card_str_representation(self):
        """Test string representation of CreditCard."""
        bank = BankFactory(name="Test Bank")
        card = CreditCardFactory(bank=bank, name="Test Card")
        assert str(card) == "Test Bank - Test Card"

    def test_credit_card_unique_together(self):
        """Test that bank and name combination must be unique."""
        bank = BankFactory()
        CreditCardFactory(bank=bank, name="Unique Card")

        with pytest.raises(IntegrityError):
            CreditCardFactory(bank=bank, name="Unique Card")

    def test_credit_card_different_banks_same_name(self):
        """Test that different banks can have cards with same name."""
        bank1 = BankFactory(name="Bank 1")
        bank2 = BankFactory(name="Bank 2")

        card1 = CreditCardFactory(bank=bank1, name="Premium Card")
        card2 = CreditCardFactory(bank=bank2, name="Premium Card")

        assert card1.name == card2.name
        assert card1.bank != card2.bank

    def test_annual_fee_validation(self):
        """Test annual fee validation."""
        with pytest.raises(ValidationError):
            card = CreditCard(
                bank=BankFactory(),
                name="Test Card",
                annual_fee=Decimal("-100"),  # Negative fee
                interest_rate_apr=Decimal("25.0"),
            )
            card.full_clean()

    def test_interest_rate_validation(self):
        """Test interest rate validation."""
        bank = BankFactory()

        # Test negative interest rate
        with pytest.raises(ValidationError):
            card = CreditCard(
                bank=bank,
                name="Test Card 1",
                annual_fee=Decimal("1000"),
                interest_rate_apr=Decimal("-5.0"),
            )
            card.full_clean()

        # Test interest rate > 100%
        with pytest.raises(ValidationError):
            card = CreditCard(
                bank=bank,
                name="Test Card 2",
                annual_fee=Decimal("1000"),
                interest_rate_apr=Decimal("150.0"),
            )
            card.full_clean()

    # Note: URL validation test removed as source_url field no longer exists

    def test_has_lounge_access_property(self):
        """Test has_lounge_access property."""
        # Card with no lounge access
        card1 = CreditCardFactory(
            lounge_access_international="", lounge_access_domestic=""
        )
        assert card1.has_lounge_access is False

        # Card with international lounge access
        card2 = CreditCardFactory(
            lounge_access_international="5 visits", lounge_access_domestic=""
        )
        assert card2.has_lounge_access is True

        # Card with domestic lounge access
        card3 = CreditCardFactory(
            lounge_access_international="", lounge_access_domestic="3 visits"
        )
        assert card3.has_lounge_access is True

        # Card with both
        card4 = CreditCardFactory(
            lounge_access_international="2 visits", lounge_access_domestic="4 visits"
        )
        assert card4.has_lounge_access is True

    def test_has_annual_fee_property(self):
        """Test has_annual_fee property."""
        # Card with no annual fee
        card1 = CreditCardFactory(annual_fee=Decimal("0"))
        assert card1.has_annual_fee is False

        # Card with annual fee
        card2 = CreditCardFactory(annual_fee=Decimal("1500"))
        assert card2.has_annual_fee is True

    def test_credit_card_ordering(self):
        """Test that credit cards are ordered by bank name, then card name."""
        bank_b = BankFactory(name="B Bank")
        bank_a = BankFactory(name="A Bank")

        card_b2 = CreditCardFactory(bank=bank_b, name="Z Card")
        card_a1 = CreditCardFactory(bank=bank_a, name="A Card")
        card_b1 = CreditCardFactory(bank=bank_b, name="A Card")
        card_a2 = CreditCardFactory(bank=bank_a, name="Z Card")

        cards = CreditCard.objects.all()
        expected_order = [card_a1, card_a2, card_b1, card_b2]
        assert list(cards) == expected_order

    def test_credit_card_defaults(self):
        """Test default values for credit card fields."""
        bank = BankFactory()
        card = CreditCard.objects.create(
            bank=bank,
            name="Test Card",
            annual_fee=Decimal("1000"),
            interest_rate_apr=Decimal("25.0"),
        )

        assert card.lounge_access_international == ""
        assert card.lounge_access_domestic == ""
        assert card.cash_advance_fee == ""
        assert card.late_payment_fee == ""
        assert card.annual_fee_waiver_policy is None
        assert card.reward_points_policy == ""
        assert card.additional_features == []
        # Note: source_url field removed
        assert card.is_active is True

    def test_json_fields(self):
        """Test JSON field functionality."""
        card = CreditCardFactory(
            annual_fee_waiver_policy={
                "minimum_spend": 100000,
                "waiver_period": "first_year",
            },
            additional_features=["travel_insurance", "purchase_protection"],
        )

        assert card.annual_fee_waiver_policy["minimum_spend"] == 100000
        assert "travel_insurance" in card.additional_features

    def test_premium_credit_card_factory(self):
        """Test PremiumCreditCardFactory generates premium cards."""
        card = PremiumCreditCardFactory()

        assert card.annual_fee >= Decimal("2000")
        assert card.lounge_access_international != ""
        assert card.lounge_access_domestic != ""

    def test_normal_credit_card_factory(self):
        """Test NormalCreditCardFactory generates normal cards."""
        card = NormalCreditCardFactory()

        assert card.annual_fee <= Decimal("1000")
        assert card.lounge_access_international != ""
        assert card.lounge_access_domestic != ""

    def test_credit_card_factory_unique_names(self):
        """Test that CreditCardFactory generates unique names."""
        cards = CreditCardFactory.create_batch(5)
        names = [card.name for card in cards]

        # Names should be unique
        assert len(names) == len(set(names))
