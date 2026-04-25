# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the tests-support approve/deny HTTP notifiers.

The integration suite launches these as sidecar processes inside the
test container; the unit suite exercises them in-process against an
OS-assigned port so a regression is caught without a container spin-up.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

from agent_auth.approval_client import ApprovalClient
from tests_support.notifier.server import run_fixed_notifier


def _free_port() -> int:
    # Ask the kernel for an ephemeral port and immediately close: the
    # run_fixed_notifier helper takes a concrete port rather than ":0"
    # so we round-trip through a fresh socket to pick one.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


@pytest.fixture
def approve_notifier():
    port = _free_port()
    thread = threading.Thread(
        target=run_fixed_notifier,
        kwargs={"host": "127.0.0.1", "port": port, "approved": True},
        daemon=True,
    )
    thread.start()
    # The server is a ThreadingHTTPServer so it's listening by the time
    # serve_forever() enters its loop, but we might race a spot check.
    # A short poll keeps the fixture deterministic without a blanket sleep.
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(
                urllib.request.Request(url, data=b"{}", method="POST"),
                timeout=0.1,
            )
            break
        except OSError:
            time.sleep(0.01)
    yield url


@pytest.mark.covers_function("POST Approval Request to Notifier")
def test_approve_notifier_returns_approved_once(approve_notifier):
    client = ApprovalClient(url=approve_notifier, timeout_seconds=2.0)
    result = client.request_approval("fam1", "things:read", "list todos")
    assert result.approved is True
    assert result.grant_type == "once"


def test_notifier_subprocess_exits_cleanly_on_sigterm():
    """#294: ``python -m tests_support.notifier`` must exit on SIGTERM.

    The integration compose stack runs this entrypoint as PID 1 inside
    its container. The Linux kernel ignores signals for which PID 1
    has no handler installed (``SIG_DFL`` is *ignore*, not terminate,
    when the receiver is PID 1), which is why every ``compose_stop``
    sat at the 5 s ``stop_grace_period`` ceiling before this fix —
    docker had to SIGKILL the notifier on every test teardown.

    Spawn the script as a real child process, send SIGTERM, and assert
    it exits with status 0 within a tight budget. A deadlock or a
    missing handler would tip the test into the wall-time guard rather
    than letting it slide past unnoticed.
    """
    port = _free_port()
    cmd = [
        sys.executable,
        "-m",
        "tests_support.notifier",
        "approve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Wait for the notifier to print its ``listening on`` line so
        # we know the signal handlers have been registered before we
        # send SIGTERM (signals can arrive earlier, but a ready stdout
        # line is the minimum guarantee of a stable steady state).
        deadline = time.monotonic() + 5.0
        ready = False
        assert proc.stdout is not None
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.01)
                continue
            if "listening on" in line:
                ready = True
                break
        assert ready, "notifier did not print listening line in 5s"

        signal_at = time.monotonic()
        os.kill(proc.pid, signal.SIGTERM)
        # Allow generous headroom on a slow CI runner but stay well
        # under the 5 s ``stop_grace_period`` so a regression here
        # surfaces as a test failure, not a SIGKILL after-effect.
        try:
            exit_code = proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)
            pytest.fail(
                "notifier did not exit within 3s of SIGTERM — the "
                "PID-1-in-container shutdown handler regressed (#294)"
            )
        elapsed = time.monotonic() - signal_at
        assert exit_code == 0, f"notifier exited {exit_code}, expected 0"
        assert elapsed < 3.0, f"notifier took {elapsed:.2f}s to exit on SIGTERM"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2.0)


def test_approve_notifier_body_shape_is_minimal():
    """Server returns just approved + grant_type; no extra fields."""
    port = _free_port()
    thread = threading.Thread(
        target=run_fixed_notifier,
        kwargs={"host": "127.0.0.1", "port": port, "approved": True},
        daemon=True,
    )
    thread.start()
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + 2.0
    body: bytes = b""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, data=b"{}", method="POST"),
                timeout=0.2,
            ) as resp:
                body = resp.read()
            break
        except OSError:
            time.sleep(0.01)
    payload = json.loads(body.decode("utf-8"))
    assert payload == {"approved": True, "grant_type": "once"}
