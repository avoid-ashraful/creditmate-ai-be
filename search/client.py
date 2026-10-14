"""Elasticsearch client lifecycle for the search service."""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_client = None


def is_enabled():
    """Return True when the search service is switched on.

    Returns
    -------
    bool
        True when ``SEARCH_ENABLED`` is truthy.
    """
    return bool(getattr(settings, "SEARCH_ENABLED", False))


def get_client():
    """Return a lazily created Elasticsearch client.

    The client is created once per process and shared.  When the search
    service is disabled a :class:`SearchUnavailable` is raised so callers can
    degrade gracefully instead of crashing the request path.

    Returns
    -------
    elasticsearch.Elasticsearch
        Configured client bound to ``SEARCH_URL``.

    Raises
    ------
    SearchUnavailable
        If ``SEARCH_ENABLED`` is false or the client library is missing.
    """
    global _client
    if not is_enabled():
        raise SearchUnavailable("Search service is disabled (SEARCH_ENABLED=False)")
    if _client is None:
        try:
            from elasticsearch import Elasticsearch
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise SearchUnavailable(
                "elasticsearch client library is not installed"
            ) from exc
        _client = Elasticsearch(
            hosts=[settings.SEARCH_URL],
            request_timeout=settings.SEARCH_REQUEST_TIMEOUT,
            verify_certs=settings.SEARCH_VERIFY_CERTS,
            ssl_show_warn=False,
        )
    return _client


def reset_client():
    """Drop the cached client, mainly for tests.

    Returns
    -------
    None
    """
    global _client
    _client = None


def ping(timeout=2.0):
    """Check whether the search engine answers.

    Parameters
    ----------
    timeout : float
        Request timeout in seconds.

    Returns
    -------
    bool
        True when the engine answered the ping, False otherwise.
    """
    if not is_enabled():
        return False
    try:
        return bool(get_client().ping(request_timeout=timeout))
    except Exception as exc:  # noqa: BLE001 - any engine error means "down"
        logger.debug("Search engine ping failed: %s", exc)
        return False


def engine_info():
    """Return the engine version information.

    Returns
    -------
    dict
        Version payload from the engine, or an empty dict when unavailable.
    """
    info = get_client().info()
    return info.get("version", {})


class SearchUnavailable(Exception):
    """Raised when the search engine cannot be used."""
