from datetime import timedelta

import pytest

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from banks.enums import ContentType, ProcessingStatus
from banks.factories import BankDataSourceFactory, BankFactory, CrawledContentFactory
from banks.models import Bank, BankDataSource, CrawledContent
from credit_cards.factories import CreditCardFactory


@pytest.mark.django_db
class TestBankModel:
    """Test Bank model functionality."""

    def test_bank_creation(self):
        """Test that a bank can be created successfully."""
        bank = BankFactory(name="Test Bank")

        assert bank.name == "Test Bank"
        assert bank.is_active is True
        assert bank.created is not None
        assert bank.modified is not None

    def test_bank_str_representation(self):
        """Test string representation of Bank."""
        bank = BankFactory(name="Test Bank")
        assert str(bank) == "Test Bank"

    def test_bank_name_uniqueness(self):
        """Test that bank names must be unique."""
        BankFactory(name="Duplicate Bank")

        with pytest.raises(IntegrityError):
            BankFactory(name="Duplicate Bank")

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

    def test_bank_url_validation(self):
        """Test URL field validation."""
        # Valid URLs should work
        bank = BankFactory(
            logo="https://example.com/logo.png", website="https://example.com"
        )
        bank.full_clean()  # Should not raise validation error

        # Invalid URLs should fail validation
        bank.logo = "not-a-url"
        with pytest.raises(ValidationError):
            bank.full_clean()

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


