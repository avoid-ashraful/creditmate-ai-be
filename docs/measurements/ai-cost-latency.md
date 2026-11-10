# AI Cost & Latency — BEFORE baseline (Stream F)

Status: **instrumentation landed; baseline measurements NOT yet taken.**
This document is the measurement skeleton. Numbers are recorded only
when measured on the fixed workloads below — never estimated.

## What is now instrumented

- `common.models.LLMUsage` — one ledger row per provider call
  (provider, model, purpose, prompt/completion/total tokens, latency_ms,
  cost_microusd, run_id, routing_reason, status). Tokens/cost are `null`
  when a provider does not return usage or no `LLMPrice` row exists —
  never silently estimated.
- `common.models.LLMPrice` — dated pricing config (USD per 1k tokens),
  following the `DepositTaxRule` dated-config pattern. **Seed real prices
  as data rows before interpreting any cost number.** Until then, cost
  columns will be null, which is the honest state.
- Prometheus: `llm_requests_total{provider,model,purpose,status}`,
  `llm_tokens_total{kind}`, `llm_cost_usd_total`,
  `llm_latency_seconds` histogram; dashboard:
  `docs/monitoring/grafana-ai-cost-latency.json` (coordinator to copy
  into the umbrella `monitoring/grafana/dashboards/`).
- Budgets: per-run call cap (existing) + per-run cost cap
  (`LLM_MAX_COST_MICROUSD_PER_RUN`) + per-session cost cap
  (`ADVISOR_MAX_COST_MICROUSD_PER_SESSION`), all flowing through the
  existing `LLMBudgetExhaustedError`.
- Routing: `common/llm/routing.py` (settings `LLM_ROUTING` overrides);
  `routing_reason` stored on every usage row.
- Retry/fallback: bounded backoff with jitter in the orchestrator
  (attempts ≤3, retries consume budget), provider fallback order per
  purpose from the route, circuit breaker opens after 5 consecutive
  failures for 60s. Hand-rolled — tenacity is not a dependency and these
  primitives are ~100 lines; revisit if retry policies grow conditions.
- Caching: exact-match Redis/Django-cache helper
  (`common/llm/cache.py`, per-purpose TTL, default disabled).

## Measurement method (to run after all streams land)

Fixed workloads, same machine, three runs each, report median:

1. **Extraction:** replay the recorded nightly-sync corpus (fixed set of
   sources) with `EVENT` flags in their default state; record from
   `LLMUsage`: calls/run, tokens/run, cost/run (requires seeded prices),
   p50/p95 latency per purpose=extraction.
2. **Advisor:** the eval stream's golden question set (fixed version);
   record cost/question, tokens/question, p50/p95 latency,
   budget-exhaustion count.
3. **Catalogue APIs:** existing umbrella k6 average-load profile against
   the local stack; record p95 per endpoint vs the pre-change baseline.

## BEFORE table (fill when measured)

| Metric | Before | After | Notes |
|---|---|---|---|
| Extraction cost / nightly run | _not measured_ | | requires LLMPrice seed |
| Extraction tokens / run | _not measured_ | | |
| Advisor cost / golden question | _not measured_ | | advisor stream pending |
| Advisor p50 / p95 latency | _not measured_ | | |
| Retrieval p95 | _not measured_ | | pgvector stream pending |
| Exact-cache hit rate | _n/a (disabled by default)_ | | enable per purpose deliberately |

## Out of scope here / later steps

- **Semantic caching** belongs to the retrieval (pgvector) stream and
  applies to *retrieval results only* — never to generated financial
  answers (plan §9.2 decision). When it lands, its threshold must be
  tuned on the golden set with false-hit sampling reported here.
- **Rule (plan §9.3):** any optimisation that regresses the eval
  suite's faithfulness gate is reverted, however much it saves. The
  AFTER column is only valid alongside a re-run of the eval gates.
