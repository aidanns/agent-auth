# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Performance-budget assertion for gpg-bridge sign / verify.

``design/DESIGN.md`` § Performance budget § gpg-bridge documents the
latency target; this test materialises that target into a deterministic
gate so a regression (an extra subprocess spawn, a stray sleep, an
unindexed lookup added later) fails CI rather than surfacing in
production.

The bridge spawns the configured ``gpg_backend_command`` per request,
so the dominant cost is Python interpreter startup for the backend CLI
plus the host ``gpg`` process. To keep the measurement focused on what
the bridge can actually control, the test points the backend at the
in-tree fake (``python -m gpg_backend_fake``) — that keeps subprocess
startup realistic without inheriting the unbounded variance of real
GPG key operations.

The test is sequential and in-process: concurrency-level throughput is
out of scope per ``design/DESIGN.md`` § gpg-bridge ("Throughput is
intentionally not budgeted"). Budgets include enough headroom over the
local devcontainer baseline (~72 ms p50, ~75-122 ms p95) to absorb
GitHub Actions / macOS CI noise without flaking; see DESIGN.md for
rationale.
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

from gpg_bridge.authz import AgentAuthClient
from gpg_bridge.config import Config
from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_bridge.metrics import build_registry
from gpg_bridge.server import GpgBridgeServer

# Budgets below match design/DESIGN.md § Performance budget § gpg-bridge
# verbatim. Update both together — the DESIGN.md table is the source of
# truth.
SIGN_P50_BUDGET_MS = 200.0
SIGN_P95_BUDGET_MS = 500.0
VERIFY_P50_BUDGET_MS = 200.0
VERIFY_P95_BUDGET_MS = 500.0
SAMPLES = 100
WARMUP = 5

_FIXTURE: dict[str, list[dict[str, object]]] = {
    "keys": [
        {
            "fingerprint": "D7A2B4C0E8F11234567890ABCDEF1234567890AB",
            "user_ids": ["Test Key <test@example.invalid>"],
            "aliases": ["test@example.invalid"],
        }
    ],
}


class _NoopAuthz(AgentAuthClient):
    """Stub authz client — perf budget tests bridge-side latency only.

    The ``/validate`` round-trip is gated by agent-auth's own perf
    budget (see ``packages/agent-auth/tests/test_perf_budget.py``); we
    do not want a second copy of that floor here.
    """

    def __init__(self) -> None:
        super().__init__("http://test-fake")

    def validate(
        self,
        token: str,
        required_scope: str,
        *,
        description: str | None = None,
    ) -> None:
        return None


@pytest.fixture
def perf_bridge(tmp_path: Path):
    fixture_path = tmp_path / "fixture.yaml"
    fixture_path.write_text(yaml.safe_dump(_FIXTURE))

    backend_command = [
        sys.executable,
        "-m",
        "gpg_backend_fake",
        "--fixtures",
        str(fixture_path),
    ]
    gpg = GpgSubprocessClient(command=backend_command, timeout_seconds=30.0)
    registry, metrics = build_registry()
    config = Config(port=0, gpg_backend_command=backend_command)
    server = GpgBridgeServer(config, gpg, _NoopAuthz(), registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def _post_json(url: str, body: dict[str, object]) -> dict[str, object]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer perf-token",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
        assert response.status == 200, response.status
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (matches Prometheus / Grafana default)."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * len(ordered))) - 1))
    return ordered[index]


@pytest.mark.perf_budget
def test_sign_latency_budget(perf_bridge: str) -> None:
    """Sign p50/p95 latency fits the DESIGN.md budget.

    Warms the subprocess module-import cache and HTTP connection once,
    then times ``SAMPLES`` sequential sign requests against the in-tree
    fake backend.
    """
    payload = {
        "local_user": "test@example.invalid",
        "payload_b64": base64.b64encode(b"perf-budget commit payload").decode("ascii"),
        "armor": True,
    }
    sign_url = f"{perf_bridge}/gpg-bridge/v1/sign"

    for _ in range(WARMUP):
        _post_json(sign_url, payload)

    durations_ms: list[float] = []
    for _ in range(SAMPLES):
        start = time.perf_counter()
        _post_json(sign_url, payload)
        durations_ms.append((time.perf_counter() - start) * 1000)

    p50 = _percentile(durations_ms, 50)
    p95 = _percentile(durations_ms, 95)

    # Print on every run so a ratchet-down PR can read the measurement
    # out of the CI log without re-running the test locally.
    print(
        f"\ngpg-bridge sign latency (n={SAMPLES}): "
        f"p50={p50:.2f}ms (budget {SIGN_P50_BUDGET_MS}ms), "
        f"p95={p95:.2f}ms (budget {SIGN_P95_BUDGET_MS}ms)"
    )

    assert p50 <= SIGN_P50_BUDGET_MS, (
        f"gpg-bridge sign p50 {p50:.2f}ms exceeds budget {SIGN_P50_BUDGET_MS}ms — "
        "see design/DESIGN.md § Performance budget § gpg-bridge."
    )
    assert p95 <= SIGN_P95_BUDGET_MS, (
        f"gpg-bridge sign p95 {p95:.2f}ms exceeds budget {SIGN_P95_BUDGET_MS}ms — "
        "see design/DESIGN.md § Performance budget § gpg-bridge."
    )


@pytest.mark.perf_budget
def test_verify_latency_budget(perf_bridge: str) -> None:
    """Verify p50/p95 latency fits the DESIGN.md budget.

    Issues a single sign first to obtain a fake signature whose
    embedded ``FAKE-FP`` and ``PAYLOAD-HASH`` markers the verify path
    will accept. Then warms the connection / subprocess and times
    ``SAMPLES`` sequential verify requests.
    """
    sign_url = f"{perf_bridge}/gpg-bridge/v1/sign"
    verify_url = f"{perf_bridge}/gpg-bridge/v1/verify"
    payload_b64 = base64.b64encode(b"perf-budget commit payload").decode("ascii")

    sign_response = _post_json(
        sign_url,
        {
            "local_user": "test@example.invalid",
            "payload_b64": payload_b64,
            "armor": True,
        },
    )
    signature_b64 = sign_response["signature_b64"]
    assert isinstance(signature_b64, str)

    verify_payload = {"signature_b64": signature_b64, "payload_b64": payload_b64}

    for _ in range(WARMUP):
        _post_json(verify_url, verify_payload)

    durations_ms: list[float] = []
    for _ in range(SAMPLES):
        start = time.perf_counter()
        _post_json(verify_url, verify_payload)
        durations_ms.append((time.perf_counter() - start) * 1000)

    p50 = _percentile(durations_ms, 50)
    p95 = _percentile(durations_ms, 95)

    print(
        f"\ngpg-bridge verify latency (n={SAMPLES}): "
        f"p50={p50:.2f}ms (budget {VERIFY_P50_BUDGET_MS}ms), "
        f"p95={p95:.2f}ms (budget {VERIFY_P95_BUDGET_MS}ms)"
    )

    assert p50 <= VERIFY_P50_BUDGET_MS, (
        f"gpg-bridge verify p50 {p50:.2f}ms exceeds budget {VERIFY_P50_BUDGET_MS}ms — "
        "see design/DESIGN.md § Performance budget § gpg-bridge."
    )
    assert p95 <= VERIFY_P95_BUDGET_MS, (
        f"gpg-bridge verify p95 {p95:.2f}ms exceeds budget {VERIFY_P95_BUDGET_MS}ms — "
        "see design/DESIGN.md § Performance budget § gpg-bridge."
    )
