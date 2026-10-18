"""Recognize quota failures across provider and parser exception boundaries."""

import re

from common.llm.exceptions import LLMRateLimitError


def rate_limit_state(error, seen=None):
    """Return whether any/all underlying provider failures are quota failures.

    Parameters
    ----------
    error : Exception or str
        Provider failure, aggregate failure, or parser wrapper.
    seen : set, optional
        Exception identities already inspected to avoid cyclic causes.

    Returns
    -------
    tuple of (bool, bool)
        Whether any failure, and every failure, is rate limited.
    """
    seen = set() if seen is None else seen
    if id(error) in seen:
        return False, False
    seen.add(id(error))
    failures = getattr(error, "failures", None)
    if isinstance(failures, dict) and failures:
        states = [rate_limit_state(value, seen.copy()) for value in failures.values()]
        return any(state[0] for state in states), all(state[1] for state in states)
    cause = getattr(error, "__cause__", None)
    if cause is not None:
        return rate_limit_state(cause, seen)
    limited = isinstance(error, LLMRateLimitError) or bool(
        re.search(
            r"\b429\b|rate[ _-]?limit|quota|resource[_ ]exhausted|too many requests",
            str(error),
            re.IGNORECASE,
        )
    )
    return limited, limited
