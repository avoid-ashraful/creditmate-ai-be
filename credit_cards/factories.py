from decimal import Decimal

import factory

from django.db.models.signals import post_save

from banks.factories import BankFactory

from .models import CreditCard


@factory.django.mute_signals(post_save)
class CreditCardFactory(factory.django.DjangoModelFactory):
    """Factory for creating CreditCard instances."""

    bank = factory.SubFactory(BankFactory)
    name = factory.Sequence(lambda n: f"Card {n}")
    annual_fee = factory.Faker(
        "pydecimal",
        left_digits=4,
        right_digits=2,
        positive=True,
        min_value=Decimal("1"),
        max_value=Decimal("5000"),
    )
    interest_rate_apr = factory.Faker(
        "pydecimal",
        left_digits=2,
        right_digits=2,
        positive=True,
        min_value=Decimal("15"),
        max_value=Decimal("45"),
    )
    lounge_access_international = factory.Faker("random_int", min=0, max=10)
    lounge_access_domestic = factory.Faker("random_int", min=0, max=15)
    cash_advance_fee = factory.Faker("sentence", nb_words=6)
    late_payment_fee = factory.Faker("sentence", nb_words=6)
    annual_fee_waiver_policy = factory.Dict(
        {
            "minimum_spend": factory.Faker("random_int", min=50000, max=500000),
            "waiver_period": factory.Faker(
                "random_element", elements=["first_year", "lifetime", "annual"]
            ),
            "conditions": factory.List(
                [
                    factory.Faker("sentence", nb_words=4),
                    factory.Faker("sentence", nb_words=6),
                ]
            ),
        }
    )
    reward_points_policy = factory.Faker("text", max_nb_chars=500)
    additional_features = factory.List(
        [factory.Faker("word"), factory.Faker("word"), factory.Faker("word")]
    )
    is_active = True

    class Meta:
        model = CreditCard


class PremiumCreditCardFactory(CreditCardFactory):
    """Factory for premium credit cards with higher benefits."""

    annual_fee = factory.Faker(
        "pydecimal",
        left_digits=4,
        right_digits=2,
        positive=True,
        min_value=Decimal("2000"),
        max_value=Decimal("10000"),
    )
    lounge_access_international = factory.Faker("random_int", min=5, max=20)
    lounge_access_domestic = factory.Faker("random_int", min=10, max=30)


class NormalCreditCardFactory(CreditCardFactory):
    """Factory for normal credit cards with standard benefits."""

    annual_fee = factory.Faker(
        "pydecimal",
        left_digits=3,
        right_digits=2,
        min_value=Decimal("0"),
        max_value=Decimal("1000"),
    )
    lounge_access_international = factory.Faker("random_int", min=0, max=3)
    lounge_access_domestic = factory.Faker("random_int", min=0, max=5)
