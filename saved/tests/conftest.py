import pytest
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

from credit_cards.factories import CreditCardFactory


@pytest.fixture()
def owner(db):
    """User who owns the saved objects under test."""
    return get_user_model().objects.create_user(
        username="saved-owner",
        email="owner@example.com",
        password="not-used-in-tests",
    )


@pytest.fixture()
def other_user(db):
    """A second user, used to check ownership boundaries."""
    return get_user_model().objects.create_user(
        username="saved-other",
        email="other@example.com",
        password="not-used-in-tests",
    )


@pytest.fixture()
def owner_client(owner):
    """APIClient authenticated as the owner."""
    client = APIClient()
    client.force_authenticate(user=owner)
    return client


@pytest.fixture()
def other_client(other_user):
    """APIClient authenticated as the non-owning user."""
    client = APIClient()
    client.force_authenticate(user=other_user)
    return client


@pytest.fixture()
def anonymous_client():
    """Unauthenticated APIClient."""
    return APIClient()


@pytest.fixture()
def cards(db):
    """Five distinct credit cards."""
    return CreditCardFactory.create_batch(5)
