"""Config-driven model routing per purpose (Stream F).

Routing is data (``settings.LLM_ROUTING``), logged on every usage row via
``routing_reason`` — never hard-coded at call sites. Defaults:

- extraction / classification -> cheap fast model (nightly-sync pinned lite)
- advisor / advisor_composition -> the configured default model
- eval_judge -> a *separate* model from the advisor default where possible,
  to reduce self-grading bias

Hand-rolled, no new dependency.
"""

import logging
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60


@dataclass
class Route:
    purpose: str
    provider: str = ""
    model: str = ""
    routing_reason: str = "default"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    fallback_providers: list = field(default_factory=list)


def _default_table():
    cheap_model = getattr(settings, "NIGHTLY_SYNC_GEMINI_MODEL", "gemini-3.5-flash-lite")
    default_model = getattr(settings, "GEMINI_MODEL", "gemini-flash-latest")
    return {
        "extraction": {
            "provider": "gemini",
            "model": cheap_model,
            "routing_reason": "extraction: high-volume, cheap model suffices",
            "timeout_seconds": 120,
            "fallback_providers": ["openrouter"],
        },
        "classification": {
            "provider": "gemini",
            "model": cheap_model,
            "routing_reason": "classification: cheap model suffices",
            "timeout_seconds": 30,
            "fallback_providers": ["openrouter"],
        },
        "advisor": {
            "provider": "gemini",
            "model": default_model,
            "routing_reason": "advisor: default composition model",
            "timeout_seconds": 20,
            "fallback_providers": ["openrouter"],
        },
        "advisor_composition": {
            "provider": "gemini",
            "model": default_model,
            "routing_reason": "advisor_composition: default composition model",
            "timeout_seconds": 20,
            "fallback_providers": ["openrouter"],
        },
        "eval_judge": {
            "provider": "openrouter",
            "model": "deepseek/deepseek-chat-v3-0324:free",
            "routing_reason": "eval_judge: separate provider/model from advisor to reduce self-grading bias",
            "timeout_seconds": 60,
            "fallback_providers": ["gemini"],
        },
        "embedding": {
            "provider": "gemini",
            "model": cheap_model,
            "routing_reason": "embedding: cheap model",
            "timeout_seconds": 30,
            "fallback_providers": [],
        },
    }


def resolve_route(purpose="extraction"):
    """Return the Route for ``purpose`` (settings override defaults per key)."""
    table = _default_table()
    overrides = getattr(settings, "LLM_ROUTING", {}) or {}
    if purpose in overrides:
        merged = {**table.get(purpose, {}), **overrides[purpose]}
    elif purpose in table:
        merged = table[purpose]
    else:
        merged = {
            "provider": "",
            "model": "",
            "routing_reason": f"no route configured for purpose={purpose}; provider default",
        }
    route = Route(
        purpose=purpose,
        provider=merged.get("provider", ""),
        model=merged.get("model", ""),
        routing_reason=merged.get("routing_reason", "configured route"),
        timeout_seconds=int(
            merged.get(
                "timeout_seconds",
                (getattr(settings, "LLM_PURPOSE_TIMEOUTS", {}) or {}).get(
                    purpose, DEFAULT_TIMEOUT_SECONDS
                ),
            )
        ),
        fallback_providers=list(merged.get("fallback_providers", [])),
    )
    logger.debug(
        "LLM route %s -> %s/%s (%s)",
        purpose,
        route.provider,
        route.model,
        route.routing_reason,
    )
    return route
