"""Retry / fallback / circuit-breaker primitives (Stream F).

Hand-rolled on purpose: tenacity is not in the dependency set and these
three small pieces do not justify a new dependency. Retries are the
caller's responsibility to charge against the budget — the orchestrator
already consumes one budget unit per attempt, so retries consume budget
by construction.
"""

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""


class CircuitBreaker:
    """Open after ``failure_threshold`` consecutive failures for ``recovery_seconds``."""

    def __init__(
        self, name, failure_threshold=5, recovery_seconds=60, clock=time.monotonic
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_at = None

    @property
    def is_open(self):
        with self._lock:
            if self._opened_at is None:
                return False
            if self._clock() - self._opened_at >= self.recovery_seconds:
                self._opened_at = None
                self._consecutive_failures = 0
                return False
            return True

    def allow(self):
        return not self.is_open

    def record_success(self):
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self):
        from common.llm import metrics as llm_metrics

        with self._lock:
            self._consecutive_failures += 1
            if (
                self._consecutive_failures >= self.failure_threshold
                and self._opened_at is None
            ):
                self._opened_at = self._clock()
                llm_metrics.llm_circuit_breaker_total.labels(
                    provider=self.name, event="opened"
                ).inc()
                logger.warning("Circuit breaker OPEN for %s", self.name)


_breakers = {}
_breakers_lock = threading.Lock()


def get_breaker(provider, purpose=""):
    key = f"{provider}:{purpose}" if purpose else provider
    with _breakers_lock:
        if key not in _breakers:
            from django.conf import settings

            _breakers[key] = CircuitBreaker(
                key,
                failure_threshold=int(
                    getattr(settings, "LLM_CIRCUIT_FAILURE_THRESHOLD", 5)
                ),
                recovery_seconds=int(
                    getattr(settings, "LLM_CIRCUIT_RECOVERY_SECONDS", 60)
                ),
            )
        return _breakers[key]


def reset_breakers():
    with _breakers_lock:
        _breakers.clear()


def call_with_retry(
    fn, *, max_attempts=3, base_delay=0.5, max_delay=8.0, sleep=time.sleep, rng=random
):
    """Call ``fn`` with bounded exponential backoff + jitter (max 3 attempts)."""
    attempts = max(1, min(int(max_attempts), 3))
    last_exc = None
    for attempt in range(attempts):
        try:
            return fn()
        except (
            Exception
        ) as exc:  # caller decides retryability via exception type upstream
            last_exc = exc
            if attempt == attempts - 1:
                break
            delay = min(max_delay, base_delay * (2**attempt))
            sleep(delay + rng.uniform(0, delay * 0.25))
    raise last_exc


def call_with_timeout(fn, timeout_seconds):
    """Run ``fn`` in a worker thread, raising TimeoutError past the budget.

    Note: the underlying blocking call may keep running in its thread;
    this bounds how long the *caller* waits, which is what latency
    budgets need.
    """
    if not timeout_seconds or timeout_seconds <= 0:
        return fn()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(fn).result(timeout=timeout_seconds)
    except FutureTimeout as exc:
        raise TimeoutError(f"LLM call exceeded {timeout_seconds}s") from exc
    finally:
        executor.shutdown(wait=False)
