"""Exact-match cache for LLM / retrieval-style calls (Stream F).

Key = SHA-256 of the normalised (whitespace-collapsed, stripped) JSON of
{purpose, model, system_prompt, prompt}. Per-purpose TTL from
``settings.LLM_CACHE_TTL_SECONDS`` (0 / missing purpose = disabled).

NOTE (scope boundary, plan §9.2): this is exact-match caching only.
Semantic caching is for *retrieval results* via the pgvector stream and
must never cache generated financial answers; it lands with that stream,
not here.
"""

import hashlib
import json
import logging
import re

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)
_WS = re.compile(r"\s+")


def _normalise(text):
    return _WS.sub(" ", (text or "")).strip()


def make_cache_key(purpose, prompt, system_prompt=None, model=""):
    payload = json.dumps(
        {
            "purpose": purpose or "",
            "model": model or "",
            "system_prompt": _normalise(system_prompt),
            "prompt": _normalise(prompt),
        },
        sort_keys=True,
    )
    return "llm:exact:" + hashlib.sha256(payload.encode()).hexdigest()


def ttl_for(purpose):
    ttls = getattr(settings, "LLM_CACHE_TTL_SECONDS", {}) or {}
    return int(ttls.get(purpose, ttls.get("default", 0)) or 0)


def get_cached(purpose, prompt, system_prompt=None, model=""):
    from common.llm import metrics as llm_metrics

    if ttl_for(purpose) <= 0:
        return None
    value = cache.get(make_cache_key(purpose, prompt, system_prompt, model))
    llm_metrics.llm_cache_total.labels(
        purpose=purpose, result="hit" if value is not None else "miss"
    ).inc()
    return value


def set_cached(purpose, prompt, value, system_prompt=None, model=""):
    ttl = ttl_for(purpose)
    if ttl <= 0 or value is None:
        return False
    cache.set(make_cache_key(purpose, prompt, system_prompt, model), value, timeout=ttl)
    return True
