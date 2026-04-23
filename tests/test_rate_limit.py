# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for :class:`agent_auth.rate_limit.RateLimiter`.

The HTTP integration (429 response shape, Retry-After header, audit
event) is exercised by ``tests/test_server_rate_limit.py`` and the
bridge-forwarding integration by ``tests/test_things_bridge_authz.py``;
this file pins the token-bucket algorithm itself under a deterministic
clock so refill / eviction behaviour is test-stable.
"""

from __future__ import annotations

import pytest

from agent_auth.rate_limit import RateLimiter


def test_enabled_flag_reflects_configured_rate():
    assert RateLimiter(60).enabled is True
    assert RateLimiter(0).enabled is False


def test_negative_rate_raises_at_construction():
    with pytest.raises(ValueError):
        RateLimiter(-1)


def test_disabled_limiter_always_allows_and_never_allocates():
    # A disabled limiter is what the deferred-posture default (ADR 0022)
    # looked like: every consume returns allowed, and no bucket state
    # accumulates so long-running servers don't grow memory.
    limiter = RateLimiter(0)
    for i in range(1000):
        assert limiter.consume(f"fam-{i}").allowed is True
    assert limiter._buckets == {}


def test_first_n_requests_burst_through_capacity():
    now = [0.0]
    limiter = RateLimiter(60, clock=lambda: now[0])  # 60/min = 1/s, capacity = 60
    for _ in range(60):
        assert limiter.consume("fam-1").allowed is True


def test_exhausted_bucket_denies_with_retry_after():
    now = [0.0]
    limiter = RateLimiter(60, clock=lambda: now[0])
    for _ in range(60):
        limiter.consume("fam-1")
    decision = limiter.consume("fam-1")
    assert decision.allowed is False
    # 60/min → 1 token per second; retry_after should be ~1s.
    assert 0.5 < decision.retry_after_seconds <= 1.0 + 1e-6


def test_bucket_refills_at_configured_rate():
    now = [0.0]
    limiter = RateLimiter(60, clock=lambda: now[0])  # 1 token / second
    for _ in range(60):
        limiter.consume("fam-1")
    assert limiter.consume("fam-1").allowed is False
    now[0] += 1.0
    # One second later, a single token has refilled — exactly one more
    # consume succeeds before the bucket is empty again.
    assert limiter.consume("fam-1").allowed is True
    assert limiter.consume("fam-1").allowed is False


def test_refill_saturates_at_capacity():
    # An idle bucket must not accumulate tokens past capacity — otherwise
    # a family that sits idle for a day could unleash a day-sized burst.
    now = [0.0]
    limiter = RateLimiter(60, clock=lambda: now[0])
    limiter.consume("fam-1")  # create bucket with capacity, consume one
    now[0] += 86_400  # one day idle
    # Now consume 60 times — all should succeed (full bucket) but the
    # 61st is denied.
    for _ in range(60):
        assert limiter.consume("fam-1").allowed is True
    assert limiter.consume("fam-1").allowed is False


def test_buckets_are_per_family_independent():
    now = [0.0]
    limiter = RateLimiter(60, clock=lambda: now[0])
    for _ in range(60):
        limiter.consume("fam-A")
    assert limiter.consume("fam-A").allowed is False
    # fam-B has its own full bucket and is unaffected.
    assert limiter.consume("fam-B").allowed is True


def test_idle_eviction_bounds_memory():
    # A family that hasn't been seen for the idle window is removed so
    # one-off token families don't accumulate forever. Eviction runs
    # opportunistically on the next ``consume`` after the window.
    now = [0.0]
    limiter = RateLimiter(60, clock=lambda: now[0], idle_eviction_seconds=10.0)
    limiter.consume("fam-A")
    assert "fam-A" in limiter._buckets
    now[0] += 11.0  # past the window
    # Any consume now triggers eviction of the stale entry.
    limiter.consume("fam-B")
    assert "fam-A" not in limiter._buckets
    assert "fam-B" in limiter._buckets
