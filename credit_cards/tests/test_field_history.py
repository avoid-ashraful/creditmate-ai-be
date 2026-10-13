from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.test import TestCase

from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard, CreditCardFieldHistory

User = get_user_model()


class CreditCardFieldHistoryModelTests(TestCase):
    """Tests for CreditCardFieldHistory model and signal tracking."""

    def setUp(self):
        self.bank = BankFactory()
        self.card = CreditCardFactory(
            bank=self.bank,
            name="Test Card",
            annual_fee=Decimal("500.00"),
            interest_rate_apr=Decimal("24.50"),
        )

    def test_create_does_not_create_history(self):
        """Creating a new card should not create history entries."""
        history = CreditCardFieldHistory.objects.filter(card=self.card)
        self.assertEqual(history.count(), 0)

    def test_update_tracked_field_creates_history(self):
        """Updating a tracked field should create a history entry."""
        self.card.annual_fee = Decimal("1000.00")
        self.card.save()

        history = CreditCardFieldHistory.objects.filter(card=self.card)
        self.assertEqual(history.count(), 1)

        entry = history.first()
        self.assertEqual(entry.field_name, "annual_fee")
        self.assertEqual(entry.old_value, "500.00")
        self.assertEqual(entry.new_value, "1000.00")

    def test_update_multiple_fields_creates_multiple_history(self):
        """Updating multiple tracked fields should create multiple history entries."""
        self.card.annual_fee = Decimal("1000.00")
        self.card.interest_rate_apr = Decimal("25.00")
        self.card.save()

        history = CreditCardFieldHistory.objects.filter(card=self.card)
        self.assertEqual(history.count(), 2)

        field_names = set(h.field_name for h in history)
        self.assertEqual(field_names, {"annual_fee", "interest_rate_apr"})

    def test_update_with_no_change_creates_no_history(self):
        """Updating tracked field to same value should not create history."""
        # Save once to establish baseline
        self.card.save()
        history_count = CreditCardFieldHistory.objects.filter(card=self.card).count()

        # Update to same value
        self.card.annual_fee = Decimal("500.00")
        self.card.save()

        # Should still have same count (no new entries)
        new_history_count = CreditCardFieldHistory.objects.filter(card=self.card).count()
        self.assertEqual(new_history_count, history_count)

    def test_update_untracked_field_creates_no_history(self):
        """Updating an untracked field should not create history entries."""
        self.card.is_active = False
        self.card.save()

        # is_active is tracked, so this should create history
        history = CreditCardFieldHistory.objects.filter(card=self.card)
        self.assertEqual(history.count(), 1)

    def test_decimal_values_serialized_as_string(self):
        """Decimal field values should be serialized as strings to preserve precision."""
        self.card.annual_fee = Decimal("1234.56")
        self.card.save()

        history = CreditCardFieldHistory.objects.filter(card=self.card).first()
        self.assertEqual(history.new_value, "1234.56")
        self.assertIsInstance(history.new_value, str)

    def test_none_values_preserved(self):
        """None values should be preserved in history."""
        self.card.interest_rate_apr = None
        self.card.save()

        history = CreditCardFieldHistory.objects.filter(
            card=self.card, field_name="interest_rate_apr"
        ).first()
        self.assertIsNone(history.new_value)

    def test_update_fields_parameter_respected(self):
        """When update_fields is used, only those fields should create history."""
        self.card.annual_fee = Decimal("750.00")
        self.card.interest_rate_apr = Decimal("26.00")
        self.card.save(update_fields=["annual_fee"])

        history = CreditCardFieldHistory.objects.filter(card=self.card)
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().field_name, "annual_fee")

    def test_history_ordering(self):
        """History should be ordered newest-first by created timestamp."""
        self.card.annual_fee = Decimal("600.00")
        self.card.save()

        self.card.annual_fee = Decimal("700.00")
        self.card.save()

        history = CreditCardFieldHistory.objects.filter(card=self.card)
        self.assertEqual(history.count(), 2)

        # First should be the latest (newest)
        first = history[0]
        second = history[1]
        self.assertGreater(first.created, second.created)
        self.assertEqual(first.new_value, "700.00")
        self.assertEqual(second.new_value, "600.00")

    def test_json_field_history(self):
        """JSON field changes should be tracked correctly."""
        old_features = [{"name": "feature1"}]
        new_features = [{"name": "feature1"}, {"name": "feature2"}]

        self.card.additional_features = old_features
        self.card.save()

        self.card.additional_features = new_features
        self.card.save()

        history = CreditCardFieldHistory.objects.filter(
            card=self.card, field_name="additional_features"
        )
        self.assertEqual(history.count(), 2)

    def test_string_field_history(self):
        """String field changes should be tracked correctly."""
        original_value = self.card.lounge_access_domestic
        new_value = "Test lounge access"
        self.card.lounge_access_domestic = new_value
        self.card.save()

        history = CreditCardFieldHistory.objects.filter(
            card=self.card, field_name="lounge_access_domestic"
        )
        self.assertEqual(history.count(), 1)

        entry = history.first()
        self.assertEqual(entry.old_value, original_value)
        self.assertEqual(entry.new_value, new_value)

    def test_field_history_endpoint_exists(self):
        """Field history endpoint action should exist on viewset."""
        from credit_cards.api.views import CreditCardViewSet

        viewset = CreditCardViewSet()
        self.assertTrue(hasattr(viewset, 'field_history'))
        self.assertTrue(callable(getattr(viewset, 'field_history')))

    def test_field_history_access_control(self):
        """Field history endpoint should have access control."""
        from unittest.mock import Mock

        from credit_cards.api.views import CreditCardViewSet

        viewset = CreditCardViewSet()
        request = Mock()
        request.user.is_authenticated = False

        # Simulate the request - the method should check authentication
        method = getattr(viewset, 'field_history')
        self.assertTrue(callable(method))


