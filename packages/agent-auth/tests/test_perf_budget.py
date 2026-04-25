# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Performance-budget assertion for the agent hot path.

``design/DESIGN.md`` § Performance budget documents the latency target
for the critical operations; this test materialises that target into a
deterministic gate so a regression (an unindexed query, a new
per-request allocation, a stray ``time.sleep``) fails CI rather than
surfacing in production.

The test is sequential and in-process: concurrency-level throughput
is out of scope for a single-user deployment, and running against a
throwaway ``AgentAuthServer`` on ``127.0.0.1:0`` keeps the budget
insulated from external services. Budgets include enough headroom
over the local baseline to absorb GitHub Actions / macOS CI noise
without flaking; see the DESIGN.md section for rationale.
"""

import os
import threading
import time

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.approval_client import ApprovalClient
from agent_auth.audit import AuditLogger
from agent_auth.config import Config
from agent_auth.metrics import build_registry
from agent_auth.server import AgentAuthServer
from agent_auth.store import TokenStore
from agent_auth.tokens import create_token_pair
from tests_support.http import post

# Budgets below match design/DESIGN.md § Performance budget verbatim.
# Update both together — the DESIGN.md table is the source of truth.
VALIDATE_P50_BUDGET_MS = 10.0
VALIDATE_P95_BUDGET_MS = 50.0
SAMPLES = 100


@pytest.fixture
def perf_server(tmp_path, signing_key, encryption_key):
    config = Config(
        db_path=os.path.join(tmp_path, "tokens.db"),
        log_path=os.path.join(tmp_path, "audit.log"),
        host="127.0.0.1",
        port=0,
    )
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    # Perf hot path is the validate endpoint's allow-tier branch, which
    # never reaches the notifier — an unconfigured ApprovalClient
    # denies without opening a socket and keeps the fixture fast.
    approval_manager = ApprovalManager(ApprovalClient(url=""), store, audit)
    registry, metrics = build_registry()
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager, registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{port}", store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (matches Prometheus / Grafana default)."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * len(ordered))) - 1))
    return ordered[index]


@pytest.mark.perf_budget
def test_validate_allow_tier_latency_budget(perf_server):
    """Allow-tier validate p50/p95 latency fits the DESIGN.md budget.

    Warms the connection pool and SQLite page cache once, then times
    ``SAMPLES`` sequential validates of a known-good access token with
    an allow-tier scope — the single path that every downstream
    bridge/CLI request goes through.
    """
    server, base, store = perf_server
    family_id = "fam-perf"
    store.create_family(family_id, {"things:read": "allow"})
    access_token, _ = create_token_pair(server.signing_key, store, family_id, server.config)

    payload = {"token": access_token, "required_scope": "things:read"}

    # Warm-up: prime the keep-alive connection, SQLite page cache, and
    # audit-log file handle so the timed loop measures steady-state
    # latency rather than cold start.
    for _ in range(5):
        status, body = post(f"{base}/agent-auth/v1/validate", data=payload)
        assert status == 200 and body.get("valid") is True

    durations_ms: list[float] = []
    for _ in range(SAMPLES):
        start = time.perf_counter()
        status, body = post(f"{base}/agent-auth/v1/validate", data=payload)
        durations_ms.append((time.perf_counter() - start) * 1000)
        assert status == 200 and body.get("valid") is True

    p50 = _percentile(durations_ms, 50)
    p95 = _percentile(durations_ms, 95)

    # Print the measurement on every run so a ratchet-down PR can read
    # it out of the CI log without re-running the test locally.
    print(
        f"\nvalidate latency (n={SAMPLES}): "
        f"p50={p50:.2f}ms (budget {VALIDATE_P50_BUDGET_MS}ms), "
        f"p95={p95:.2f}ms (budget {VALIDATE_P95_BUDGET_MS}ms)"
    )

    assert p50 <= VALIDATE_P50_BUDGET_MS, (
        f"validate p50 {p50:.2f}ms exceeds budget {VALIDATE_P50_BUDGET_MS}ms — "
        "see design/DESIGN.md § Performance budget."
    )
    assert p95 <= VALIDATE_P95_BUDGET_MS, (
        f"validate p95 {p95:.2f}ms exceeds budget {VALIDATE_P95_BUDGET_MS}ms — "
        "see design/DESIGN.md § Performance budget."
    )
