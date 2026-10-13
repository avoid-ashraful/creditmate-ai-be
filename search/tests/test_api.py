"""Tests for the search HTTP API (engine is faked)."""

import pytest
from rest_framework.test import APIClient

from search.tests.fakes import RecordingService

pytestmark = pytest.mark.django_db


class _StubService:
    """Service double used by the API tests."""

    def __init__(self, available=True):
        self.available = available
        self.search_calls = []
        self.suggest_calls = []
        self._status = {
            "enabled": True,
            "url": "http://127.0.0.1:19200",
            "synonyms": ["visa, credit card"],
            "engine": {"number": "8.19.3"},
            "indexes": {"banks": {"exists": True, "count": 1, "health": "green"}},
            "pending_queue_rows": 0,
            "sync_mode": "queue",  # default, can be overridden by tests
        }

    def search(self, kind, **kwargs):
        self.search_calls.append((kind, kwargs))
        return {"total": 0, "took": 1, "hits": [], "aggregations": {}}

    def suggest(self, kind, query, size=8):
        self.suggest_calls.append((kind, query, size))
        return [{"id": 1, "text": "SkyBlue Visa"}]

    def status(self):
        return self._status


@pytest.fixture()
def stub_service(monkeypatch):
    """Patch the API service factory with a recording double."""
    service = _StubService()
    import search.api.views as views_module

    monkeypatch.setattr(views_module, "_service", lambda: service)
    monkeypatch.setattr("search.api.views.SearchService", lambda: service)
    monkeypatch.setattr("search.client.ping", lambda *a, **k: True)
    return service


class TestSearchEndpoint:
    def test_search_returns_results_envelope(self, stub_service, settings):
        settings.SEARCH_SYNC_MODE = "queue"
        client = APIClient()
        response = client.get("/api/search/", {"q": "visa", "type": "cards"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["query"] == "visa"
        assert payload["type"] == "cards"
        assert "results" in payload
        assert payload["results"]["cards"]["total"] == 0
        kind, kwargs = stub_service.search_calls[0]
        assert kind == "cards"
        assert kwargs["query"] == "visa"
        assert kwargs["page"] == 1

    def test_search_all_targets_both_indexes(self, stub_service):
        client = APIClient()
        response = client.get("/api/search/", {"q": "bank", "type": "all"})
        assert response.status_code == 200
        kinds = [call[0] for call in stub_service.search_calls]
        assert kinds == ["banks", "cards"]

    def test_search_passes_filters_through(self, stub_service):
        client = APIClient()
        response = client.get(
            "/api/search/",
            {"q": "", "type": "cards", "is_active": "true", "annual_fee_max": "1000"},
        )
        assert response.status_code == 200
        _, kwargs = stub_service.search_calls[0]
        assert kwargs["filters"] == {"is_active": "true", "annual_fee_max": "1000"}

    def test_unknown_type_is_404(self, stub_service):
        client = APIClient()
        response = client.get("/api/search/", {"type": "nope"})
        assert response.status_code == 404

    def test_service_unavailable_returns_503(self, monkeypatch):
        import search.api.views as views_module

        def raise_unavailable():
            raise views_module.SearchUnavailable()

        monkeypatch.setattr(views_module, "_service", raise_unavailable)
        client = APIClient()
        response = client.get("/api/search/", {"q": "visa"})
        assert response.status_code == 503


class TestSuggestEndpoint:
    def test_suggestions(self, stub_service):
        client = APIClient()
        response = client.get("/api/search/suggest/", {"q": "sky", "limit": 5})
        assert response.status_code == 200
        assert response.json()["suggestions"][0]["text"] == "SkyBlue Visa"
        assert stub_service.suggest_calls[0] == ("cards", "sky", 5)

    def test_empty_query_returns_empty_list(self, stub_service):
        client = APIClient()
        response = client.get("/api/search/suggest/", {"q": "   "})
        assert response.status_code == 200
        assert response.json()["suggestions"] == []


class TestStatusEndpoint:
    def test_status_exposes_index_metadata(self, stub_service, settings):
        settings.SEARCH_INDEX_PREFIX = ""
        client = APIClient()
        response = client.get("/api/search/status/")
        assert response.status_code == 200
        payload = response.json()
        assert payload["indexes_meta"]["banks"]["index"] == "banks"
        assert payload["indexes_meta"]["cards"]["index"] == "credit_cards"
        assert payload["queue_depth"]["total"] == 0
        # sync_mode can be "queue" or "sync" depending on SEARCH_SYNC_MODE
        assert payload["sync_mode"] in ("queue", "sync")
        assert "annual_fee" in payload["indexes_meta"]["cards"]["filterable_fields"]


class TestQueueReporting:
    def test_status_reports_pending_rows(
        self, stub_service, django_capture_on_commit_callbacks, settings
    ):
        settings.SEARCH_SYNC_MODE = "queue"
        from search.queue import enqueue

        with django_capture_on_commit_callbacks(execute=True):
            enqueue("banks", 1)
        client = APIClient()
        response = client.get("/api/search/status/")
        assert response.status_code == 200
        assert response.json()["queue_depth"]["banks"] == 1


def test_recording_service_used_in_api_module():
    """Guard against accidentally importing the real engine in tests."""
    service = RecordingService()
    service.bulk_index("banks", [(1, {"id": 1})])
    assert service.indexed["banks"][1] == {"id": 1}