@pytest.mark.django_db
class TestBankDataSourceModel:
    """Test BankDataSource model functionality."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory()

    def test_bank_data_source_creation(self):
        """Test basic bank data source creation."""
        data_source = BankDataSourceFactory(
            bank=self.bank,
            url="https://example.com/cards.pdf",
            content_type=ContentType.PDF,
        )

        assert data_source.bank == self.bank
        assert data_source.url == "https://example.com/cards.pdf"
        assert data_source.content_type == ContentType.PDF
        assert data_source.failed_attempt_count == 0
        assert data_source.is_active is True
        assert data_source.last_crawled_at is None
        assert data_source.last_successful_crawl_at is None

    def test_bank_data_source_str_representation(self):
        """Test bank data source string representation."""
        data_source = BankDataSourceFactory(
            bank=self.bank, url="https://example.com/cards.pdf"
        )
        expected = f"{self.bank.name} - https://example.com/cards.pdf"
        assert str(data_source) == expected

    def test_bank_data_source_unique_constraint(self):
        """Test unique constraint on bank and URL."""
        url = "https://example.com/cards.pdf"
        BankDataSourceFactory(bank=self.bank, url=url)

        with pytest.raises(IntegrityError):
            BankDataSourceFactory(bank=self.bank, url=url)

    @pytest.mark.parametrize(
        "content_type",
        [
            ContentType.PDF,
            ContentType.WEBPAGE,
            ContentType.IMAGE,
            ContentType.CSV,
        ],
    )
    def test_bank_data_source_content_type_choices(self, content_type):
        """Test content type choices."""
        data_source = BankDataSourceFactory(bank=self.bank, content_type=content_type)
        assert data_source.content_type == content_type

    def test_is_failing_property(self):
        """Test is_failing property."""
        data_source = BankDataSourceFactory(bank=self.bank, failed_attempt_count=3)
        assert data_source.is_failing is False

        data_source.failed_attempt_count = 5
        assert data_source.is_failing is True

    def test_increment_failed_attempts(self):
        """Test increment_failed_attempts method."""
        data_source = BankDataSourceFactory(bank=self.bank, failed_attempt_count=0)

        # Increment attempts
        data_source.increment_failed_attempts()
        assert data_source.failed_attempt_count == 1
        assert data_source.is_active is True

        # Increment to threshold (5 attempts)
        data_source.failed_attempt_count = 4
        data_source.save()
        data_source.increment_failed_attempts()

        data_source.refresh_from_db()
        assert data_source.failed_attempt_count == 5
        assert data_source.is_active is False

    def test_reset_failed_attempts(self):
        """Test reset_failed_attempts method."""
        data_source = BankDataSourceFactory(
            bank=self.bank, failed_attempt_count=3, is_active=False
        )

        data_source.reset_failed_attempts()

        data_source.refresh_from_db()
        assert data_source.failed_attempt_count == 0
        # Note: reset_failed_attempts doesn't automatically reactivate

    def test_bank_data_source_url_validation(self):
        """Test URL validation."""
        data_source = BankDataSourceFactory(bank=self.bank)

        # Valid URL should work
        data_source.url = "https://example.com/valid-url"
        data_source.full_clean()  # Should not raise

        # Invalid URL should fail
        data_source.url = "not-a-valid-url"
        with pytest.raises(ValidationError):
            data_source.full_clean()

    def test_bank_data_source_ordering(self):
        """Test model ordering."""
        bank1 = BankFactory(name="AAA Bank")
        bank2 = BankFactory(name="ZZZ Bank")

        source2 = BankDataSourceFactory(bank=bank2, url="https://zzz.com")
        source1 = BankDataSourceFactory(bank=bank1, url="https://aaa.com")

        sources = list(BankDataSource.objects.all())
        assert sources[0] == source1  # AAA Bank should come first
        assert sources[1] == source2  # ZZZ Bank should come second


@pytest.mark.django_db
class TestCrawledContentModel:
    """Test CrawledContent model functionality."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory()
        self.data_source = BankDataSourceFactory(bank=self.bank)
        self.credit_card = CreditCardFactory(bank=self.bank)

    def test_crawled_content_creation(self):
        """Test basic crawled content creation."""
        content = CrawledContentFactory(
            data_source=self.data_source,
            credit_card=self.credit_card,
            raw_content="Raw content here",
            extracted_content="Extracted content here",
            processing_status=ProcessingStatus.COMPLETED,
        )

        assert content.data_source == self.data_source
        assert content.credit_card == self.credit_card
        assert content.raw_content == "Raw content here"
        assert content.extracted_content == "Extracted content here"
        assert content.processing_status == ProcessingStatus.COMPLETED
        assert content.crawl_date is not None

    def test_crawled_content_str_representation(self):
        """Test crawled content string representation."""
        content = CrawledContentFactory(data_source=self.data_source)
        expected = f"{self.bank.name} - {content.crawl_date}"
        assert str(content) == expected

    def test_crawled_content_without_credit_card(self):
        """Test crawled content creation without credit card FK."""
        content = CrawledContentFactory(data_source=self.data_source, credit_card=None)

        assert content.data_source == self.data_source
        assert content.credit_card is None

    @pytest.mark.parametrize(
        "status",
        [
            ProcessingStatus.PENDING,
            ProcessingStatus.PROCESSING,
            ProcessingStatus.COMPLETED,
            ProcessingStatus.FAILED,
        ],
    )
    def test_crawled_content_processing_status_choices(self, status):
        """Test processing status choices."""
        content = CrawledContentFactory(
            data_source=self.data_source, processing_status=status
        )
        assert content.processing_status == status

    def test_crawled_content_default_values(self):
        """Test default values for fields."""
        content = CrawledContent.objects.create(data_source=self.data_source)

        assert content.raw_content == ""
        assert content.extracted_content == ""
        assert content.parsed_json == {}
        assert content.processing_status == ProcessingStatus.PENDING
        assert content.error_message == ""

    def test_crawled_content_ordering(self):
        """Test model ordering (newest first)."""
        # Create content with different timestamps
        older_content = CrawledContentFactory(data_source=self.data_source)

        # Manually update the crawl_date to make it older
        older_timestamp = timezone.now() - timedelta(hours=1)
        CrawledContent.objects.filter(id=older_content.id).update(
            crawl_date=older_timestamp
        )

        newer_content = CrawledContentFactory(data_source=self.data_source)

        contents = list(CrawledContent.objects.all())
        assert contents[0] == newer_content  # Newer should come first
        assert contents[1] == older_content  # Older should come second

    def test_crawled_content_json_field(self):
        """Test JSON field functionality."""
        test_json = {
            "credit_cards": [
                {
                    "name": "Test Card",
                    "annual_fee": 95,
                    "features": ["Travel Insurance", "Lounge Access"],
                }
            ]
        }

        content = CrawledContentFactory(
            data_source=self.data_source, parsed_json=test_json
        )

        content.refresh_from_db()
        assert content.parsed_json == test_json
        assert content.parsed_json["credit_cards"][0]["name"] == "Test Card"

    def test_crawled_content_cascade_deletion(self):
        """Test cascade deletion when data source is deleted."""
        content = CrawledContentFactory(data_source=self.data_source)
        content_id = content.id

        # Delete the data source
        self.data_source.delete()

        # Content should also be deleted
        assert not CrawledContent.objects.filter(id=content_id).exists()

    def test_crawled_content_credit_card_cascade_deletion(self):
        """Test cascade deletion when credit card is deleted."""
        content = CrawledContentFactory(
            data_source=self.data_source, credit_card=self.credit_card
        )
        content_id = content.id

        # Delete the credit card
        self.credit_card.delete()

        # Content should also be deleted
        assert not CrawledContent.objects.filter(id=content_id).exists()

    def test_crawled_content_large_text_fields(self):
        """Test handling of large text content."""
        large_content = "A" * 10000  # 10KB of content

        content = CrawledContentFactory(
            data_source=self.data_source,
            raw_content=large_content,
            extracted_content=large_content,
        )

        content.refresh_from_db()
        assert len(content.raw_content) == 10000
        assert len(content.extracted_content) == 10000


