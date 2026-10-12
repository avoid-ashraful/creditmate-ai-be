"""Tests for the outbox queue (enqueue, coalescing, drain, retries)."""

from datetime import timedelta

import pytest

from django.utils import timezone

from search.models import SearchIndexUpdate
from search.queue import (
    drain,
    enqueue,
    pending_count,
    prune_done,
    queue_depth,
    retry_failed,
)
from search.tests.fakes import RecordingService


def queued(capture, *args, **kwargs):
    """Run ``enqueue`` and execute its ``transaction.on_commit`` callbacks.

    ``pytest.mark.django_db`` wraps every test in a transaction, so rows are
    deferred exactly like they would be inside a real request transaction;
    this helper executes the callbacks so the row becomes visible.
    """
    with capture(execute=True):
        enqueue(*args, **kwargs)


@pytest.mark.django_db
class TestEnqueue:
    """Rows are only written once the surrounding transaction commits."""

    def test_enqueue_defers_until_commit(self, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            enqueue("banks", 41)
            # Inside the transaction the row does not exist yet.
            assert not SearchIndexUpdate.objects.filter(object_id=41).exists()
        assert len(callbacks) == 1, "expected exactly one on-commit callback"
        row = SearchIndexUpdate.objects.get()
        assert row.index_name == "banks"
        assert row.object_id == 41
        assert row.action == SearchIndexUpdate.ACTION_INDEX
        assert row.status == SearchIndexUpdate.STATUS_PENDING

    def test_repeated_saves_coalesce_into_one_row(
        self, django_capture_on_commit_callbacks
    ):
        queued(django_capture_on_commit_callbacks, "credit_cards", 7)
        queued(django_capture_on_commit_callbacks, "credit_cards", 7)
        queued(django_capture_on_commit_callbacks, "credit_cards", 7)
        assert pending_count() == 1

    def test_delete_supersedes_pending_index(self, django_capture_on_commit_callbacks):
        queued(django_capture_on_commit_callbacks, "credit_cards", 8, "index")
        queued(django_capture_on_commit_callbacks, "credit_cards", 8, "delete")
        row = SearchIndexUpdate.objects.get()
        assert row.action == SearchIndexUpdate.ACTION_DELETE

    def test_index_after_delete_queues_fresh_index(
        self, django_capture_on_commit_callbacks
    ):
        queued(django_capture_on_commit_callbacks, "credit_cards", 9, "delete")
        queued(django_capture_on_commit_callbacks, "credit_cards", 9, "index")
        # delete + re-create are two distinct operations for the engine.
        assert pending_count() == 2

    def test_queue_depth_per_index(self, django_capture_on_commit_callbacks):
        queued(django_capture_on_commit_callbacks, "banks", 1)
        queued(django_capture_on_commit_callbacks, "banks", 2)
        queued(django_capture_on_commit_callbacks, "credit_cards", 3)
        depth = queue_depth()
        assert depth["banks"] == 2
        assert depth["credit_cards"] == 1
        assert depth["total"] == 3


@pytest.mark.django_db
class TestDrain:
    """Draining pushes documents to the (fake) engine and marks rows done."""

    def test_drain_indexes_document(self, django_capture_on_commit_callbacks, db):
        from banks.factories import BankFactory

        bank = BankFactory(name="Drain Bank")
        queued(django_capture_on_commit_callbacks, "banks", bank.pk)
        service = RecordingService()
        summary = drain(service=service)

        assert summary["indexed"] == 1
        assert summary["failed"] == 0
        assert summary["remaining"] == 0
        assert bank.pk in service.indexed["banks"]
        assert service.indexed["banks"][bank.pk]["name"] == "Drain Bank"
        assert service.refresh_calls == 1
        row = SearchIndexUpdate.objects.get()
        assert row.status == SearchIndexUpdate.STATUS_DONE
        assert row.attempts == 1

    def test_drain_deletes_document(self, django_capture_on_commit_callbacks):
        queued(
            django_capture_on_commit_callbacks,
            "banks",
            500,
            SearchIndexUpdate.ACTION_DELETE,
        )
        service = RecordingService()
        service.indexed["banks"] = {500: {"id": 500}}
        summary = drain(service=service)

        assert summary["deleted"] == 1
        assert 500 in service.deleted["banks"]
        assert 500 not in service.indexed["banks"]
        assert SearchIndexUpdate.objects.get().status == SearchIndexUpdate.STATUS_DONE

    def test_drain_handles_missing_object_as_delete(
        self, django_capture_on_commit_callbacks
    ):
        queued(django_capture_on_commit_callbacks, "banks", 999999)  # no such bank
        service = RecordingService()
        summary = drain(service=service)
        assert summary["deleted"] == 1
        assert summary["processed"] == 1
        assert SearchIndexUpdate.objects.get().status == SearchIndexUpdate.STATUS_DONE

    def test_failed_drain_backs_off_and_keeps_row_pending(
        self, django_capture_on_commit_callbacks
    ):
        queued(django_capture_on_commit_callbacks, "banks", 600)
        service = RecordingService(fail=True)
        before = timezone.now()
        summary = drain(service=service)

        assert summary["failed"] == 1
        assert summary["errors"]
        row = SearchIndexUpdate.objects.get()
        assert row.status == SearchIndexUpdate.STATUS_PENDING
        assert row.attempts == 1
        assert "engine is down" in row.last_error
        assert row.available_at > before + timedelta(seconds=4)
        # Nothing is drained while the backoff window is open.
        summary_second = drain(service=RecordingService())
        assert summary_second["processed"] == 0

    def test_exhausted_retries_mark_row_failed(self, django_capture_on_commit_callbacks):
        queued(django_capture_on_commit_callbacks, "banks", 700)
        row = SearchIndexUpdate.objects.get()
        row.attempts = 5
        row.save(update_fields=["attempts"])
        drain(service=RecordingService(fail=True))
        row.refresh_from_db()
        assert row.status == SearchIndexUpdate.STATUS_FAILED
        assert pending_count() == 0

    def test_retry_failed_requeues_rows(self, django_capture_on_commit_callbacks):
        queued(django_capture_on_commit_callbacks, "banks", 800)
        drain(service=RecordingService(fail=True))
        SearchIndexUpdate.objects.all().update(status=SearchIndexUpdate.STATUS_FAILED)
        assert retry_failed() == 1
        row = SearchIndexUpdate.objects.get()
        assert row.status == SearchIndexUpdate.STATUS_PENDING
        assert row.attempts == 0

    def test_drain_without_rows_is_a_noop(self):
        service = RecordingService()
        summary = drain(service=service)
        assert summary["processed"] == 0
        assert service.refresh_calls == 0
        assert service.created_indexes == []

    def test_drain_creates_the_index_before_writing(
        self, django_capture_on_commit_callbacks, db
    ):
        """An engine auto-created index would use dynamic mappings.

        ``drain`` must therefore make sure the real index definition exists
        before the first write, otherwise a fresh environment silently loses
        the analyzers, synonyms and filterable fields.
        """
        from banks.factories import BankFactory

        bank = BankFactory(name="Create Index Bank")
        queued(django_capture_on_commit_callbacks, "banks", bank.pk)
        service = RecordingService()
        drain(service=service)
        assert service.created_indexes == ["banks"]
        assert bank.pk in service.indexed["banks"]

    def test_prune_done(self, django_capture_on_commit_callbacks):
        queued(django_capture_on_commit_callbacks, "banks", 900)
        SearchIndexUpdate.objects.all().update(status=SearchIndexUpdate.STATUS_DONE)
        SearchIndexUpdate.objects.all().update(
            modified=timezone.now() - timedelta(hours=48)
        )
        assert prune_done(older_than_hours=24) == 1
        assert SearchIndexUpdate.objects.count() == 0

    def test_drain_resolves_index_prefix(
        self, django_capture_on_commit_callbacks, db, settings
    ):
        """Queue rows store logical kinds; the engine gets the real name."""
        from banks.factories import BankFactory

        bank = BankFactory(name="Prefixed Bank")
        settings.SEARCH_INDEX_PREFIX = "ci6_"
        queued(django_capture_on_commit_callbacks, "banks", bank.pk)
        service = RecordingService()
        drain(service=service)
        assert "ci6_banks" in service.indexed
        assert "banks" not in service.indexed
