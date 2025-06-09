import pytest

from django.core.exceptions import ValidationError
from django.db import IntegrityError

from banks.factories import BankFactory
from banks.models import Bank
from credit_cards.factories import CreditCardFactory


@pytest.mark.django_db
class TestBankModel:
    """Test Bank model functionality."""

    def test_bank_creation(self):
        """Test that a bank can be created successfully."""
        bank = BankFactory()
        assert bank.id is not None
        assert bank.name
        assert bank.is_active is True
        assert bank.created is not None
        assert bank.modified is not None

    def test_bank_str_representation(self):
        """Test string representation of Bank."""
        bank = BankFactory(name="Test Bank")
        assert str(bank) == "Test Bank"

    def test_bank_name_uniqueness(self):
        """Test that bank names must be unique."""
        BankFactory(name="Unique Bank")

        with pytest.raises(IntegrityError):
            BankFactory(name="Unique Bank")

    def test_bank_url_validation(self):
        """Test URL field validation."""
        bank = Bank(name="Test Bank", logo="invalid-url", website="invalid-website")

        with pytest.raises(ValidationError):
            bank.full_clean()

    def test_bank_valid_urls(self):
        """Test that valid URLs are accepted."""
        bank = Bank(
            name="Test Bank",
            logo="https://example.com/logo.png",
            website="https://example.com",
        )
        bank.full_clean()  # Should not raise

    def test_bank_credit_card_count_property(self):
        """Test credit_card_count property."""
        bank = BankFactory()

        # Initially no credit cards
        assert bank.credit_card_count == 0

        # Add active credit cards
        CreditCardFactory.create_batch(3, bank=bank, is_active=True)
        assert bank.credit_card_count == 3

        # Add inactive credit card - should not be counted
        CreditCardFactory(bank=bank, is_active=False)
        assert bank.credit_card_count == 3

    def test_bank_ordering(self):
        """Test that banks are ordered by name."""
        bank_c = BankFactory(name="C Bank")
        bank_a = BankFactory(name="A Bank")
        bank_b = BankFactory(name="B Bank")

        banks = Bank.objects.all()
        assert list(banks) == [bank_a, bank_b, bank_c]

    def test_bank_defaults(self):
        """Test default values for bank fields."""
        bank = Bank.objects.create(name="Test Bank")

        assert bank.logo == ""
        assert bank.website == ""
        assert bank.is_active is True

    def test_bank_blank_fields(self):
        """Test that blank fields are allowed."""
        bank = Bank(name="Test Bank", logo="", website="")
        bank.full_clean()  # Should not raise