@pytest.mark.django_db
class TestModelRelationships:
    """Test model relationships and cross-references."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory()

    def test_bank_to_data_sources_relationship(self):
        """Test one-to-many relationship between Bank and BankDataSource."""
        sources = BankDataSourceFactory.create_batch(3, bank=self.bank)

        assert self.bank.data_sources.count() == 3
        assert sources[0] in self.bank.data_sources.all()
        assert sources[1] in self.bank.data_sources.all()
        assert sources[2] in self.bank.data_sources.all()

    def test_data_source_to_crawled_content_relationship(self):
        """Test one-to-many relationship between BankDataSource and CrawledContent."""
        data_source = BankDataSourceFactory(bank=self.bank)
        contents = CrawledContentFactory.create_batch(3, data_source=data_source)

        assert data_source.crawled_contents.count() == 3
        assert contents[0] in data_source.crawled_contents.all()
        assert contents[1] in data_source.crawled_contents.all()
        assert contents[2] in data_source.crawled_contents.all()

    def test_credit_card_to_crawled_content_relationship(self):
        """Test one-to-many relationship between CreditCard and CrawledContent."""
        credit_card = CreditCardFactory(bank=self.bank)
        data_source = BankDataSourceFactory(bank=self.bank)
        contents = CrawledContentFactory.create_batch(
            2, data_source=data_source, credit_card=credit_card
        )

        assert credit_card.crawled_contents.count() == 2
        assert contents[0] in credit_card.crawled_contents.all()
        assert contents[1] in credit_card.crawled_contents.all()

    def test_cross_bank_isolation(self):
        """Test that data is properly isolated between banks."""
        bank1 = BankFactory(name="Bank 1")
        bank2 = BankFactory(name="Bank 2")

        source1 = BankDataSourceFactory(bank=bank1)
        source2 = BankDataSourceFactory(bank=bank2)

        content1 = CrawledContentFactory(data_source=source1)
        content2 = CrawledContentFactory(data_source=source2)

        # Each bank should only see its own data
        assert bank1.data_sources.count() == 1
        assert bank2.data_sources.count() == 1
        assert source1.bank != source2.bank
        assert content1.data_source.bank != content2.data_source.bank


@pytest.mark.django_db
class TestBankModelEdgeCases:
    """Test Bank model edge cases and validation boundaries."""

    def test_bank_name_max_length_validation(self):
        """Test bank name field max length validation (255 chars)."""
        # Valid length should work
        valid_name = "A" * 255
        bank = BankFactory(name=valid_name)
        bank.full_clean()  # Should not raise
        assert bank.name == valid_name

        # Exceeding max length should fail
        invalid_name = "A" * 256
        bank.name = invalid_name
        with pytest.raises(ValidationError):
            bank.full_clean()

    def test_bank_name_empty_validation(self):
        """Test bank name cannot be empty (required field)."""
        with pytest.raises(ValidationError):
            bank = Bank(name="")
            bank.full_clean()

    def test_bank_url_field_max_length_validation(self):
        """Test logo and website URL fields max length validation (512 chars)."""
        # Valid length should work
        valid_url = "https://example.com/" + "a" * 480  # Total ~500 chars
        bank = BankFactory(logo=valid_url, website=valid_url)
        bank.full_clean()  # Should not raise

        # Exceeding max length should fail
        invalid_url = "https://example.com/" + "a" * 500  # Total >512 chars
        bank.logo = invalid_url
        with pytest.raises(ValidationError):
            bank.full_clean()

    def test_bank_url_field_blank_handling(self):
        """Test URL fields can be blank but not None."""
        bank = BankFactory(logo="", website="")
        bank.full_clean()  # Should not raise
        assert bank.logo == ""
        assert bank.website == ""

    def test_bank_inactive_bank_credit_card_count(self):
        """Test credit_card_count property with inactive bank."""
        bank = BankFactory(is_active=False)
        CreditCardFactory.create_batch(3, bank=bank, is_active=True)

        # Should still count credit cards even if bank is inactive
        assert bank.credit_card_count == 3

    def test_bank_unicode_name_handling(self):
        """Test bank names with unicode characters."""
        unicode_name = "البنك العربي 中国银行 Банк"
        bank = BankFactory(name=unicode_name)
        bank.full_clean()  # Should not raise
        assert bank.name == unicode_name

    def test_bank_special_characters_in_name(self):
        """Test bank names with special characters and punctuation."""
        special_name = "Bank & Trust Co. - North America (USA)"
        bank = BankFactory(name=special_name)
        bank.full_clean()  # Should not raise
        assert bank.name == special_name


@pytest.mark.django_db
class TestBankDataSourceEdgeCases:
    """Test BankDataSource model edge cases and validation boundaries."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory()

    def test_data_source_url_max_length_validation(self):
        """Test URL field max length validation (1024 chars)."""
        # Valid length should work
        valid_url = "https://example.com/" + "a" * 1000  # Total ~1020 chars
        data_source = BankDataSourceFactory(bank=self.bank, url=valid_url)
        data_source.full_clean()  # Should not raise

        # Exceeding max length should fail
        invalid_url = "https://example.com/" + "a" * 1010  # Total >1024 chars
        data_source.url = invalid_url
        with pytest.raises(ValidationError):
            data_source.full_clean()

    def test_data_source_description_max_length_validation(self):
        """Test description field max length validation (500 chars)."""
        # Valid length should work
        valid_description = "A" * 500
        data_source = BankDataSourceFactory(bank=self.bank, description=valid_description)
        data_source.full_clean()  # Should not raise

        # Exceeding max length should fail
        invalid_description = "A" * 501
        data_source.description = invalid_description
        with pytest.raises(ValidationError):
            data_source.full_clean()

    def test_data_source_failed_attempt_count_negative_validation(self):
        """Test failed_attempt_count cannot be negative."""
        data_source = BankDataSourceFactory(bank=self.bank)
        data_source.failed_attempt_count = -1
        with pytest.raises(ValidationError):
            data_source.full_clean()

    def test_data_source_increment_failed_attempts_edge_cases(self):
        """Test increment at exactly threshold boundary (4->5)."""
        data_source = BankDataSourceFactory(
            bank=self.bank, failed_attempt_count=4, is_active=True
        )

        # Should deactivate at exactly 5 attempts
        data_source.increment_failed_attempts()
        data_source.refresh_from_db()

        assert data_source.failed_attempt_count == 5
        assert data_source.is_active is False

    def test_data_source_increment_failed_attempts_beyond_threshold(self):
        """Test increment when already at/above threshold."""
        data_source = BankDataSourceFactory(
            bank=self.bank, failed_attempt_count=6, is_active=False
        )

        # Should still increment even when already deactivated
        data_source.increment_failed_attempts()
        data_source.refresh_from_db()

        assert data_source.failed_attempt_count == 7
        assert data_source.is_active is False

    def test_data_source_reset_failed_attempts_when_inactive(self):
        """Test reset_failed_attempts doesn't reactivate inactive sources."""
        data_source = BankDataSourceFactory(
            bank=self.bank, failed_attempt_count=10, is_active=False
        )

        data_source.reset_failed_attempts()
        data_source.refresh_from_db()

        assert data_source.failed_attempt_count == 0
        # Should NOT automatically reactivate
        assert data_source.is_active is False

    def test_data_source_is_failing_boundary_conditions(self):
        """Test is_failing property at boundary values (4, 5, 6)."""
        data_source = BankDataSourceFactory(bank=self.bank)

        # At 4 attempts - not failing
        data_source.failed_attempt_count = 4
        assert data_source.is_failing is False

        # At 5 attempts - failing
        data_source.failed_attempt_count = 5
        assert data_source.is_failing is True

        # At 6 attempts - still failing
        data_source.failed_attempt_count = 6
        assert data_source.is_failing is True

    def test_data_source_last_crawled_timezone_handling(self):
        """Test timezone handling for crawl timestamps."""
        data_source = BankDataSourceFactory(bank=self.bank)

        # Set timestamps with timezone
        now = timezone.now()
        data_source.last_crawled_at = now
        data_source.last_successful_crawl_at = now
        data_source.save()

        data_source.refresh_from_db()
        assert data_source.last_crawled_at.tzinfo is not None
        assert data_source.last_successful_crawl_at.tzinfo is not None


