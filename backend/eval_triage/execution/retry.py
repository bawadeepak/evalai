"""Transport retries.

At most ``max_retries`` retries (default 2) for retryable, non-mutating
transport failures (rate limits, network errors, timeouts), with bounded
exponential backoff and jitter. Every attempt is preserved by the caller's
``on_attempt`` callback. A low-quality answer is never retried: retries exist
only for transport failures, and a retried call may still be billed and may
return a different answer.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from eval_triage.adapters.base import TargetResult

RETRYABLE_STATUSES = frozenset({"provider_error", "timeout"})


def backoff_delay(attempt: int, base: float, cap: float, rng: random.Random) -> float:
    return min(cap, base * (2 ** attempt)) * (0.5 + rng.random() / 2)


async def with_transport_retries(
    call: Callable[[int], Awaitable[TargetResult]],
    *,
    max_retries: int = 2,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    mutating: bool = False,
    on_attempt: Callable[[int, TargetResult], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: random.Random | None = None,
) -> TargetResult:
    rng = rng or random.Random()
    result: TargetResult | None = None
    for attempt in range(max_retries + 1):
        result = await call(attempt)
        if on_attempt:
            on_attempt(attempt, result)
        retryable = result.status in RETRYABLE_STATUSES and result.retryable and not mutating
        if not retryable or attempt == max_retries:
            return result
        await sleep(backoff_delay(attempt, base_delay, max_delay, rng))
    assert result is not None
    return result
