"""Tests for the health probes, the /metrics endpoint and HTTP metrics."""

from unittest import mock

import pytest
from prometheus_client import REGISTRY

from django.test import Client, override_settings

from credit_mate_ai import health
from credit_mate_ai.metrics import (
    SEARCH_TYPES,
    increment_comparison,
    increment_search,
    increment_signup,
)

HEALTHZ_URL = "/api/healthz/"
READYZ_URL = "/api/readyz/"
METRICS_URL = "/metrics"

HTTP_REQUESTS = "django_http_requests_total_by_view_transport_method_total"
HTTP_RESPONSES = "django_http_responses_total_by_status_view_method_total"
HTTP_LATENCY_COUNT = "django_http_requests_latency_seconds_by_view_method_count"


def sample(name, labels=None):
    """Return the current value of a registry sample, or 0.0 when absent.

    Parameters
    ----------
    name : str
        Sample name as exposed on /metrics.
    labels : dict, optional
        Label values identifying the sample.

    Returns
    -------
    float
        The sample value.
    """
    value = REGISTRY.get_sample_value(name, labels or {})
    return 0.0 if value is None else value


def healthy_dependencies():
    """Patch the database and cache checks so they always pass.

    Returns
    -------
    unittest.mock._patch
        Patcher to use as a context manager.
    """
    return mock.patch.multiple(
        health, _check_database=mock.DEFAULT, _check_cache=mock.DEFAULT
    )


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


def test_healthz_reports_alive_without_database_access(client):
    """Liveness must answer even when the database cannot be reached."""
    with mock.patch.object(health, "_check_database") as check_database:
        response = client.get(HEALTHZ_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    check_database.assert_not_called()


def test_healthz_allows_head(client):
    """HEAD requests get the same liveness answer without a body."""
    assert client.head(HEALTHZ_URL).status_code == 200


def test_legacy_health_endpoint_is_unchanged(client):
    """The original /health/ endpoint keeps its response shape."""
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_healthz_rejects_post(client):
    """Only read methods are allowed on the probe."""
    assert client.post(HEALTHZ_URL).status_code == 405


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


@override_settings(SEARCH_ENABLED=False)
def test_readyz_returns_200_when_dependencies_answer(client):
    """All healthy dependencies produce 200 with per-check latency."""
    with healthy_dependencies():
        response = client.get(READYZ_URL)

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ready"
    assert set(body["checks"]) == {"database", "cache"}
    for check in body["checks"].values():
        assert check["healthy"] is True
        assert check["latency_ms"] >= 0
    assert body["total_latency_ms"] >= 0


@override_settings(SEARCH_ENABLED=False)
def test_readyz_returns_503_and_sanitized_error_when_database_fails(client):
    """A failing database gives 503 with the class name only, never the message."""
    secret_message = "password=hunter2 host=10.0.0.5"
    with healthy_dependencies():
        with mock.patch.object(
            health, "_check_database", side_effect=RuntimeError(secret_message)
        ):
            response = client.get(READYZ_URL)

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not ready"
    assert body["checks"]["database"]["healthy"] is False
    assert body["checks"]["database"]["error"] == "RuntimeError"
    assert body["checks"]["cache"]["healthy"] is True
    assert b"hunter2" not in response.content
    assert b"10.0.0.5" not in response.content


@override_settings(SEARCH_ENABLED=False)
def test_readyz_returns_503_when_cache_fails(client):
    """A failing cache gives 503 and the failing check is named."""
    with mock.patch.object(health, "_check_database"):
        with mock.patch.object(
            health,
            "_check_cache",
            side_effect=ConnectionError("redis://:secret@10.0.0.9:6379/14"),
        ):
            response = client.get(READYZ_URL)

    assert response.status_code == 503
    assert response.json()["checks"]["cache"]["error"] == "ConnectionError"
    assert b"secret@" not in response.content


@override_settings(SEARCH_ENABLED=False)
def test_readyz_omits_elasticsearch_when_search_disabled(client):
    """Elasticsearch is not checked, and not listed, when search is off."""
    with healthy_dependencies():
        with mock.patch.object(health.search_client, "ping") as ping:
            response = client.get(READYZ_URL)

    assert response.status_code == 200
    assert "elasticsearch" not in response.json()["checks"]
    ping.assert_not_called()


@override_settings(SEARCH_ENABLED=True, READYZ_TIMEOUT_SECONDS=0.5)
def test_readyz_checks_elasticsearch_with_readiness_timeout(client):
    """With search enabled, an unanswered ping gives 503 and uses the timeout."""
    with healthy_dependencies():
        with mock.patch.object(health.search_client, "ping", return_value=False) as ping:
            response = client.get(READYZ_URL)

    assert response.status_code == 503
    ping.assert_called_once_with(timeout=0.5)
    es_check = response.json()["checks"]["elasticsearch"]
    assert es_check["healthy"] is False
    assert es_check["error"] == "DependencyUnavailable"


@override_settings(SEARCH_ENABLED=True)
def test_readyz_elasticsearch_healthy_when_ping_answers(client):
    """A ping that answers marks Elasticsearch healthy and keeps 200."""
    with healthy_dependencies():
        with mock.patch.object(health.search_client, "ping", return_value=True):
            response = client.get(READYZ_URL)

    assert response.status_code == 200
    assert response.json()["checks"]["elasticsearch"]["healthy"] is True


def test_readyz_rejects_post(client):
    """Only read methods are allowed on the readiness probe."""
    assert client.post(READYZ_URL).status_code == 405


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": "redis://127.0.0.1:6379/14",
        }
    },
    READYZ_TIMEOUT_SECONDS=0.5,
)
def test_redis_probe_pings_with_socket_timeouts():
    """The Redis probe pings the cache location with the readiness timeout."""
    with mock.patch("redis.Redis.from_url") as from_url:
        from_url.return_value.ping.return_value = True
        health._check_cache()

    from_url.assert_called_once_with(
        "redis://127.0.0.1:6379/14",
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    from_url.return_value.close.assert_called_once()


@override_settings(
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    }
)
def test_cache_probe_round_trips_non_redis_backend():
    """Non-Redis backends are checked with a set/get round trip."""
    health._check_cache()


