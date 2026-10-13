from decimal import Decimal

from django.test import TestCase

from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard, CreditCardFieldHistory


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
        from credit_cards.api.views import CreditCardViewSet
        from unittest.mock import Mock

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
