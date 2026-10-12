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


@pytest.mark.django_db
class TestRelatedDocumentSync:
    """Denormalised values must be refreshed in the other index too.

    Card documents store ``bank_name`` and bank documents store the active
    card count, so one write has to queue rows for both indexes.
    """

    def _bank(self, name="Relation Bank"):
        return Bank.objects.create(name=name)

    def _card(self, bank, name="Relation Card", **kwargs):
        return CreditCard.objects.create(bank=bank, name=name, **kwargs)

    def _queued(self, index_name, action="index"):
        return sorted(
            SearchIndexUpdate.objects.filter(
                index_name=index_name, action=action
            ).values_list("object_id", flat=True)
        )

    def test_bank_rename_queues_every_related_card(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = self._bank()
            self._card(bank, "Card A")
            self._card(bank, "Card B")
        SearchIndexUpdate.objects.all().delete()

        with django_capture_on_commit_callbacks(execute=True):
            bank.name = "Renamed Relation Bank"
            bank.save()

        card_ids = sorted(bank.credit_cards.values_list("pk", flat=True))
        assert self._queued("banks") == [bank.pk]
        assert self._queued("credit_cards") == card_ids

    def test_bank_save_without_rename_leaves_cards_alone(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = self._bank()
            self._card(bank)
        SearchIndexUpdate.objects.all().delete()

        with django_capture_on_commit_callbacks(execute=True):
            bank.website = "https://renamed.example.com"
            bank.save()

        assert self._queued("banks") == [bank.pk]
        # ``bank_name`` is the only bank value copied into card documents.
        assert self._queued("credit_cards") == []

    def test_card_create_queues_its_bank(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = self._bank()
        SearchIndexUpdate.objects.all().delete()

        with django_capture_on_commit_callbacks(execute=True):
            card = self._card(bank)

        assert self._queued("credit_cards") == [card.pk]
        assert self._queued("banks") == [bank.pk]

    def test_card_move_queues_both_banks(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            source = self._bank("Source Bank")
            target = self._bank("Target Bank")
            card = self._card(source)
        SearchIndexUpdate.objects.all().delete()

        with django_capture_on_commit_callbacks(execute=True):
            card.bank = target
            card.save()

        assert self._queued("banks") == sorted([source.pk, target.pk])
        assert self._queued("credit_cards") == [card.pk]

    def test_card_delete_queues_its_bank(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = self._bank()
            card = self._card(bank)
            card_pk = card.pk
        SearchIndexUpdate.objects.all().delete()

        with django_capture_on_commit_callbacks(execute=True):
            card.delete()

        assert self._queued("credit_cards", "delete") == [card_pk]
        assert self._queued("banks") == [bank.pk]

    def test_card_activation_flip_queues_bank(
        self, django_capture_on_commit_callbacks, settings
    ):
        """The bank document counts *active* cards only."""
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = self._bank()
            card = self._card(bank)
        SearchIndexUpdate.objects.all().delete()

        with django_capture_on_commit_callbacks(execute=True):
            card.is_active = False
            card.save(update_fields=["is_active"])

        assert self._queued("banks") == [bank.pk]
        assert self._queued("credit_cards") == [card.pk]

    def test_unrelated_card_edit_leaves_banks_alone(
        self, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = self._bank()
            card = self._card(bank)
        SearchIndexUpdate.objects.all().delete()

        with django_capture_on_commit_callbacks(execute=True):
            card.name = "Relation Card v2"
            card.save()

        assert self._queued("credit_cards") == [card.pk]
        assert self._queued("banks") == []

    def test_bank_rename_with_rollback_queues_nothing(
        self, django_capture_on_commit_callbacks, settings
    ):
        """Rollback behaviour must not change for related rows."""
        from django.db import transaction

        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            bank = self._bank()
            card = self._card(bank)
            card_pk, bank_pk = card.pk, bank.pk
        SearchIndexUpdate.objects.all().delete()

        with django_capture_on_commit_callbacks(execute=True) as rolled_back:
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    bank.name = "Never Committed"
                    bank.save()
                    self._card(bank, "Never Committed Card")
                    raise RuntimeError("boom")

        assert rolled_back == []
        assert SearchIndexUpdate.objects.count() == 0
        assert Bank.objects.filter(pk=bank_pk).get().name == "Relation Bank"
        assert CreditCard.objects.filter(pk=card_pk).exists()

    def test_bank_delete_still_wins_over_related_index_rows(
        self, django_capture_on_commit_callbacks, settings
    ):
        """Cascading deletes must not resurrect the bank document."""
        settings.SEARCH_SYNC_MODE = "queue"
        with django_capture_on_commit_callbacks(execute=True):
            bank = self._bank()
            card_a = self._card(bank, "Cascading Card A")
            card_b = self._card(bank, "Cascading Card B")
            bank_pk = bank.pk
        card_pks = sorted([card_a.pk, card_b.pk])
        SearchIndexUpdate.objects.all().delete()

        with django_capture_on_commit_callbacks(execute=True):
            bank.delete()

        # The card delete signals queue a bank index row, but the bank's own
        # delete row supersedes it: delete wins.
        bank_rows = SearchIndexUpdate.objects.filter(index_name="banks")
        assert list(bank_rows.values_list("object_id", "action")) == [(bank_pk, "delete")]
        assert self._queued("credit_cards", "delete") == card_pks


def pending_rows():
    """Return the number of pending outbox rows."""
    return SearchIndexUpdate.objects.filter(
        status=SearchIndexUpdate.STATUS_PENDING
    ).count()
