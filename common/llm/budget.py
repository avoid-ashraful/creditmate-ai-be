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
    """Counter of provider calls allowed in one run."""

    def __init__(self, limit):
        """Initialize the budget.

        Parameters
        ----------
        limit : int
            Maximum number of provider calls; ``0`` or less means unlimited.
        """
        self.limit = limit
        self.used = 0

    @property
    def exhausted(self):
        """bool: True once ``limit`` calls were consumed."""
        return self.limit > 0 and self.used >= self.limit

    def consume(self):
        """Count one provider call.

        Returns
        -------
        bool
            False (and nothing is counted) when the budget is already spent.
        """
        if self.exhausted:
            return False
        self.used += 1
        return True


@contextmanager
def llm_call_budget(limit=None):
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
    budget = LLMCallBudget(limit)
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
