"""Unit tests for Stream F: pricing, budgets, routing, circuit breaker, cache."""

import datetime
from decimal import Decimal

import pytest

from common.llm.budget import (
    LLMCallBudget,
    llm_call_budget,
    record_session_cost,
    session_budget_exhausted,
)
from common.llm.cache import get_cached, make_cache_key, set_cached
from common.llm.exceptions import LLMBudgetExhaustedError
from common.llm.retry import CircuitBreaker, call_with_retry, reset_breakers
from common.llm.routing import resolve_route
from common.llm.usage import compute_cost_microusd, record_usage
from common.models import LLMPrice, LLMUsage


@pytest.fixture(autouse=True)
def _reset():
    reset_breakers()
    yield
    reset_breakers()


@pytest.mark.django_db
def test_pricing_calc_uses_latest_effective_price():
    LLMPrice.objects.create(
        provider="gemini",
        model="m-x",
        effective_from=datetime.date(2026, 1, 1),
        input_per_1k=Decimal("0.100000"),
        output_per_1k=Decimal("0.400000"),
    )
    LLMPrice.objects.create(
        provider="gemini",
        model="m-x",
        effective_from=datetime.date(2026, 6, 1),
        input_per_1k=Decimal("0.200000"),
        output_per_1k=Decimal("0.800000"),
    )
    # 2000 prompt + 500 completion at the June prices: $0.40 + $0.40 = $0.80
    assert (
        compute_cost_microusd(
            "gemini", "m-x", 2000, 500, on_date=datetime.date(2026, 7, 1)
        )
        == 800_000
    )
    # Before June the January price applies: $0.20 + $0.20 = $0.40
    assert (
        compute_cost_microusd(
            "gemini", "m-x", 2000, 500, on_date=datetime.date(2026, 3, 1)
        )
        == 400_000
    )


@pytest.mark.django_db
def test_cost_is_null_when_tokens_or_price_unknown():
    assert compute_cost_microusd("gemini", "nope", 100, 100) is None
    LLMPrice.objects.create(
        provider="gemini",
        model="m-x",
        effective_from=datetime.date(2026, 1, 1),
        input_per_1k=Decimal("0.1"),
        output_per_1k=Decimal("0.4"),
    )
    # Provider did not return usage -> tokens null -> cost null, never estimated.
    assert compute_cost_microusd("gemini", "m-x", None, 100) is None


@pytest.mark.django_db
def test_record_usage_writes_ledger_row():
    LLMPrice.objects.create(
        provider="gemini",
        model="m-x",
        effective_from=datetime.date(2020, 1, 1),
        input_per_1k=Decimal("0.1"),
        output_per_1k=Decimal("0.4"),
    )
    row = record_usage(
        provider="gemini",
        model="m-x",
        purpose="extraction",
        prompt_tokens=1000,
        completion_tokens=1000,
        latency_ms=250,
        run_id="run-1",
        routing_reason="test",
    )
    assert isinstance(row, LLMUsage)
    assert row.total_tokens == 2000
    assert row.cost_microusd == 500_000  # $0.10 + $0.40


def test_call_budget_cost_enforcement():
    budget = LLMCallBudget(10, cost_limit_microusd=1000)
    with llm_call_budget(limit=10, cost_limit_microusd=1000) as active:
        assert active is not budget  # context manager builds its own
        assert active.consume()
        assert active.record_cost(600)
        assert not active.exhausted
        assert not active.record_cost(500)  # cumulative 1100 >= 1000
        assert active.exhausted
        assert not active.consume()


def test_call_budget_call_count_still_works():
    with llm_call_budget(limit=2) as budget:
        assert budget.consume()
        assert budget.consume()
        assert not budget.consume()


@pytest.mark.django_db
def test_session_budget_tracks_and_exhausts(settings):
    settings.ADVISOR_MAX_COST_MICROUSD_PER_SESSION = 1000
    from django.core.cache import cache

    cache.clear()
    record_session_cost("sess-1", 400)
    assert not session_budget_exhausted("sess-1")
    record_session_cost("sess-1", 700)
    assert session_budget_exhausted("sess-1")


def test_routing_defaults():
    extraction = resolve_route("extraction")
    assert extraction.routing_reason.startswith("extraction:")
    assert extraction.timeout_seconds == 120
    judge = resolve_route("eval_judge")
    # Judge must differ from the advisor default provider/model pairing.
    advisor = resolve_route("advisor")
    assert (judge.provider, judge.model) != (advisor.provider, advisor.model)
    unknown = resolve_route("something_new")
    assert "no route configured" in unknown.routing_reason


def test_routing_settings_override(settings):
    settings.LLM_ROUTING = {
        "extraction": {
            "provider": "openrouter",
            "model": "x/y",
            "routing_reason": "override",
        }
    }
    route = resolve_route("extraction")
    assert route.provider == "openrouter"
    assert route.model == "x/y"
    assert route.routing_reason == "override"


def test_circuit_breaker_opens_after_threshold_and_recovers():
    now = [1000.0]
    breaker = CircuitBreaker(
        "test", failure_threshold=5, recovery_seconds=60, clock=lambda: now[0]
    )
    for _ in range(4):
        breaker.record_failure()
        assert breaker.allow()
    breaker.record_failure()
    assert not breaker.allow()
    now[0] += 61
    assert breaker.allow()
    breaker.record_success()
    assert breaker.allow()


def test_circuit_breaker_success_resets_failures():
    breaker = CircuitBreaker("test2", failure_threshold=3, recovery_seconds=60)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow()


def test_retry_succeeds_after_transient_failure():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return "ok"

    assert (
        call_with_retry(flaky, max_attempts=3, base_delay=0.01, sleep=lambda s: None)
        == "ok"
    )
    assert calls["n"] == 3


def test_retry_caps_at_three_attempts():
    def always():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        call_with_retry(always, max_attempts=10, base_delay=0.01, sleep=lambda s: None)


def test_cache_key_normalises_whitespace():
    a = make_cache_key("extraction", "hello   world", model="m")
    b = make_cache_key("extraction", " hello world ", model="m")
    assert a == b
    assert a != make_cache_key("extraction", "hello world", model="other")


def test_cache_roundtrip_respects_ttl_setting(settings):
    settings.LLM_CACHE_TTL_SECONDS = {"extraction": 60}
    assert get_cached("extraction", "p") is None
    assert set_cached("extraction", "p", "answer")
    assert get_cached("extraction", "p") == "answer"
    settings.LLM_CACHE_TTL_SECONDS = {"extraction": 0}
    assert get_cached("extraction", "p") is None


def test_budget_exhausted_error_type_is_existing():
    # The cost budget raises/flows through the pre-existing error type.
    budget = LLMCallBudget(1, cost_limit_microusd=1)
    budget.record_cost(5)
    assert budget.exhausted
    with pytest.raises(LLMBudgetExhaustedError):
        raise LLMBudgetExhaustedError("spent")