@pytest.mark.django_db
def test_database_probe_runs_select_one():
    """The real database check passes against a live connection."""
    health._check_database()


# ---------------------------------------------------------------------------
# /metrics access control
# ---------------------------------------------------------------------------


@override_settings(METRICS_TOKEN="", METRICS_ALLOWED_IPS=[])
def test_metrics_is_denied_by_default(client):
    """With no token and no allowed networks, /metrics is closed."""
    response = client.get(METRICS_URL)
    assert response.status_code == 403


@override_settings(METRICS_TOKEN="s3cret-token", METRICS_ALLOWED_IPS=[])
def test_metrics_accepts_matching_bearer_token(client):
    """A correct bearer token returns the Prometheus text exposition."""
    response = client.get(METRICS_URL, HTTP_AUTHORIZATION="Bearer s3cret-token")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert b"creditmate_comparisons_total" in response.content


@pytest.mark.parametrize(
    "authorization",
    [
        "",
        "Bearer wrong-token",
        "Basic s3cret-token",
        "Bearer",
        "s3cret-token",
    ],
)
@override_settings(METRICS_TOKEN="s3cret-token", METRICS_ALLOWED_IPS=[])
def test_metrics_rejects_wrong_or_malformed_credentials(client, authorization):
    """Wrong, missing or malformed credentials get 403."""
    response = client.get(METRICS_URL, HTTP_AUTHORIZATION=authorization)
    assert response.status_code == 403


