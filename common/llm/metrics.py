"""Prometheus metrics for LLM calls (Stream F).

Defined here (not in credit_mate_ai.metrics) so common.llm never imports
the project package; they register in the same default REGISTRY and are
exposed by the existing /metrics endpoint.
"""

from prometheus_client import Counter, Histogram

llm_requests_total = Counter(
    "llm_requests_total",
    "LLM provider calls",
    ["provider", "model", "purpose", "status"],
)
llm_tokens_total = Counter(
    "llm_tokens_total",
    "LLM tokens by kind (prompt/completion/total)",
    ["provider", "model", "purpose", "kind"],
)
llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "LLM spend in USD (only calls with known pricing and token counts)",
    ["provider", "model", "purpose"],
)
llm_latency_seconds = Histogram(
    "llm_latency_seconds",
    "LLM provider call latency",
    ["provider", "model", "purpose"],
    buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32, 64),
)
llm_budget_exhaustions_total = Counter(
    "llm_budget_exhaustions_total",
    "Times an LLM budget (calls/cost/session) stopped a run",
    ["kind"],
)
llm_cache_total = Counter(
    "llm_cache_total",
    "Exact-match LLM cache lookups",
    ["purpose", "result"],
)
llm_circuit_breaker_total = Counter(
    "llm_circuit_breaker_total",
    "Circuit breaker events",
    ["provider", "event"],
)
