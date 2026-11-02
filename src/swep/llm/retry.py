"""Exponential back-off with jitter (REQ-1.7).

Only failures explicitly marked retryable are retried; authentication errors and
malformed requests fail immediately, because retrying them only burns time.
"""

import random
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from ..logging_utils import get_logger


@dataclass
class RetryPolicy:
    """Retry parameters, mirroring ``llm.retry`` in the YAML configuration."""

    max_attempts: int = 5
    base_delay_s: float = 2.0
    max_delay_s: float = 60.0
    jitter_s: float = 0.5

    @classmethod
    def from_config(cls, config) -> "RetryPolicy":
        return cls(
            max_attempts=int(config.get("llm.retry.max_attempts")),
            base_delay_s=float(config.get("llm.retry.base_delay_s")),
            max_delay_s=float(config.get("llm.retry.max_delay_s")),
            jitter_s=float(config.get("llm.retry.jitter_s", 0.0)),
        )

    def delay_for(self, attempt: int, rng: Optional[random.Random] = None) -> float:
        """Delay before retry number ``attempt`` (1-based)."""
        raw = self.base_delay_s * (2 ** (attempt - 1))
        capped = min(raw, self.max_delay_s)
        jitter = (rng or random).uniform(0, self.jitter_s) if self.jitter_s else 0.0
        return capped + jitter


def call_with_retry(
    func: Callable[[], Any],
    policy: RetryPolicy,
    is_retryable: Callable[[BaseException], bool] = lambda exc: True,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
):
    """Call ``func`` until it succeeds or the retry budget is exhausted.

    ``on_retry(attempt, exc, delay)`` is invoked before sleeping so callers can
    log the event and, for example, add it to the per-record retry count.
    """
    logger = get_logger()
    last_error = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return func()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            last_error = exc
            if not is_retryable(exc) or attempt >= policy.max_attempts:
                raise
            delay = policy.delay_for(attempt)
            logger.warning(
                "attempt %d/%d failed (%s: %s); retrying in %.1fs",
                attempt,
                policy.max_attempts,
                type(exc).__name__,
                exc,
                delay,
            )
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)
    raise last_error  # pragma: no cover - defensive


class AttemptCounter:
    """Small helper that records how many attempts one record consumed."""

    def __init__(self):
        self.attempts = 0

    def __call__(self, attempt: int, exc: BaseException, delay: float):
        self.attempts = attempt

    def bump(self):
        self.attempts += 1


__all__: List[str] = ["RetryPolicy", "call_with_retry", "AttemptCounter"]
