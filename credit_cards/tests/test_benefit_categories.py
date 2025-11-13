"""
Tests for benefit category models and functionality.

This module tests the new benefit category system including:
- BenefitCategory model
- CreditCardBenefit model
- AI classification fields
- Filtering and querying
"""

import pytest
from django.core.exceptions import ValidationError

from banks.models import Bank
from credit_cards.models import BenefitCategory, CreditCard, CreditCardBenefit


@pytest.mark.django_db
class TestBenefitCategory:
    """Test cases for BenefitCategory model."""

    def test_create_benefit_category(self):
        """Test creating a benefit category."""
        category = BenefitCategory.objects.create(
            name="Restaurant & Dining",
            category_type="RESTAURANT",
            description="Benefits on dining",
            mcc_codes=[5812, 5813],
            icon="🍽️",
            display_order=1,
        )

        assert category.name == "Restaurant & Dining"
        assert category.category_type == "RESTAURANT"
        assert category.mcc_codes == [5812, 5813]
        assert category.is_active is True

    def test_benefit_category_unique_name(self):
        """Test that benefit category names must be unique."""
        BenefitCategory.objects.create(
            name="Restaurant & Dining", category_type="RESTAURANT"
        )

        with pytest.raises(Exception):  # IntegrityError
            BenefitCategory.objects.create(
                name="Restaurant & Dining", category_type="HEALTHCARE"
            )

    def test_benefit_category_ordering(self):
        """Test that categories are ordered by display_order."""
        cat1 = BenefitCategory.objects.create(
            name="Category 3", category_type="OTHER", display_order=3
        )
        cat2 = BenefitCategory.objects.create(
            name="Category 1", category_type="OTHER", display_order=1
        )
        cat3 = BenefitCategory.objects.create(
            name="Category 2", category_type="OTHER", display_order=2
        )

        categories = list(BenefitCategory.objects.all())
        assert categories[0] == cat2
        assert categories[1] == cat3
        assert categories[2] == cat1


@pytest.mark.django_db
class TestCreditCardBenefit:
    """Test cases for CreditCardBenefit model."""

    @pytest.fixture
    def bank(self):
        """Create a test bank."""
        return Bank.objects.create(name="Test Bank", website="https://test.com")

    @pytest.fixture
    def credit_card(self, bank):
        """Create a test credit card."""
        return CreditCard.objects.create(
            bank=bank,
            name="Test Card",
            annual_fee=1000,
            interest_rate_apr=18.0,
        )

    @pytest.fixture
    def benefit_category(self):
        """Create a test benefit category."""
        return BenefitCategory.objects.create(
            name="Restaurant & Dining",
            category_type="RESTAURANT",
        )

    def test_create_credit_card_benefit(self, credit_card, benefit_category):
        """Test creating a credit card benefit relationship."""
        benefit = CreditCardBenefit.objects.create(
            credit_card=credit_card,
            benefit_category=benefit_category,
            reward_rate=5.0,
            reward_description="5% cashback on dining",
            conditions="Valid at all restaurants",
            is_primary=True,
            confidence_score=95,
        )

        assert benefit.credit_card == credit_card
        assert benefit.benefit_category == benefit_category
        assert benefit.reward_rate == 5.0
        assert benefit.is_primary is True

    def test_credit_card_benefit_unique_together(
        self, credit_card, benefit_category
    ):
        """Test that credit_card and benefit_category combination must be unique."""
        CreditCardBenefit.objects.create(
            credit_card=credit_card,
            benefit_category=benefit_category,
            reward_rate=5.0,
        )

        with pytest.raises(Exception):  # IntegrityError
            CreditCardBenefit.objects.create(
                credit_card=credit_card,
                benefit_category=benefit_category,
                reward_rate=3.0,
            )

    def test_credit_card_benefit_ordering(self, credit_card, benefit_category):
        """Test that benefits are ordered correctly."""
        primary_benefit = CreditCardBenefit.objects.create(
            credit_card=credit_card,
            benefit_category=benefit_category,
            reward_rate=5.0,
            is_primary=True,
        )

        # Create another category for secondary benefit
        secondary_category = BenefitCategory.objects.create(
            name="Shopping",
            category_type="SHOPPING",
        )
        secondary_benefit = CreditCardBenefit.objects.create(
            credit_card=credit_card,
            benefit_category=secondary_category,
            reward_rate=3.0,
            is_primary=False,
        )

        benefits = list(credit_card.card_benefits.all())
        assert benefits[0] == primary_benefit  # Primary first
        assert benefits[1] == secondary_benefit