@override_settings(METRICS_TOKEN="", METRICS_ALLOWED_IPS=["10.0.0.0/8", "127.0.0.1"])
def test_metrics_allows_configured_addresses_and_networks(client):
    """Addresses inside a configured IP or CIDR range are allowed."""
    assert client.get(METRICS_URL, REMOTE_ADDR="10.20.30.40").status_code == 200
    assert client.get(METRICS_URL, REMOTE_ADDR="127.0.0.1").status_code == 200
    assert client.get(METRICS_URL, REMOTE_ADDR="203.0.113.7").status_code == 403


@override_settings(METRICS_TOKEN="", METRICS_ALLOWED_IPS=["10.0.0.0/8"])
def test_metrics_ignores_spoofed_forwarded_for(client):
    """X-Forwarded-For is client-controlled and must not open the endpoint."""
    response = client.get(
        METRICS_URL, REMOTE_ADDR="203.0.113.7", HTTP_X_FORWARDED_FOR="10.0.0.1"
    )
    assert response.status_code == 403


@override_settings(METRICS_TOKEN="", METRICS_ALLOWED_IPS=["not-a-network", "10.0.0.0/8"])
def test_metrics_skips_invalid_allowlist_entries(client):
    """A malformed entry does not stop valid entries from matching."""
    assert client.get(METRICS_URL, REMOTE_ADDR="10.1.1.1").status_code == 200


@override_settings(METRICS_TOKEN="s3cret-token", METRICS_ALLOWED_IPS=[])
def test_metrics_rejects_post(client):
    """Only read methods are allowed on /metrics."""
    response = client.post(METRICS_URL, HTTP_AUTHORIZATION="Bearer s3cret-token")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# HTTP RED metrics middleware
# ---------------------------------------------------------------------------


def test_middleware_counts_unresolved_paths_as_unknown_view(client):
    """Unmatched paths share the bounded ``unknown`` view label."""
    requests_labels = {"view": "unknown", "transport": "http", "method": "GET"}
    responses_labels = {"status": "404", "view": "unknown", "method": "GET"}
    latency_labels = {"view": "unknown", "method": "GET"}
    before = (
        sample(HTTP_REQUESTS, requests_labels),
        sample(HTTP_RESPONSES, responses_labels),
        sample(HTTP_LATENCY_COUNT, latency_labels),
    )

    response = client.get("/no/such/path/")

    assert response.status_code == 404
    assert sample(HTTP_REQUESTS, requests_labels) == before[0] + 1
    assert sample(HTTP_RESPONSES, responses_labels) == before[1] + 1
    assert sample(HTTP_LATENCY_COUNT, latency_labels) == before[2] + 1


def test_middleware_uses_url_name_as_view_label(client):
    """A resolved route is labelled with its URL name."""
    labels = {"view": "schema", "transport": "http", "method": "GET"}
    before = sample(HTTP_REQUESTS, labels)

    response = client.get("/api/v1/schema/")

    assert response.status_code == 200
    assert sample(HTTP_REQUESTS, labels) == before + 1


def test_middleware_records_5xx_responses(client):
    """An unhandled view exception is recorded as a 500 on its view."""
    labels = {"status": "500", "view": "search-status", "method": "GET"}
    before = sample(HTTP_RESPONSES, labels)
    error_client = Client(raise_request_exception=False)

    with mock.patch(
        "search.api.views.SearchStatusView.get", side_effect=RuntimeError("boom")
    ):
        response = error_client.get("/api/search/status/")

    assert response.status_code == 500
    assert sample(HTTP_RESPONSES, labels) == before + 1


def test_middleware_maps_unknown_methods_to_other(client):
    """Non-standard HTTP methods cannot create new method label values."""
    labels = {"view": "unknown", "transport": "http", "method": "OTHER"}
    before = sample(HTTP_REQUESTS, labels)

    client.generic("PROPFIND", "/no/such/path/")

    assert sample(HTTP_REQUESTS, labels) == before + 1


