# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT
# integration-isolation: in-process-server

"""End-to-end: a wedged gpg subprocess drives a 503 ``signing_backend_unavailable``.

Lives under ``tests/integration/`` (not ``tests/fault/``) because it
exercises real subprocess + HTTP wiring: the bridge spawns the in-tree
``gpg_backend_fake`` subprocess (whose import resolution requires
``packages/gpg-bridge/tests`` on PYTHONPATH — see
``scripts/_bootstrap_venv.sh``) and the test drives the full HTTP path
through a live :class:`GpgBridgeServer` thread. The per-package unit
shard runs raw ``pytest`` without sourcing the bootstrap, so the
fake's subprocess can't import its module from the unit shard's
environment; the integration shard goes through ``task test
--integration`` which sources the bootstrap and exports the right
``PYTHONPATH``. See issue #520 for the gpg-bridge wedge of this
broader pattern.

The companion in-process tests under
``packages/gpg-bridge/tests/fault/test_backend_subprocess_hang.py``
keep the unit-shard-friendly cases that drive a script-on-disk
``gpg`` substitute (no ``gpg_backend_fake`` dependency, no HTTP).
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from gpg_bridge.authz import AgentAuthClient
from gpg_bridge.config import Config
from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_bridge.metrics import build_registry
from gpg_bridge.server import GpgBridgeServer


class _AlwaysAllowAuthz(AgentAuthClient):
    """Test stub that accepts every token / scope without contacting agent-auth."""

    def __init__(self) -> None:
        super().__init__("http://test-fake")

    def validate(self, token: str, required_scope: str, *, description: str | None = None) -> None:
        return None


@pytest.mark.covers_function("Serve GPG Bridge HTTP API")
def test_wedged_gpg_surfaces_signing_backend_unavailable(tmp_path: Path) -> None:
    """End-to-end: a gpg subprocess past the deadline drives 503 ``signing_backend_unavailable``.

    Reproduces the wedge from issue #331: a misconfigured host
    ``gpg-agent`` causes the host gpg subprocess to hang. The fake's
    ``sleep_seconds`` knob simulates that. The bridge's per-subprocess
    timeout fires, the bridge translates the
    ``GpgBackendUnavailableError`` into a 503 with the
    ``signing_backend_unavailable`` code and a remediation hint in
    the body, and the whole thing finishes well inside the
    devcontainer ``gpg-cli`` 30s ceiling so the user sees a
    structured error rather than ``bridge unreachable: timed out``.
    """
    fixture_path = tmp_path / "fixture.yaml"
    # 12s sleep guarantees the bridge's 5s per-subprocess timeout
    # below fires before the fake has a chance to return — without
    # making this test sit through the full 10s production budget.
    fixture_path.write_text(
        yaml.safe_dump(
            {
                "keys": [
                    {
                        "fingerprint": "D7A2B4C0E8F11234567890ABCDEF1234567890AB",
                        "user_ids": ["Test Key <test@example.invalid>"],
                        "aliases": ["test@example.invalid"],
                    }
                ],
                "behaviours": {"sleep_seconds": 12},
            }
        )
    )
    gpg_client = GpgSubprocessClient(
        command=[sys.executable, "-m", "gpg_backend_fake", "--fixtures", str(fixture_path)],
        timeout_seconds=5.0,
    )
    config = Config(port=0)
    registry, metrics = build_registry()
    server = GpgBridgeServer(config, gpg_client, _AlwaysAllowAuthz(), registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        body = json.dumps(
            {
                "local_user": "test@example.invalid",
                "payload_b64": base64.b64encode(b"x").decode("ascii"),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/gpg-bridge/v1/sign",
            data=body,
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        elapsed = time.monotonic() - start

        # Total time must stay well below the 30s gpg-cli ceiling so
        # the directed error reaches the user before the client gives
        # up. The fault test's per-subprocess deadline is 5s, so a
        # 15s ceiling is comfortable while staying CI-stable.
        assert elapsed < 15.0, f"wedge handling took too long: {elapsed:.2f}s"
        assert status == 503, f"expected 503, got {status}"
        payload = json.loads(raw)
        assert payload["error"] == "signing_backend_unavailable"
        # The remediation hint is part of the wire contract — clients
        # forward it to the user. Asserting the substring keeps the
        # detail message stable enough that ``gpg-cli`` can pass it
        # through verbatim.
        assert "allow-loopback-pinentry" in payload["detail"]
        assert "gpg-bridge-host-setup.md" in payload["detail"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