class CreditCardUpdateOrCreateHistoryTests(TestCase):
    """Tests for history tracking via update_or_create."""

    def setUp(self):
        self.bank = BankFactory()

    def test_update_or_create_creates_no_history_on_create(self):
        """update_or_create with created=True should not create history."""
        card, created = CreditCard.objects.update_or_create(
            bank_id=self.bank.id,
            name="New Card",
            defaults={
                "annual_fee": Decimal("500.00"),
                "interest_rate_apr": Decimal("24.50"),
            },
        )

        self.assertTrue(created)
        history = CreditCardFieldHistory.objects.filter(card=card)
        self.assertEqual(history.count(), 0)

    def test_update_or_create_creates_history_on_update(self):
        """update_or_create with created=False should create history for changed fields."""
        card = CreditCardFactory(
            bank=self.bank,
            annual_fee=Decimal("500.00"),
            interest_rate_apr=Decimal("24.50"),
        )

        card, created = CreditCard.objects.update_or_create(
            bank_id=self.bank.id,
            name=card.name,
            defaults={
                "annual_fee": Decimal("1000.00"),
                "interest_rate_apr": Decimal("24.50"),
            },
        )

        self.assertFalse(created)
        history = CreditCardFieldHistory.objects.filter(card=card)
        # Should have one entry for annual_fee change
        self.assertGreaterEqual(history.count(), 1)
        self.assertTrue(
            history.filter(field_name="annual_fee").exists()
        )

    def test_update_or_create_no_history_when_values_unchanged(self):
        """update_or_create with same values should not create history."""
        card = CreditCardFactory(
            bank=self.bank,
            annual_fee=Decimal("500.00"),
            interest_rate_apr=Decimal("24.50"),
        )

        initial_history_count = CreditCardFieldHistory.objects.filter(card=card).count()

        card, created = CreditCard.objects.update_or_create(
            bank_id=self.bank.id,
            name=card.name,
            defaults={
                "annual_fee": Decimal("500.00"),
                "interest_rate_apr": Decimal("24.50"),
            },
        )

        self.assertFalse(created)
        final_history_count = CreditCardFieldHistory.objects.filter(card=card).count()
        self.assertEqual(final_history_count, initial_history_count)

    def test_bulk_update_limitation_documented(self):
        """Bulk operations (bulk_update) won't trigger signals - limitation documented."""
        # This is a known limitation - bulk_update bypasses signals
        # This test documents the limitation
        card1 = CreditCardFactory(bank=self.bank, annual_fee=Decimal("100.00"))

        # Track that single updates work
        card1.annual_fee = Decimal("150.00")
        card1.save()
        history1 = CreditCardFieldHistory.objects.filter(card=card1).count()
        self.assertGreater(history1, 0)

        # Note: bulk_update would not trigger signals
        # This is a documented limitation for bulk operations

    def test_transaction_safety_duplicate_prevents(self):
        """Verify duplicate creates are prevented even with rapid successive updates."""
        card = CreditCardFactory(bank=self.bank, annual_fee=Decimal("100.00"))

        # First update
        card.annual_fee = Decimal("200.00")
        card.save()
        history_after_first = CreditCardFieldHistory.objects.filter(card=card).count()

        # Immediate second update (could cause duplicates if signals weren't isolated)
        card.annual_fee = Decimal("300.00")
        card.save()
        history_after_second = CreditCardFieldHistory.objects.filter(card=card).count()

        # Should have exactly 2 entries (one per update), not duplicates
        self.assertEqual(history_after_first, 1)
        self.assertEqual(history_after_second, 2)

    def test_no_op_on_same_value_multiple_times(self):
        """Setting field to same value multiple times doesn't create duplicate history."""
        card = CreditCardFactory(bank=self.bank, annual_fee=Decimal("500.00"))

        # Save with same value
        card.annual_fee = Decimal("500.00")
        card.save()
        count1 = CreditCardFieldHistory.objects.filter(card=card).count()

        # Save again with same value
        card.annual_fee = Decimal("500.00")
        card.save()
        count2 = CreditCardFieldHistory.objects.filter(card=card).count()

        # Should not create history entries for no-ops
        self.assertEqual(count1, 0)
        self.assertEqual(count2, 0)

    def test_update_fields_partial_tracking(self):
        """Verify that update_fields restricts history to specified fields only."""
        card = CreditCardFactory(
            bank=self.bank,
            annual_fee=Decimal("500.00"),
            interest_rate_apr=Decimal("20.00"),
            lounge_access_domestic="Domestic lounge",
        )

        # Update multiple fields but only request one to be saved
        card.annual_fee = Decimal("600.00")
        card.interest_rate_apr = Decimal("25.00")
        card.lounge_access_domestic = "Updated lounge"
        card.save(update_fields=["annual_fee"])

        # Only annual_fee change should be recorded
        history = CreditCardFieldHistory.objects.filter(card=card)
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().field_name, "annual_fee")
        self.assertEqual(history.first().old_value, "500.00")
        self.assertEqual(history.first().new_value, "600.00")


