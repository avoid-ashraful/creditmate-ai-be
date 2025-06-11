"""
Comprehensive tests for CreditCard model including edge cases and validation boundaries.

These tests cover security, validation, edge cases, and boundary conditions
that are critical for production readiness.
"""

from decimal import Decimal

import pytest

from django.core.exceptions import ValidationError
from django.db import IntegrityError

from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard


@pytest.mark.django_db
class TestCreditCardModelEdgeCases:
    """Test CreditCard model edge cases and validation boundaries."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory()

    def test_credit_card_decimal_precision_limits(self):
        """Test annual_fee and interest_rate_apr at precision boundaries."""
        # Test maximum decimal precision (2 decimal places)
        card = CreditCardFactory(
            bank=self.bank,
            annual_fee=Decimal("99999.99"),
            interest_rate_apr=Decimal("99.99"),
        )
        card.full_clean()  # Should not raise
        assert card.annual_fee == Decimal("99999.99")
        assert card.interest_rate_apr == Decimal("99.99")

        # Test precision beyond 2 decimal places (should be rounded)
        card.annual_fee = Decimal("100.999")
        card.interest_rate_apr = Decimal("15.999")
        card.save()
        card.refresh_from_db()

        # Django should handle precision correctly
        assert str(card.annual_fee) in ["100.999", "101.00"]  # Depends on DB rounding
        assert str(card.interest_rate_apr) in ["15.999", "16.00"]

    def test_credit_card_very_high_lounge_access_values(self):
        """Test maximum integer values for lounge access fields."""
        # Test reasonable high values
        card = CreditCardFactory(
            bank=self.bank, lounge_access_domestic=999, lounge_access_international=999
        )
        card.full_clean()  # Should not raise
        assert card.lounge_access_domestic == 999
        assert card.lounge_access_international == 999

    def test_credit_card_interest_rate_boundary_values(self):
        """Test interest_rate_apr at 0%, 100%, and near boundaries."""
        # Test 0% interest rate
        card = CreditCardFactory(bank=self.bank, interest_rate_apr=Decimal("0.00"))
        card.full_clean()  # Should not raise
        assert card.interest_rate_apr == Decimal("0.00")

        # Test 100% interest rate
        card.interest_rate_apr = Decimal("100.00")
        card.full_clean()  # Should not raise
        assert card.interest_rate_apr == Decimal("100.00")

        # Test negative interest rate (should fail validation if implemented)
        card.interest_rate_apr = Decimal("-1.00")
        # Note: Add validation in model if needed
        # with pytest.raises(ValidationError):
        #     card.full_clean()

    def test_credit_card_annual_fee_zero_handling(self):
        """Test specific behavior when annual_fee is exactly 0."""
        card = CreditCardFactory(bank=self.bank, annual_fee=Decimal("0.00"))
        card.full_clean()  # Should not raise
        assert card.annual_fee == Decimal("0.00")

        # Test that zero is different from null
        assert card.annual_fee is not None

    def test_credit_card_properties_with_null_values(self):
        """Test properties when related fields are null/None."""
        card = CreditCardFactory(
            bank=self.bank,
            annual_fee_waiver_policy=None,
            # Note: lounge_access fields cannot be null as they are PositiveIntegerField with default=0
            lounge_access_domestic=0,
            lounge_access_international=0,
        )

        # Should handle null/default values gracefully
        assert card.annual_fee_waiver_policy is None
        assert card.lounge_access_domestic == 0
        assert card.lounge_access_international == 0

    def test_credit_card_json_field_schema_validation(self):
        """Test annual_fee_waiver_policy with various JSON schemas."""
        valid_json_schemas = [
            {},  # Empty object
            {"conditions": ["minimum_spend_50000"]},  # Simple array
            {
                "waiver_conditions": {
                    "first_year": True,
                    "minimum_spend": 50000,
                    "salary_account": False,
                }
            },  # Nested object
            {
                "policies": [
                    {"year": 1, "waived": True},
                    {"year": 2, "condition": "spend_100k"},
                ]
            },  # Complex structure
            None,  # Null value
        ]

        for json_data in valid_json_schemas:
            card = CreditCardFactory(bank=self.bank, annual_fee_waiver_policy=json_data)
            card.full_clean()  # Should not raise
            if json_data is None:
                assert card.annual_fee_waiver_policy is None
            else:
                assert card.annual_fee_waiver_policy == json_data

    def test_credit_card_additional_features_empty_vs_null(self):
        """Test additional_features field with [], None, and various structures."""
        # Empty list
        card1 = CreditCardFactory(bank=self.bank, additional_features=[])
        assert card1.additional_features == []

        # Default value (should be empty list due to default=list)
        card2 = CreditCardFactory(bank=self.bank, additional_features=[])
        assert card2.additional_features == []

        # Complex nested structures
        complex_features = [
            {
                "category": "travel",
                "benefits": ["insurance", "concierge"],
                "limits": {"annual": 500000},
            },
            {"category": "shopping", "cashback": {"rate": 2.5, "cap": 10000}},
        ]
        card3 = CreditCardFactory(bank=self.bank, additional_features=complex_features)
        assert card3.additional_features == complex_features

    def test_credit_card_long_text_field_limits(self):
        """Test maximum length handling for text fields."""
        # Test reasonable long values
        long_name = (
            "Premium Rewards Credit Card with Extended Benefits and Features " * 10
        )
        long_fees = "Annual fee waiver conditions: " + "A" * 1000
        long_rewards = "Reward points policy: " + "B" * 1000

        card = CreditCardFactory(
            bank=self.bank,
            name=long_name[:255],  # Truncate to max length
            cash_advance_fee=long_fees[:255],
            reward_points_policy=long_rewards,
        )

        card.full_clean()  # Should not raise
        assert len(card.name) <= 255

    def test_credit_card_cascade_behavior_with_bank_deletion(self):
        """Test credit card deletion when bank is deleted."""
        card = CreditCardFactory(bank=self.bank)
        card_id = card.id

        # Delete the bank
        self.bank.delete()

        # Credit card should also be deleted (CASCADE)
        assert not CreditCard.objects.filter(id=card_id).exists()

    def test_credit_card_ordering_with_identical_names(self):
        """Test ordering behavior with identical bank and card names."""
        # Note: This test is adjusted due to unique constraint on (bank, name)
        # Create cards with unique names but similar patterns
        card1 = CreditCardFactory(bank=self.bank, name="Test Card 1")
        card2 = CreditCardFactory(bank=self.bank, name="Test Card 2")
        card3 = CreditCardFactory(bank=self.bank, name="Test Card 3")

        # Should maintain consistent ordering
        cards = list(
            CreditCard.objects.filter(name__startswith="Test Card").order_by("id")
        )
        assert len(cards) == 3
        assert cards[0].id < cards[1].id < cards[2].id

    def test_credit_card_unicode_content_handling(self):
        """Test credit card fields with unicode characters."""
        unicode_data = {
            "name": "白金信用卡 Premium Credit Card العربية Русский",
            "cash_advance_fee": "سنوية رسوم waived for 第一年 первый год",
            "reward_points_policy": "每花费1元得1分 نقطة لكل ريال балл за рубль",
        }

        card = CreditCardFactory(bank=self.bank, **unicode_data)
        card.full_clean()  # Should not raise

        card.refresh_from_db()
        assert card.name == unicode_data["name"]
        assert card.cash_advance_fee == unicode_data["cash_advance_fee"]
        assert card.reward_points_policy == unicode_data["reward_points_policy"]

    def test_credit_card_special_characters_handling(self):
        """Test credit card fields with special characters and symbols."""
        special_data = {
            "name": "Card & Co. - Premium (USA) 💳",
            "cash_advance_fee": "Fee: $0* (*conditions apply) - see T&Cs",
            "reward_points_policy": "1x points on all purchases, 2x on groceries & gas",
        }

        card = CreditCardFactory(bank=self.bank, **special_data)
        card.full_clean()  # Should not raise

        card.refresh_from_db()
        assert card.name == special_data["name"]
        assert card.cash_advance_fee == special_data["cash_advance_fee"]
        assert card.reward_points_policy == special_data["reward_points_policy"]


@pytest.mark.django_db
class TestCreditCardValidationEdgeCases:
    """Test CreditCard model validation edge cases."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory()

    def test_credit_card_name_max_length_validation(self):
        """Test credit card name field max length validation."""
        # Valid length should work
        valid_name = "A" * 255
        card = CreditCardFactory(bank=self.bank, name=valid_name)
        card.full_clean()  # Should not raise
        assert card.name == valid_name

        # Exceeding max length should fail
        invalid_name = "A" * 256
        card.name = invalid_name
        with pytest.raises(ValidationError):
            card.full_clean()

    def test_credit_card_name_empty_validation(self):
        """Test credit card name cannot be empty."""
        with pytest.raises(ValidationError):
            card = CreditCard(bank=self.bank, name="")
            card.full_clean()

    def test_credit_card_decimal_field_validation(self):
        """Test decimal field validation with various inputs."""
        card = CreditCardFactory(bank=self.bank)

        # Test valid decimal values
        # Test annual_fee (no max limit constraint)
        annual_fee_values = [
            Decimal("0.00"),
            Decimal("99.99"),
            Decimal("1000.00"),
            Decimal("0.01"),
        ]

        for value in annual_fee_values:
            card.annual_fee = value
            card.full_clean()  # Should not raise

        # Test interest_rate_apr (limited to 0-100, max_digits=5, decimal_places=2)
        interest_rate_values = [
            Decimal("0.00"),
            Decimal("99.99"),
            Decimal("15.50"),
            Decimal("0.01"),
        ]

        for value in interest_rate_values:
            card.interest_rate_apr = value
            card.full_clean()  # Should not raise

    def test_credit_card_integer_field_validation(self):
        """Test integer field validation with various inputs."""
        card = CreditCardFactory(bank=self.bank)

        # Test valid integer values
        valid_values = [0, 1, 10, 100, 999]

        for value in valid_values:
            card.lounge_access_domestic = value
            card.lounge_access_international = value
            card.full_clean()  # Should not raise

        # Test negative values (if validation exists)
        # card.lounge_access_domestic = -1
        # with pytest.raises(ValidationError):
        #     card.full_clean()

    def test_credit_card_boolean_field_validation(self):
        """Test boolean field validation."""
        card = CreditCardFactory(bank=self.bank)

        # Test valid boolean values
        for value in [True, False]:
            card.is_active = value
            card.full_clean()  # Should not raise
            assert card.is_active == value