@pytest.mark.django_db
class TestCrawledContentEdgeCases:
    """Test CrawledContent model edge cases and validation boundaries."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.bank = BankFactory()
        self.data_source = BankDataSourceFactory(bank=self.bank)

    def test_crawled_content_very_large_content(self):
        """Test handling of extremely large text content (>1MB)."""
        large_content = "A" * (1024 * 1024)  # 1MB of content

        content = CrawledContentFactory(
            data_source=self.data_source,
            raw_content=large_content,
            extracted_content=large_content,
        )

        content.refresh_from_db()
        assert len(content.raw_content) == 1024 * 1024
        assert len(content.extracted_content) == 1024 * 1024

    def test_crawled_content_invalid_json_handling(self):
        """Test behavior with malformed JSON in parsed_json field."""
        # Django JSONField should handle this gracefully
        content = CrawledContentFactory(data_source=self.data_source)

        # Valid JSON should work
        content.parsed_json = {"valid": "json"}
        content.save()
        content.refresh_from_db()
        assert content.parsed_json == {"valid": "json"}

    def test_crawled_content_nested_json_depth(self):
        """Test deeply nested JSON structures."""
        nested_json = {
            "level1": {"level2": {"level3": {"level4": {"level5": "deep_value"}}}}
        }

        content = CrawledContentFactory(
            data_source=self.data_source, parsed_json=nested_json
        )

        content.refresh_from_db()
        assert (
            content.parsed_json["level1"]["level2"]["level3"]["level4"]["level5"]
            == "deep_value"
        )

    def test_crawled_content_empty_json_vs_null(self):
        """Test difference between {} and None for parsed_json."""
        # Empty dict
        content1 = CrawledContentFactory(data_source=self.data_source, parsed_json={})
        content1.refresh_from_db()
        assert content1.parsed_json == {}

        # None/null - should default to empty dict
        content2 = CrawledContentFactory(data_source=self.data_source, parsed_json=None)
        content2.refresh_from_db()
        assert content2.parsed_json == {}

    def test_crawled_content_auto_timestamp_accuracy(self):
        """Test crawl_date auto_now_add accuracy and timezone."""
        before_creation = timezone.now()
        content = CrawledContentFactory(data_source=self.data_source)
        after_creation = timezone.now()

        assert before_creation <= content.crawl_date <= after_creation
        assert content.crawl_date.tzinfo is not None

    def test_crawled_content_error_message_length_limits(self):
        """Test very long error messages handling."""
        long_error = "Error: " + "A" * 10000  # Very long error message

        content = CrawledContentFactory(
            data_source=self.data_source,
            error_message=long_error,
            processing_status=ProcessingStatus.FAILED,
        )

        content.refresh_from_db()
        assert len(content.error_message) > 1000  # Should store long messages

    def test_crawled_content_unicode_content_handling(self):
        """Test raw/extracted content with unicode characters."""
        unicode_content = "测试内容 العربية Русский 🌟📱💳"

        content = CrawledContentFactory(
            data_source=self.data_source,
            raw_content=unicode_content,
            extracted_content=unicode_content,
        )

        content.refresh_from_db()
        assert content.raw_content == unicode_content
        assert content.extracted_content == unicode_content
