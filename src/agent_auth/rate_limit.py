# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""In-memory per-token-family rate limiter.

Token-bucket algorithm keyed on ``family_id``: every handler that has
already resolved a non-revoked family calls :meth:`RateLimiter.consume`
before doing its real work. An exhausted bucket surfaces as HTTP 429
with a ``Retry-After`` header; the caller waits and tries again.

State lives in process memory only — there is no persistence across
restarts, and the scope is intentionally single-process. A second
agent-auth process would maintain a separate bucket, which is fine
given the single-user deployment model (see ADR 0026). Idle buckets
are evicted to bound memory; buckets are only created for families
that have already been verified by the caller, so a malicious client
cannot inflate the map by probing unknown ``family_id`` values.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

# Idle TTL for an unused bucket. Long enough that a short interactive
# pause (browsing, approval dialog, coffee break) doesn't reset the
# burst allowance; short enough that stale families for CLI-issued
# one-off tokens don't accumulate forever in memory.
_BUCKET_IDLE_EVICTION_SECONDS = 300.0


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a :meth:`RateLimiter.consume` call.

    ``retry_after_seconds`` is only meaningful when ``allowed`` is
    ``False``; it is the minimum wait before the caller's next attempt
    would succeed (i.e. until at least one token has refilled).
    """

    allowed: bool
    retry_after_seconds: float = 0.0


class RateLimiter:
    """Per-family token-bucket rate limiter.

    ``requests_per_minute`` sets both the sustained rate and the burst
    capacity: a bucket starts full with ``requests_per_minute`` tokens,
    refills at the same rate, and saturates back at capacity. A rate
    of ``0`` disables the limiter entirely — :meth:`consume` always
    returns an allowed decision and does not touch the bucket map.

    The class is thread-safe: a single ``threading.Lock`` guards the
    bucket map. The lock is held only for the constant-time update
    per call, not across the handler body.
    """

    def __init__(
        self,
        requests_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        idle_eviction_seconds: float = _BUCKET_IDLE_EVICTION_SECONDS,
    ):
        if requests_per_minute < 0:
            raise ValueError(
                f"RateLimiter: requests_per_minute must be >= 0, got {requests_per_minute}"
            )
        self._capacity: float = float(requests_per_minute)
        self._refill_rate_per_second: float = self._capacity / 60.0
        self._clock = clock
        self._idle_eviction_seconds = idle_eviction_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._capacity > 0.0

    def consume(self, family_id: str) -> RateLimitDecision:
        """Consume one token from ``family_id``'s bucket.

        When the limiter is disabled, returns an allowed decision
        immediately without allocating a bucket. Otherwise a bucket
        is created on first touch for the family, refilled by the
        elapsed time since its last update, and either decremented
        (allowed) or left untouched with a ``retry_after_seconds``
        computed from the shortfall (denied).
        """
        if not self.enabled:
            return RateLimitDecision(allowed=True)

        now = self._clock()
        with self._lock:
            self._evict_idle_locked(now)
            bucket = self._buckets.get(family_id)
            if bucket is None:
                # Start full: the first N requests of a fresh family
                # burst through without refill, matching the spirit
                # of the configured per-minute rate.
                bucket = _Bucket(tokens=self._capacity, last_refill=now)
                self._buckets[family_id] = bucket

            # Refill: the number of tokens accrued since the last
            # update, capped at ``capacity``.
            elapsed = max(0.0, now - bucket.last_refill)
            bucket.tokens = min(
                self._capacity,
                bucket.tokens + elapsed * self._refill_rate_per_second,
            )
            bucket.last_refill = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return RateLimitDecision(allowed=True)

            # Denied. Compute how long the caller must wait for a
            # whole token to refill — the minimum honest retry-after.
            needed = 1.0 - bucket.tokens
            retry_after = needed / self._refill_rate_per_second
            return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

    def _evict_idle_locked(self, now: float) -> None:
        """Remove buckets not touched in ``idle_eviction_seconds``.

        Keeps memory bounded by the set of actively-used families,
        not the set of all families ever issued. Called under the
        bucket map lock, so concurrent consumers block for at most
        one sweep; the sweep is O(buckets) but buckets are bounded
        by the number of active families.
        """
        stale = [
            fid
            for fid, bucket in self._buckets.items()
            if now - bucket.last_refill > self._idle_eviction_seconds
        ]
        for fid in stale:
            del self._buckets[fid]


@dataclass
class _Bucket:
    tokens: float
    last_refill: float