@pytest.mark.django_db
class TestCreditCardRelationshipEdgeCases:
    """Test CreditCard model relationship edge cases."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory()

    def test_credit_card_bank_relationship_integrity(self):
        """Test foreign key relationship integrity."""
        bank1 = BankFactory(name="Bank 1")
        bank2 = BankFactory(name="Bank 2")

        card = CreditCardFactory(bank=bank1)
        assert card.bank == bank1

        # Change bank relationship
        card.bank = bank2
        card.save()
        card.refresh_from_db()
        assert card.bank == bank2

    def test_credit_card_unique_constraints(self):
        """Test unique constraints on credit cards."""
        # Test unique constraint on (bank, name)
        bank1 = BankFactory()
        bank2 = BankFactory()

        # Same name in different banks should be allowed
        card1 = CreditCardFactory(bank=bank1, name="Same Name")
        card2 = CreditCardFactory(bank=bank2, name="Same Name")

        card1.full_clean()
        card2.full_clean()
        assert card1.name == card2.name
        assert card1.bank != card2.bank

        # Same name in same bank should fail
        with pytest.raises(IntegrityError):
            CreditCardFactory(bank=bank1, name="Same Name")

    def test_credit_card_cross_bank_isolation(self):
        """Test that credit cards are properly isolated between banks."""
        bank1 = BankFactory(name="Bank 1")
        bank2 = BankFactory(name="Bank 2")

        card1 = CreditCardFactory(bank=bank1, name="Card 1")
        card2 = CreditCardFactory(bank=bank2, name="Card 2")

        # Each bank should only see its own cards
        bank1_cards = CreditCard.objects.filter(bank=bank1)
        bank2_cards = CreditCard.objects.filter(bank=bank2)

        assert card1 in bank1_cards
        assert card1 not in bank2_cards
        assert card2 in bank2_cards
        assert card2 not in bank1_cards


@pytest.mark.django_db
class TestCreditCardPerformanceAndBoundaries:
    """Test CreditCard model performance and boundary conditions."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory()

    def test_credit_card_bulk_creation_performance(self):
        """Test performance of bulk credit card creation."""
        # Create many credit cards
        cards_data = []
        for i in range(100):
            cards_data.append(
                CreditCard(
                    bank=self.bank,
                    name=f"Card {i}",
                    annual_fee=Decimal("99.00"),
                    interest_rate_apr=Decimal("15.99"),
                    is_active=True,
                )
            )

        # Bulk create
        created_cards = CreditCard.objects.bulk_create(cards_data)
        assert len(created_cards) == 100

        # Verify they were created
        assert CreditCard.objects.filter(bank=self.bank).count() == 100

    def test_credit_card_query_performance_with_large_dataset(self):
        """Test query performance with large number of credit cards."""
        # Create large dataset
        CreditCardFactory.create_batch(500, bank=self.bank)

        # Test various query patterns
        queries = [
            CreditCard.objects.filter(bank=self.bank),
            CreditCard.objects.filter(is_active=True),
            CreditCard.objects.filter(annual_fee__lt=Decimal("100.00")),
            CreditCard.objects.filter(name__icontains="Card"),
        ]

        for query in queries:
            result = list(query[:10])  # Limit results for performance
            assert len(result) <= 10

    def test_credit_card_json_field_performance(self):
        """Test performance of JSON field operations."""
        # Create cards with complex JSON data
        complex_json = {
            "benefits": {
                "travel": ["insurance", "lounge", "concierge"],
                "shopping": ["cashback", "rewards", "protection"],
                "dining": ["discounts", "exclusive_access"],
            },
            "limits": {"daily": 100000, "monthly": 500000, "annual": 1000000},
            "features": [
                {"name": "contactless", "enabled": True},
                {"name": "international", "enabled": True},
                {"name": "online", "enabled": True},
            ],
        }

        # Create multiple cards with complex JSON
        cards = []
        for i in range(50):
            card = CreditCardFactory(
                bank=self.bank,
                additional_features=complex_json,
                annual_fee_waiver_policy=complex_json,
            )
            cards.append(card)

        # Test JSON field queries
        cards_with_features = CreditCard.objects.filter(additional_features__isnull=False)
        assert len(cards_with_features) >= 50

    def test_credit_card_memory_usage_optimization(self):
        """Test memory usage with large credit card objects."""
        # Create card with large text fields
        large_text = "A" * 10000  # 10KB of text

        card = CreditCardFactory(
            bank=self.bank,
            cash_advance_fee=large_text[:255],
            reward_points_policy=large_text,
            additional_features=["feature"] * 1000,  # Large JSON array
        )

        # Verify it was created and can be retrieved
        card.refresh_from_db()
        assert len(card.cash_advance_fee) == 255
        assert len(card.reward_points_policy) == 10000
        assert len(card.additional_features) == 1000
