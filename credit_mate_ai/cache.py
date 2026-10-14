"""Query-aware caching helpers for the credit card API.

Design notes (addressing code review):
- Cache keys are built from a JSON-canonicalized list of (key, values)
  pairs preserving multi-value order (last-value-wins filter semantics),
  plus the request origin and path, hashed to a bounded digest.
- Invalidation uses version counters bumped atomically inside
  ``transaction.on_commit`` so pre-commit data can never be re-cached
  under a new version.
"""

import hashlib
import json

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

CARD_LIST_VERSION_KEY = "credit_cards:list:version"
FILTER_RESULTS_VERSION_KEY = "credit_cards:filter:version"
SEARCH_SUGGESTIONS_VERSION_KEY = "credit_cards:search_suggestions:version"
ADVANCED_SEARCH_VERSION_KEY = "credit_cards:advanced_search:version"

# Distinct TTLs per cached surface (seconds, from settings with env overrides)
CARD_LIST_TTL = getattr(settings, "CACHE_TTL_CARD_LIST", 300)  # 5 minutes
FILTER_RESULTS_TTL = getattr(settings, "CACHE_TTL_FILTER_RESULTS", 120)  # 2 min
SEARCH_SUGGESTIONS_TTL = getattr(
    settings, "CACHE_TTL_SEARCH_SUGGESTIONS", 600
)  # 10 minutes
ADVANCED_SEARCH_TTL = getattr(settings, "CACHE_TTL_ADVANCED_SEARCH", 120)  # 2 min


def _get_cache_version(version_key):
    """Return the current integer cache version, atomically initialized.

    Uses ``cache.add`` (SETNX) so concurrent callers can never reset an
    existing version back to 1.
    """
    cache.add(version_key, 1, None)
    return cache.get(version_key)


def bump_cache_versions():
    """Schedule invalidation of all credit card cache surfaces at commit.

    The bump runs inside ``transaction.on_commit`` and uses atomic
    ``add`` + ``incr`` so a missing key never resets the version and
    pre-commit data is never re-cached under a new version.
    """

    def _bump():
        for version_key in (
            CARD_LIST_VERSION_KEY,
            FILTER_RESULTS_VERSION_KEY,
            SEARCH_SUGGESTIONS_VERSION_KEY,
        ):
            # Atomically initialize (SETNX) before incrementing so a
            # missing key never resets an existing version.
            cache.add(version_key, 1, None)
            cache.incr(version_key)

    transaction.on_commit(_bump)


def canonicalize_query_params(query_params):
    """Canonicalize a QueryDict to a JSON string.

    - Parameter names are sorted, so single-valued reordered queries
      (``?a=1&b=2`` vs ``?b=2&a=1``) map to the same canonical form.
    - Multi-value ordering is preserved because django-filter applies
      last-value-wins semantics (``bank=1&bank=2`` != ``bank=2&bank=1``).
    - JSON encoding avoids ``&``/``=`` join ambiguity when values contain
      those characters.
    """
    items = []
    for key in sorted(query_params.keys()):
        values = query_params.getlist(key)
        items.append([key, values])
    return json.dumps(items, separators=(",", ":"))


def build_query_cache_key(prefix, version_key, request):
    """Build a stable, bounded, query-specific cache key.

    The digest covers the canonicalized query params plus the request
    origin and path, because DRF paginated responses embed absolute
    ``next``/``previous`` URLs derived from the request origin.

    Parameters
    ----------
    prefix : str
        Cache key prefix identifying the cached surface.
    version_key : str
        Version key used for coarse invalidation.
    request : HttpRequest
        The incoming request.

    Returns
    -------
    str
        Bounded cache key including the current cache version.
    """
    canonical_query = canonicalize_query_params(request.GET)
    origin = request.build_absolute_uri("/").rstrip("/")
    fingerprint = f"{origin}{request.path}:{canonical_query}"
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:32]
    version = _get_cache_version(version_key)
    return f"{prefix}:v{version}:{digest}"


@receiver([post_save, post_delete], sender="credit_cards.CreditCard")
def invalidate_credit_card_caches(sender, **kwargs):
    """Invalidate credit card caches when a card is created/updated/deleted."""
    bump_cache_versions()


@receiver([post_save, post_delete], sender="banks.Bank")
def invalidate_card_caches_on_bank_change(sender, **kwargs):
    """Invalidate credit card caches when bank data changes.

    Bank names appear in card list/filter payloads and search
    suggestions, so card caches depend on bank data too.
    """
    bump_cache_versions()


def bump_advanced_search_version():
    """Schedule invalidation of advanced search cache at commit."""

    def _bump():
        from django.core.cache import cache

        cache.add(ADVANCED_SEARCH_VERSION_KEY, 1, None)
        cache.incr(ADVANCED_SEARCH_VERSION_KEY)

    from django.db import transaction

    transaction.on_commit(_bump)


@receiver([post_save, post_delete], sender="credit_cards.CreditCard")
def invalidate_advanced_search_on_card_change(sender, **kwargs):
    """Invalidate advanced search cache when a card changes."""
    bump_advanced_search_version()


@receiver([post_save, post_delete], sender="banks.Bank")
def invalidate_advanced_search_on_bank_change(sender, **kwargs):
    """Invalidate advanced search cache when bank data changes."""
    bump_advanced_search_version()
