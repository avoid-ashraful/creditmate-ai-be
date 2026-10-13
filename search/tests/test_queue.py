"""Tests for the outbox queue (enqueue, coalescing, drain, retries)."""

from datetime import timedelta

import pytest

from django.utils import timezone

from search.models import SearchIndexUpdate
from search.queue import (
    claim_batch,
    drain,
    enqueue,
    pending_count,
    prune_done,
    queue_depth,
    retry_failed,
)
from search.tests.fakes import RecordingService


@pytest.fixture(autouse=True)
def no_index_prefix(settings):
    """Ensure tests use bare index names without a prefix."""
    settings.SEARCH_INDEX_PREFIX = ""


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


@pytest.mark.django_db
class TestAutomaticQueueScheduling:
    """The default queue mode must have a registered periodic worker task."""

    def test_beat_schedule_registers_drain_task(self):
        from credit_mate_ai.celery import app

        entry = app.conf.beat_schedule["search-index-queue-drain"]
        assert entry["task"] == "search.process_index_queue"
        interval = float(entry["schedule"])
        assert interval > 0

        # Celery discovers tasks lazily; importing default modules mirrors
        # worker startup and proves beat's task name is actually registered.
        app.loader.import_default_modules()
        assert entry["task"] in app.tasks

    def test_beat_task_drains_pending_rows(
        self, django_capture_on_commit_callbacks, monkeypatch
    ):
        from banks.factories import BankFactory
        from search.tasks import process_search_index_queue

        bank = BankFactory(name="Beat Queue Bank")
        queued(django_capture_on_commit_callbacks, "banks", bank.pk)
        service = RecordingService()
        monkeypatch.setattr("search.service.SearchService", lambda: service)

        summary = process_search_index_queue()

        assert summary["indexed"] == 1
        assert bank.pk in service.indexed["banks"]
        assert SearchIndexUpdate.objects.get().status == SearchIndexUpdate.STATUS_DONE


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_are_disjoint():
    """Two simultaneous drainers must atomically claim disjoint outbox rows."""
    from threading import Barrier, Thread

    from django.db import close_old_connections

    SearchIndexUpdate.objects.bulk_create(
        [
            SearchIndexUpdate(
                index_name=SearchIndexUpdate.INDEX_CREDIT_CARDS,
                object_id=object_id,
            )
            for object_id in range(10)
        ]
    )
    barrier = Barrier(2)
    results = {}
    errors = []

    def claim(name):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            _, rows = claim_batch(batch_size=5, token=name)
            results[name] = {row.pk for row in rows}
        except Exception as exc:  # surfaced in the main test thread
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [Thread(target=claim, args=(name,)) for name in ("drainer-a", "drainer-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert set(results) == {"drainer-a", "drainer-b"}
    assert results["drainer-a"]
    assert results["drainer-b"]
    assert results["drainer-a"].isdisjoint(results["drainer-b"])


@pytest.mark.django_db
def test_lease_check_rejects_a_mixed_owner_batch():
    from search.queue import _holds_lease

    now = timezone.now()
    first = SearchIndexUpdate.objects.create(
        index_name="banks",
        object_id=1001,
        status=SearchIndexUpdate.STATUS_PROCESSING,
        claimed_by="token-a",
        claimed_at=now,
    )
    second = SearchIndexUpdate.objects.create(
        index_name="banks",
        object_id=1002,
        status=SearchIndexUpdate.STATUS_PROCESSING,
        claimed_by="token-b",
        claimed_at=now,
    )

    assert _holds_lease("token-a", [first]) is True
    assert _holds_lease("token-a", [first, second]) is False
