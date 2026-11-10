"""Usage recording + pricing (Stream F).

``record_usage`` is the single choke point called by the provider layer
after every generate_response attempt. It:
  1. computes cost from the dated LLMPrice table (None if tokens or a
     price are unknown — never estimated),
  2. writes an LLMUsage ledger row,
  3. updates Prometheus metrics,
  4. charges the active per-run cost budget and (if given) the per-session
     budget in the cache.

It never raises into the provider path: callers wrap it, and a ledger
failure must not fail a user-visible LLM call.
"""

import logging
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)


def compute_cost_microusd(
    provider, model, prompt_tokens, completion_tokens, on_date=None
):
    """Cost in micro-USD, or None when tokens or pricing are unknown."""
    if prompt_tokens is None or completion_tokens is None or not model:
        return None
    from common.models import LLMPrice

    price = LLMPrice.current_for(provider, model, on_date=on_date)
    if price is None:
        logger.warning("No LLMPrice for %s/%s; cost recorded as null", provider, model)
        return None
    usd = (Decimal(prompt_tokens) / 1000) * price.input_per_1k + (
        Decimal(completion_tokens) / 1000
    ) * price.output_per_1k
    return int((usd * 1_000_000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def record_usage(
    *,
    provider,
    model="",
    purpose="extraction",
    prompt_tokens=None,
    completion_tokens=None,
    total_tokens=None,
    latency_ms=None,
    run_id="",
    session_id="",
    routing_reason="",
    status="success",
):
    """Persist + meter one provider call. Returns the LLMUsage row or None."""
    from common.llm import metrics as llm_metrics

    if (
        total_tokens is None
        and prompt_tokens is not None
        and completion_tokens is not None
    ):
        total_tokens = prompt_tokens + completion_tokens
    cost = compute_cost_microusd(provider, model, prompt_tokens, completion_tokens)

    llm_metrics.llm_requests_total.labels(
        provider=provider, model=model or "unknown", purpose=purpose, status=status
    ).inc()
    if latency_ms is not None:
        llm_metrics.llm_latency_seconds.labels(
            provider=provider, model=model or "unknown", purpose=purpose
        ).observe(latency_ms / 1000)
    for kind, value in (
        ("prompt", prompt_tokens),
        ("completion", completion_tokens),
        ("total", total_tokens),
    ):
        if value is not None:
            llm_metrics.llm_tokens_total.labels(
                provider=provider, model=model or "unknown", purpose=purpose, kind=kind
            ).inc(value)
    if cost is not None:
        llm_metrics.llm_cost_usd_total.labels(
            provider=provider, model=model or "unknown", purpose=purpose
        ).inc(cost / 1_000_000)

    # Budgets: charge the active run budget; the *next* consume() then
    # raises LLMBudgetExhaustedError once the cost cap is spent (a call
    # already in flight cannot be un-spent).
    try:
        from common.llm.budget import current_budget, record_session_cost

        budget = current_budget()
        if budget is not None and cost:
            budget.record_cost(cost)
        if session_id and cost:
            record_session_cost(session_id, cost)
    except Exception:  # budget bookkeeping must not break the call path
        logger.exception("LLM budget bookkeeping failed")

    from common.models import LLMUsage

    return LLMUsage.objects.create(
        provider=provider,
        model=model or "",
        purpose=purpose,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        cost_microusd=cost,
        run_id=run_id or "",
        routing_reason=routing_reason or "",
        status=status,
        occurred_at=timezone.now(),
    )