@override_settings(SEARCH_ENABLED=False, METRICS_TOKEN="s3cret-token")
def test_middleware_skips_health_and_metrics_endpoints(client):
    """Probes and /metrics never create series, so scraping does not count itself."""
    with healthy_dependencies():
        client.get(HEALTHZ_URL)
        client.get(READYZ_URL)
    client.get(METRICS_URL, HTTP_AUTHORIZATION="Bearer s3cret-token")
    client.get("/health/")

    for view in ("healthz", "readyz", "metrics", "health_check"):
        labels = {"view": view, "transport": "http", "method": "GET"}
        assert REGISTRY.get_sample_value(HTTP_REQUESTS, labels) is None


# ---------------------------------------------------------------------------
# Business counters
# ---------------------------------------------------------------------------


def test_business_counters_are_exposed_from_startup():
    """Counters are present on /metrics even before any traffic."""
    assert REGISTRY.get_sample_value("creditmate_comparisons_total") is not None
    assert REGISTRY.get_sample_value("creditmate_signups_total") is not None
    for search_type in SEARCH_TYPES:
        labels = {"search_type": search_type}
        assert REGISTRY.get_sample_value("creditmate_searches_total", labels) is not None


def test_increment_helpers_update_their_counters():
    """Each helper adds one to its own series."""
    before_comparisons = sample("creditmate_comparisons_total")
    before_signups = sample("creditmate_signups_total")
    before_searches = sample("creditmate_searches_total", {"search_type": "advanced"})

    increment_comparison()
    increment_signup()
    increment_search("advanced")

    assert sample("creditmate_comparisons_total") == before_comparisons + 1
    assert sample("creditmate_signups_total") == before_signups + 1
    assert (
        sample("creditmate_searches_total", {"search_type": "advanced"})
        == before_searches + 1
    )


def test_increment_search_rejects_unbounded_search_types():
    """Unknown search types raise instead of creating a new label value."""
    with pytest.raises(ValueError):
        increment_search("free-text-from-user")


# ---------------------------------------------------------------------------
# Search handler hooks
# ---------------------------------------------------------------------------


def test_search_endpoint_counts_search_requests(client):
    """Each request to /api/search/ adds one ``search`` search."""
    labels = {"search_type": "search"}
    before = sample("creditmate_searches_total", labels)

    with mock.patch("search.api.views._service") as service:
        service.return_value.search.return_value = {"total": 0, "hits": []}
        response = client.get("/api/search/", {"q": "amex", "type": "cards"})

    assert response.status_code == 200
    assert sample("creditmate_searches_total", labels) == before + 1


def test_suggest_endpoint_counts_suggest_requests(client):
    """Each request to /api/search/suggest/ adds one ``suggest`` search."""
    labels = {"search_type": "suggest"}
    before = sample("creditmate_searches_total", labels)

    with mock.patch("search.api.views._service") as service:
        service.return_value.suggest.return_value = []
        response = client.get("/api/search/suggest/", {"q": "am", "type": "cards"})

    assert response.status_code == 200
    assert sample("creditmate_searches_total", labels) == before + 1


@pytest.mark.django_db
def test_typeahead_endpoint_counts_typeahead_requests(client):
    """Each credit-card typeahead request adds one ``typeahead`` search."""
    labels = {"search_type": "typeahead"}
    before = sample("creditmate_searches_total", labels)

    response = client.get("/api/v1/credit-cards/typeahead/", {"q": "ca"})

    assert response.status_code == 200
    assert sample("creditmate_searches_total", labels) == before + 1


@pytest.mark.django_db
@override_settings(SEARCH_ENABLED=False)
def test_advanced_search_counts_only_the_search_action(client):
    """The advanced-search list counts; its sort and category helpers do not."""
    labels = {"search_type": "advanced"}
    before = sample("creditmate_searches_total", labels)

    client.get("/api/v1/credit-cards/advanced-search/sort-options/")
    client.get("/api/v1/credit-cards/advanced-search/categories/")
    assert sample("creditmate_searches_total", labels) == before

    response = client.get("/api/v1/credit-cards/advanced-search/")

    assert response.status_code == 200
    assert sample("creditmate_searches_total", labels) == before + 1
