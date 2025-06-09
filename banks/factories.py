import factory

from django.db.models.signals import post_save

from .models import Bank


@factory.django.mute_signals(post_save)
class BankFactory(factory.django.DjangoModelFactory):
    """Factory for creating Bank instances."""

    name = factory.Sequence(lambda n: f"Bank {n}")
    logo = factory.Faker("image_url", width=200, height=100)
    website = factory.Faker("url")
    is_active = True

    class Meta:
        model = Bank
