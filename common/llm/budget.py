"""Per-run LLM call budget.

A crawl run opens :func:`llm_call_budget`; the orchestrator then counts every
provider call (retries and fallbacks included) against it. Once the budget is
spent further calls raise :class:`~common.llm.exceptions.LLMBudgetExhaustedError`
and the crawler stops extracting more sources, leaving them for the next run.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings

_current_budget = ContextVar("llm_call_budget", default=None)


class LLMCallBudget:
    """Counter of provider calls (and, Stream F, cost) allowed in one run."""

    def __init__(self, limit, cost_limit_microusd=0):
        """Initialize the budget.

        Parameters
        ----------
        limit : int
            Maximum number of provider calls; ``0`` or less means unlimited.
        cost_limit_microusd : int
            Maximum cumulative cost in micro-USD; ``0`` or less = unlimited.
        """
        self.limit = limit
        self.used = 0
        self.cost_limit_microusd = int(cost_limit_microusd or 0)
        self.cost_used_microusd = 0

    @property
    def cost_exhausted(self):
        return (
            self.cost_limit_microusd > 0
            and self.cost_used_microusd >= self.cost_limit_microusd
        )

    @property
    def exhausted(self):
        """bool: True once the call limit or the cost limit is spent."""
        return (self.limit > 0 and self.used >= self.limit) or self.cost_exhausted

    def record_cost(self, cost_microusd):
        """Charge a completed call's cost; returns False once over budget."""
        if not cost_microusd:
            return True
        self.cost_used_microusd += int(cost_microusd)
        if self.cost_exhausted:
            try:
                from common.llm import metrics as llm_metrics

                llm_metrics.llm_budget_exhaustions_total.labels(kind="cost").inc()
            except Exception:
                pass
            return False
        return True

    def consume(self):
        """Count one provider call.

        Returns
        -------
        bool
            False (and nothing is counted) when the budget is already spent.
        """
        if self.exhausted:
            try:
                from common.llm import metrics as llm_metrics

                llm_metrics.llm_budget_exhaustions_total.labels(
                    kind="cost" if self.cost_exhausted else "calls"
                ).inc()
            except Exception:
                pass
            return False
        self.used += 1
        return True


def session_cost_key(session_id):
    return f"llm:session_cost_microusd:{session_id}"


def session_cost_used(session_id):
    from django.core.cache import cache

    return int(cache.get(session_cost_key(session_id), 0) or 0)


def record_session_cost(session_id, cost_microusd, ttl_seconds=3600):
    """Charge a per-session (advisor) cost budget in the cache.

    Returns the new cumulative cost. When the session cap
    (ADVISOR_MAX_COST_MICROUSD_PER_SESSION) is reached an exhaustion
    metric is recorded; enforcement happens before the *next* call via
    :func:`session_budget_exhausted` (a call already completed cannot be
    un-spent), mirroring the per-run cost budget.
    """
    from django.core.cache import cache

    if not session_id or not cost_microusd:
        return session_cost_used(session_id) if session_id else 0
    key = session_cost_key(session_id)
    try:
        used = cache.incr(key, int(cost_microusd))
    except ValueError:
        cache.set(key, int(cost_microusd), timeout=ttl_seconds)
        used = int(cost_microusd)
    limit = int(getattr(settings, "ADVISOR_MAX_COST_MICROUSD_PER_SESSION", 0) or 0)
    if limit > 0 and used >= limit:
        try:
            from common.llm import metrics as llm_metrics

            llm_metrics.llm_budget_exhaustions_total.labels(kind="session_cost").inc()
        except Exception:
            pass
    return used


def session_budget_exhausted(session_id):
    limit = int(getattr(settings, "ADVISOR_MAX_COST_MICROUSD_PER_SESSION", 0) or 0)
    return bool(session_id) and limit > 0 and session_cost_used(session_id) >= limit


@contextmanager
def llm_call_budget(limit=None, cost_limit_microusd=None):
    """Open the call budget for one run, or reuse the one already open.

    Parameters
    ----------
    limit : int, optional
        Maximum calls for this run. Defaults to ``settings.LLM_MAX_CALLS_PER_RUN``.
        Ignored when an enclosing run already opened a budget.

    Yields
    ------
    LLMCallBudget
        The active budget.
    """
    active = _current_budget.get()
    if active is not None:
        yield active
        return
    if limit is None:
        limit = getattr(settings, "LLM_MAX_CALLS_PER_RUN", 200)
    if cost_limit_microusd is None:
        cost_limit_microusd = getattr(settings, "LLM_MAX_COST_MICROUSD_PER_RUN", 0)
    budget = LLMCallBudget(limit, cost_limit_microusd=cost_limit_microusd)
    token = _current_budget.set(budget)
    try:
        yield budget
    finally:
        _current_budget.reset(token)


def current_budget():
    """Return the active :class:`LLMCallBudget`, or None outside a run."""
    return _current_budget.get()


def llm_budget_exhausted():
    """Return True when a budget is active and already spent."""
    budget = _current_budget.get()
    return budget is not None and budget.exhausted