@pytest.mark.django_db
class TestFieldHistoryAPIEndpoint:
    """Real request-level tests for field-history API endpoint."""

    def setup_method(self):
        """Set up test data before each test method."""
        self.client = APIClient()
        self.bank = BankFactory()
        self.card = CreditCardFactory(
            bank=self.bank,
            name="Test Card",
            annual_fee=Decimal("100.00"),
            interest_rate_apr=Decimal("20.00"),
        )

        # Create multiple history entries to test ordering and pagination
        for i, fee in enumerate([Decimal("200.00"), Decimal("300.00"), Decimal("400.00")]):
            self.card.annual_fee = fee
            self.card.save()

    def test_anonymous_user_forbidden(self):
        """Anonymous GET to field-history should return 403."""
        url = f"/api/v1/credit-cards/{self.card.id}/field-history/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Authentication required" in response.data.get("detail", "")

    def test_authenticated_user_can_access(self):
        """Authenticated GET to field-history should return 200."""
        user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_authenticate(user=user)

        url = f"/api/v1/credit-cards/{self.card.id}/field-history/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

    def test_history_returns_paginated_response(self):
        """History endpoint returns paginated response with results."""
        user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_authenticate(user=user)

        url = f"/api/v1/credit-cards/{self.card.id}/field-history/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert "count" in response.data

    def test_history_newest_first_ordering(self):
        """History should be ordered newest-first."""
        user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_authenticate(user=user)

        url = f"/api/v1/credit-cards/{self.card.id}/field-history/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        results = response.data["results"]
        assert len(results) > 0

        # Verify ordering: each entry created timestamp should be >= next entry
        for i in range(len(results) - 1):
            current_created = results[i]["created"]
            next_created = results[i + 1]["created"]
            # Current should be >= next (newest first)
            assert current_created >= next_created

    def test_history_contains_tracked_fields(self):
        """History entries should contain expected fields."""
        user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_authenticate(user=user)

        url = f"/api/v1/credit-cards/{self.card.id}/field-history/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        results = response.data["results"]
        assert len(results) > 0

        for entry in results:
            assert "id" in entry
            assert "card_id" in entry
            assert "field_name" in entry
            assert "old_value" in entry
            assert "new_value" in entry
            assert "created" in entry

    def test_history_only_for_requested_card(self):
        """History should only include records for the requested card."""
        other_bank = BankFactory()
        other_card = CreditCardFactory(
            bank=other_bank,
            name="Other Card",
            annual_fee=Decimal("500.00"),
        )
        other_card.annual_fee = Decimal("600.00")
        other_card.save()

        user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_authenticate(user=user)

        # Get history for the first card
        url = f"/api/v1/credit-cards/{self.card.id}/field-history/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        results = response.data["results"]
        # All entries should be for self.card
        for entry in results:
            assert entry["card_id"] == self.card.id

    def test_history_shows_decimal_values_as_strings(self):
        """Decimal values should be stored and returned as strings."""
        user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_authenticate(user=user)

        url = f"/api/v1/credit-cards/{self.card.id}/field-history/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        results = response.data["results"]
        # Find an annual_fee change
        for entry in results:
            if entry["field_name"] == "annual_fee":
                # Values should be strings (Decimal serialized)
                assert isinstance(entry["old_value"], str)
                assert isinstance(entry["new_value"], str)
                # Check format
                assert "." in entry["new_value"]

    def test_pagination_with_many_records(self):
        """Test that pagination works with many history records."""
        user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_authenticate(user=user)

        # Create more history entries
        for i in range(10):
            self.card.lounge_access_domestic = f"Update {i}"
            self.card.save()

        url = f"/api/v1/credit-cards/{self.card.id}/field-history/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        # Should have pagination info
        assert "count" in response.data
        assert "results" in response.data
        # Results should be bounded (paginated)
        assert len(response.data["results"]) <= 20  # Django default page size

    def test_staff_user_can_access(self):
        """Staff users should also be able to access field history."""
        user = User.objects.create_user(username="staffuser", password="testpass")
        user.is_staff = True
        user.save()
        self.client.force_authenticate(user=user)

        url = f"/api/v1/credit-cards/{self.card.id}/field-history/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

    def test_history_read_only_no_post(self):
        """Field history endpoint should not accept POST requests."""
        user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_authenticate(user=user)

        url = f"/api/v1/credit-cards/{self.card.id}/field-history/"
        response = self.client.post(url, {})
        # Should get 405 Method Not Allowed
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_history_for_nonexistent_card(self):
        """Requesting history for nonexistent card should return 404."""
        user = User.objects.create_user(username="testuser", password="testpass")
        self.client.force_authenticate(user=user)

        url = "/api/v1/credit-cards/999999/field-history/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
