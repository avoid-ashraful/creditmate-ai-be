"""Liveness and readiness probes for the Django backend.

``/api/healthz/`` only proves the process can answer HTTP and never touches a
dependency, so a Redis or database outage cannot make Kubernetes restart the
pod. ``/api/readyz/`` checks the dependencies the backend cannot serve without
(PostgreSQL, the default cache and, only when search is enabled,
Elasticsearch) and answers 503 while any of them is down.

Failures report the exception class name only. These endpoints are public, so
hostnames, credentials and driver messages must never appear in a response.
"""

import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from search import client as search_client

logger = logging.getLogger(__name__)

CACHE_PROBE_KEY = "creditmate:readyz:probe"
CACHE_PROBE_VALUE = "ok"


class DependencyUnavailable(RuntimeError):
    """Raised by a readiness check when a dependency did not answer correctly."""


@require_http_methods(["GET", "HEAD"])
def healthz(request):
    """Liveness probe: report that the process is serving HTTP.

    Parameters
    ----------
    request : HttpRequest
        Unused. The probe never reads request data.

    Returns
    -------
    JsonResponse
        ``{"status": "alive"}`` with HTTP 200.
    """
    return JsonResponse({"status": "alive"})


@require_http_methods(["GET", "HEAD"])
def readyz(request):
    """Readiness probe: check every dependency this backend needs.

    Parameters
    ----------
    request : HttpRequest
        Unused. The probe never reads request data.

    Returns
    -------
    JsonResponse
        ``{"status": "ready" | "not ready", "checks": {...}, ...}``. Each entry
        in ``checks`` has ``healthy``, ``latency_ms`` and, on failure, an
        ``error`` class name. The response is 200 when every check passes and
        503 otherwise. ``elasticsearch`` is only checked when
        ``SEARCH_ENABLED`` is true.
    """
    started = time.perf_counter()
    checks = {
        "database": _run_check("database", _check_database),
        "cache": _run_check("cache", _check_cache),
    }
    if search_client.is_enabled():
        checks["elasticsearch"] = _run_check("elasticsearch", _check_search)

    healthy = all(check["healthy"] for check in checks.values())
    body = {
        "status": "ready" if healthy else "not ready",
        "checks": checks,
        "total_latency_ms": _elapsed_ms(started),
    }
    return JsonResponse(body, status=200 if healthy else 503)


def _run_check(name, check):
    """Run one readiness check and time it.

    Parameters
    ----------
    name : str
        Dependency name used in log lines.
    check : callable
        Zero-argument function that raises when the dependency is unhealthy.

    Returns
    -------
    dict
        ``healthy`` flag, ``latency_ms`` and ``error`` (exception class name)
        when the check failed.
    """
    started = time.perf_counter()
    try:
        check()
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        logger.warning("Readiness check %s failed: %s", name, type(exc).__name__)
        result = {"healthy": False, "error": type(exc).__name__}
    else:
        result = {"healthy": True}
    result["latency_ms"] = _elapsed_ms(started)
    return result


def _elapsed_ms(started):
    """Return milliseconds elapsed since ``started`` rounded to two decimals.

    Parameters
    ----------
    started : float
        Value returned by ``time.perf_counter()``.

    Returns
    -------
    float
        Elapsed time in milliseconds.
    """
    return round((time.perf_counter() - started) * 1000, 2)


def _timeout_seconds():
    """Return the per-dependency readiness timeout in seconds.

    Returns
    -------
    float
        ``READYZ_TIMEOUT_SECONDS`` from settings, defaulting to 1.0.
    """
    return float(getattr(settings, "READYZ_TIMEOUT_SECONDS", 1.0))


def _check_database():
    """Run ``SELECT 1`` on the default database.

    On PostgreSQL the query runs under a server-side ``statement_timeout``
    equal to the readiness timeout, so a stalled query fails fast.

    Raises
    ------
    DependencyUnavailable
        If the database does not return the expected row.
    """
    timeout_ms = int(_timeout_seconds() * 1000)
    with transaction.atomic(), connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            # SET does not accept bound parameters; timeout_ms is an int.
            cursor.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
        cursor.execute("SELECT 1")
        if cursor.fetchone() != (1,):
            raise DependencyUnavailable("database returned an unexpected result")


def _check_cache():
    """Check the default cache backend.

    Redis is pinged directly with socket timeouts set to the readiness timeout,
    because the Django cache API does not expose them. Any other backend gets a
    set/get round trip through the cache API.

    Raises
    ------
    DependencyUnavailable
        If the cache does not answer or returns the wrong value.
    """
    default_cache = settings.CACHES["default"]
    if default_cache["BACKEND"].endswith("RedisCache"):
        import redis

        timeout = _timeout_seconds()
        client = redis.Redis.from_url(
            default_cache["LOCATION"],
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )
        try:
            if not client.ping():
                raise DependencyUnavailable("redis did not answer ping")
        finally:
            client.close()
        return

    cache.set(CACHE_PROBE_KEY, CACHE_PROBE_VALUE, timeout=30)
    if cache.get(CACHE_PROBE_KEY) != CACHE_PROBE_VALUE:
        raise DependencyUnavailable("cache round trip returned the wrong value")


def _check_search():
    """Ping the Elasticsearch cluster with the readiness timeout.

    Raises
    ------
    DependencyUnavailable
        If the cluster does not answer the ping.
    """
    if not search_client.ping(timeout=_timeout_seconds()):
        raise DependencyUnavailable("elasticsearch did not answer ping")