@pytest.mark.django_db
class TestCreditCardAIFields:
    """Test cases for AI classification fields on CreditCard model."""

    @pytest.fixture
    def bank(self):
        """Create a test bank."""
        return Bank.objects.create(name="Test Bank", website="https://test.com")

    def test_annual_fee_waiver_difficulty_choices(self, bank):
        """Test that annual_fee_waiver_difficulty accepts valid choices."""
        card = CreditCard.objects.create(
            bank=bank,
            name="Easy Waiver Card",
            annual_fee=1000,
            interest_rate_apr=18.0,
            annual_fee_waiver_difficulty="EASY",
        )

        assert card.annual_fee_waiver_difficulty == "EASY"

    def test_spending_tier_choices(self, bank):
        """Test that spending_tier accepts valid choices."""
        card = CreditCard.objects.create(
            bank=bank,
            name="Premium Card",
            annual_fee=10000,
            interest_rate_apr=18.0,
            spending_tier="PREMIUM",
        )

        assert card.spending_tier == "PREMIUM"

    def test_best_for_tags_default(self, bank):
        """Test that best_for_tags has empty list default."""
        card = CreditCard.objects.create(
            bank=bank,
            name="Test Card",
            annual_fee=1000,
            interest_rate_apr=18.0,
        )

        assert card.best_for_tags == []

    def test_best_for_tags_storage(self, bank):
        """Test storing and retrieving best_for_tags."""
        card = CreditCard.objects.create(
            bank=bank,
            name="Cashback Card",
            annual_fee=1000,
            interest_rate_apr=18.0,
            best_for_tags=["Cashback", "Shopping Rewards", "Fuel Savings"],
        )

        assert "Cashback" in card.best_for_tags
        assert "Shopping Rewards" in card.best_for_tags
        assert len(card.best_for_tags) == 3


@pytest.mark.django_db
class TestCreditCardBenefitRelationships:
    """Test cases for credit card benefit category relationships."""

    @pytest.fixture
    def setup_data(self):
        """Set up test data for relationship tests."""
        bank = Bank.objects.create(name="Test Bank", website="https://test.com")
        card = CreditCard.objects.create(
            bank=bank,
            name="Multi-Benefit Card",
            annual_fee=5000,
            interest_rate_apr=18.0,
        )

        restaurant_category = BenefitCategory.objects.create(
            name="Restaurant & Dining",
            category_type="RESTAURANT",
        )
        shopping_category = BenefitCategory.objects.create(
            name="Shopping & Retail",
            category_type="SHOPPING",
        )

        return {
            "bank": bank,
            "card": card,
            "restaurant": restaurant_category,
            "shopping": shopping_category,
        }

    def test_many_to_many_relationship(self, setup_data):
        """Test many-to-many relationship between cards and categories."""
        card = setup_data["card"]
        restaurant = setup_data["restaurant"]
        shopping = setup_data["shopping"]

        # Create benefit relationships
        CreditCardBenefit.objects.create(
            credit_card=card,
            benefit_category=restaurant,
            reward_rate=5.0,
        )
        CreditCardBenefit.objects.create(
            credit_card=card,
            benefit_category=shopping,
            reward_rate=3.0,
        )

        # Test card can access categories
        assert card.benefit_categories.count() == 2
        assert restaurant in card.benefit_categories.all()
        assert shopping in card.benefit_categories.all()

    def test_reverse_relationship(self, setup_data):
        """Test accessing cards from benefit category."""
        card = setup_data["card"]
        restaurant = setup_data["restaurant"]

        CreditCardBenefit.objects.create(
            credit_card=card,
            benefit_category=restaurant,
            reward_rate=5.0,
        )

        # Test category can access cards
        assert restaurant.credit_cards.count() == 1
        assert card in restaurant.credit_cards.all()

    def test_cascade_delete_card(self, setup_data):
        """Test that deleting a card deletes its benefit relationships."""
        card = setup_data["card"]
        restaurant = setup_data["restaurant"]

        CreditCardBenefit.objects.create(
            credit_card=card,
            benefit_category=restaurant,
            reward_rate=5.0,
        )

        assert CreditCardBenefit.objects.count() == 1

        card.delete()

        assert CreditCardBenefit.objects.count() == 0
        assert BenefitCategory.objects.count() == 2  # Categories remain

    def test_cascade_delete_category(self, setup_data):
        """Test that deleting a category deletes benefit relationships."""
        card = setup_data["card"]
        restaurant = setup_data["restaurant"]

        CreditCardBenefit.objects.create(
            credit_card=card,
            benefit_category=restaurant,
            reward_rate=5.0,
        )

        assert CreditCardBenefit.objects.count() == 1

        restaurant.delete()

        assert CreditCardBenefit.objects.count() == 0
        assert CreditCard.objects.count() == 1  # Card remains
