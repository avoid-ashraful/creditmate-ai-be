import uuid

import factory

from django.db.models.signals import post_save
from django.utils import timezone

from banks.enums import ContentType, ProcessingStatus
from banks.models import Bank, BankDataSource, CrawledContent


@factory.django.mute_signals(post_save)
class BankFactory(factory.django.DjangoModelFactory):
    """Factory for creating Bank instances."""

    name = factory.LazyAttribute(lambda _: f"Bank {uuid.uuid4().hex[:8]}")
    logo = factory.Faker("image_url", width=200, height=100)
    website = factory.Faker("url")
    is_active = True

    class Meta:
        model = Bank


@factory.django.mute_signals(post_save)
class BankDataSourceFactory(factory.django.DjangoModelFactory):
    """Factory for creating BankDataSource instances."""

    bank = factory.SubFactory(BankFactory)
    url = factory.Faker("url")
    content_type = factory.Iterator(
        [
            ContentType.PDF,
            ContentType.WEBPAGE,
            ContentType.IMAGE,
            ContentType.CSV,
        ]
    )
    description = factory.Faker("sentence", nb_words=6)
    failed_attempt_count = 0
    is_active = True
    last_crawled_at = None
    last_successful_crawl_at = None

    class Meta:
        model = BankDataSource

    @factory.post_generation
    def with_crawl_history(self, create, extracted, **kwargs):
        """Add crawl history timestamps if requested."""
        if not create or not extracted:
            return

        self.last_crawled_at = timezone.now()
        if extracted.get("successful", True):
            self.last_successful_crawl_at = timezone.now()
        self.save()


@factory.django.mute_signals(post_save)
class CrawledContentFactory(factory.django.DjangoModelFactory):
    """Factory for creating CrawledContent instances."""

    data_source = factory.SubFactory(BankDataSourceFactory)
    credit_card = None  # Optional FK to CreditCard
    raw_content = factory.Faker("text", max_nb_chars=1000)
    extracted_content = factory.Faker("text", max_nb_chars=500)
    parsed_json = factory.LazyFunction(
        lambda: {
            "credit_cards": [
                {
                    "name": "Test Card",
                    "annual_fee": 95,
                    "interest_rate_apr": 18.99,
                    "lounge_access_international": 2,
                    "lounge_access_domestic": 4,
                    "cash_advance_fee": "3% of amount",
                    "late_payment_fee": "$35",
                    "annual_fee_waiver_policy": {"minimum_spend": 12000},
                    "reward_points_policy": "1 point per $1 spent",
                    "additional_features": ["Travel Insurance", "Concierge Service"],
                }
            ]
        }
    )
    processing_status = ProcessingStatus.COMPLETED
    error_message = ""

    class Meta:
        model = CrawledContent

    class Params:
        failed = factory.Trait(
            processing_status=ProcessingStatus.FAILED,
            error_message=factory.Faker("sentence", nb_words=8),
            parsed_json={},
        )
        pending = factory.Trait(
            processing_status=ProcessingStatus.PENDING, parsed_json={}
        )
        processing = factory.Trait(
            processing_status=ProcessingStatus.PROCESSING, parsed_json={}
        )
