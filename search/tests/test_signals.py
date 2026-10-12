"""Tests for the signal -> queue wiring."""

import pytest

from banks.models import Bank
from credit_cards.models import CreditCard
from search.models import SearchIndexUpdate
from search.tests.fakes import RecordingService


@pytest.mark.django_db
class TestSignalToQueue:
    """Model writes must produce outbox rows after the transaction commits."""

    def test_bank_save_queues_index_row(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = Bank.objects.create(name="Signal Bank")
        row = SearchIndexUpdate.objects.get()
        assert row.index_name == SearchIndexUpdate.INDEX_BANKS
        assert row.object_id == bank.pk
        assert row.action == SearchIndexUpdate.ACTION_INDEX

    def test_card_save_queues_index_row(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = Bank.objects.create(name="Signal Bank 2")
            card = CreditCard.objects.create(
                bank=bank, name="Signal Card", annual_fee=None
            )
        rows = list(SearchIndexUpdate.objects.order_by("id"))
        assert [(r.index_name, r.object_id) for r in rows] == [
            (SearchIndexUpdate.INDEX_BANKS, bank.pk),
            (SearchIndexUpdate.INDEX_CREDIT_CARDS, card.pk),
        ]

    def test_card_delete_queues_delete_row(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = Bank.objects.create(name="Signal Bank 3")
            card = CreditCard.objects.create(bank=bank, name="Signal Card 3")
            card_pk = card.pk
            card.delete()
        delete_rows = SearchIndexUpdate.objects.filter(
            action=SearchIndexUpdate.ACTION_DELETE, object_id=card_pk
        )
        assert delete_rows.count() == 1
        assert delete_rows.get().index_name == SearchIndexUpdate.INDEX_CREDIT_CARDS

    def test_bank_delete_cascades_delete_rows_for_cards(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = Bank.objects.create(name="Cascade Bank")
            card = CreditCard.objects.create(bank=bank, name="Cascade Card")
            bank_pk, card_pk = bank.pk, card.pk
            bank.delete()
        assert SearchIndexUpdate.objects.filter(
            object_id=bank_pk, action=SearchIndexUpdate.ACTION_DELETE
        ).exists()
        assert SearchIndexUpdate.objects.filter(
            object_id=card_pk, action=SearchIndexUpdate.ACTION_DELETE
        ).exists()

    def test_sync_mode_off_skips_queueing(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "off"
        with django_capture_on_commit_callbacks(execute=True):
            Bank.objects.create(name="Off Mode Bank")
        assert SearchIndexUpdate.objects.count() == 0


@pytest.mark.django_db
class TestSyncMode:
    """``SEARCH_SYNC_MODE=sync`` drains the queue right after the commit."""

    def test_sync_mode_drains_inline(
        self, django_capture_on_commit_callbacks, settings, monkeypatch
    ):
        settings.SEARCH_SYNC_MODE = "sync"
        recorded = {}

        def fake_dispatch():
            recorded["drained"] = True
            return {"processed": 0}

        import search.signals as signals_module

        monkeypatch.setattr(signals_module, "dispatch", fake_dispatch)
        with django_capture_on_commit_callbacks(execute=True):
            Bank.objects.create(name="Inline Sync Bank")
        assert recorded.get("drained") is True

    def test_queue_mode_does_not_drain_inline(
        self, django_capture_on_commit_callbacks, settings, monkeypatch
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        recorded = {}

        def fake_dispatch():
            recorded["drained"] = True

        import search.signals as signals_module

        monkeypatch.setattr(signals_module, "dispatch", fake_dispatch)
        with django_capture_on_commit_callbacks(execute=True):
            Bank.objects.create(name="Queued Bank")
        assert "drained" not in recorded
        assert SearchIndexUpdate.objects.count() == 1


@pytest.mark.django_db
class TestSignalConnectivity:
    """The receivers are registered for both models."""

    def test_receivers_connected(self):
        from django.db.models.signals import post_delete, post_save

        assert post_save.has_listeners(Bank)
        assert post_delete.has_listeners(Bank)
        assert post_save.has_listeners(CreditCard)
        assert post_delete.has_listeners(CreditCard)

    def test_full_signal_queue_index_flow(
        self, django_capture_on_commit_callbacks, settings
    ):
        """End to end: save -> commit -> queue -> drain -> index."""
        from search.queue import drain

        settings.SEARCH_SYNC_MODE = "queue"
        service = RecordingService()
        with django_capture_on_commit_callbacks(execute=True):
            bank = Bank.objects.create(name="Flow Bank")
        assert pending_rows() == 1
        summary = drain(service=service)
        assert summary["indexed"] == 1
        assert bank.pk in service.indexed["banks"]
        assert pending_rows() == 0


def pending_rows():
    """Return the number of pending outbox rows."""
    return SearchIndexUpdate.objects.filter(
        status=SearchIndexUpdate.STATUS_PENDING
    ).count()
