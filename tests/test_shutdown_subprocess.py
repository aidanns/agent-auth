# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Subprocess-level shutdown tests for the serve commands.

These tests spawn ``agent-auth serve`` and ``things-bridge serve`` as
real child processes and drive SIGTERM / SIGINT through ``os.kill``.
They cover the two #154 acceptance-criterion corners that the in-process
unit tests in ``test_server_shutdown.py`` /
``test_things_bridge_shutdown.py`` only reach indirectly:

- A follow-up connection is refused after the signal is delivered —
  the real listening socket has been torn down, not just swapped with a
  black-hole handler.
- The process exits with status 0 via the real ``sys.exit(0)`` path,
  not the in-process test that returns from ``run_server`` cleanly.

A keyring backend that works without a GUI is required because
``agent-auth serve`` bootstraps its management token on startup.
``keyrings.alt.file.PlaintextKeyring`` is available as a dev-only
dependency and writes its data under the keyring library's
``data_root()``, which resolves to ``$XDG_DATA_HOME/python_keyring/``
on Linux and ``$HOME/Library/Application Support/python_keyring/`` on
macOS. The fixture below points ``HOME`` and all three XDG dirs at a
per-test ``tmp_path`` so the child's keyring is fully isolated from
the developer's real keyring.
"""

from __future__ import annotations

import os
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import IO, Literal, NamedTuple

import pytest
import yaml


class SpawnedServer(NamedTuple):
    """Handle to a running ``<service> serve`` subprocess under test."""

    proc: subprocess.Popen[str]
    port: int
    stdout: queue.Queue[str | None]


ServerKind = Literal["agent-auth", "things-bridge"]
SpawnFactory = Callable[[ServerKind], SpawnedServer]

# Ceiling on how long we'll wait for the child to print its
# ``listening on`` line. Covers import time + bind + signal-handler
# install; 15s is comfortable on a cold CI runner without masking a
# genuine hang.
READY_TIMEOUT_SECONDS = 15.0

# Configured deadline the shutdown watchdog enforces inside the child.
# A short value keeps the test fast; it also tightens the wall-time
# budget below so a drain regression is caught.
SHUTDOWN_DEADLINE_SECONDS = 1.0

# Upper bound on observable wall time from signal delivery to process
# exit. The child also has thread-join and process-exit work after
# ``drain_complete`` flips, so we allow headroom above
# ``SHUTDOWN_DEADLINE_SECONDS`` for that plus CI scheduler noise — but
# stay tight enough that a deadlock in ``server_close`` trips the
# assertion instead of silently running to the pytest timeout.
WALL_TIME_BUDGET_SECONDS = 3.0

_LISTENING_PATTERN = re.compile(r"listening on (?:https?://)?\d+\.\d+\.\d+\.\d+:(\d+)")


@pytest.fixture
def subprocess_env(tmp_path: Path) -> dict[str, str]:
    """Return an environ dict that fully isolates child filesystem state.

    Points ``HOME`` and all three XDG dirs at ``tmp_path`` so XDG
    lookups (agent-auth's data / state dirs, things-bridge's config
    dir) and keyring storage both resolve inside the per-test tree.
    """
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / ".local" / "share").mkdir(parents=True)
    (home / ".local" / "state").mkdir(parents=True)
    env = {**os.environ}
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "PYTHON_KEYRING_BACKEND": "keyrings.alt.file.PlaintextKeyring",
        }
    )
    return env


def _drain_stream(stream: IO[str], sink: queue.Queue[str | None]) -> None:
    """Forward each line from ``stream`` into ``sink``; append ``None`` on EOF."""
    try:
        for line in stream:
            sink.put(line)
    finally:
        sink.put(None)


def _capture_stdout(proc: subprocess.Popen[str]) -> queue.Queue[str | None]:
    """Spawn a reader thread that drains ``proc.stdout`` into a queue."""
    assert proc.stdout is not None
    out_queue: queue.Queue[str | None] = queue.Queue()
    threading.Thread(
        target=_drain_stream,
        args=(proc.stdout, out_queue),
        daemon=True,
    ).start()
    return out_queue


def _wait_for_listening(
    proc: subprocess.Popen[str],
    out_queue: queue.Queue[str | None],
    *,
    timeout_seconds: float = READY_TIMEOUT_SECONDS,
) -> int:
    """Block until the child prints its bound port; return the int port.

    Raises with the full captured output so a pytest failure surfaces
    *why* the child never became ready (keyring error, import failure,
    YAML typo, etc.) rather than just a timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    captured: list[str] = []
    while time.monotonic() < deadline:
        try:
            line = out_queue.get(timeout=0.1)
        except queue.Empty:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"subprocess exited before reporting listening "
                    f"(exit={proc.returncode}, output={''.join(captured)!r})"
                ) from None
            continue
        if line is None:
            raise RuntimeError(
                f"subprocess stdout closed before reporting listening "
                f"(exit={proc.poll()}, output={''.join(captured)!r})"
            )
        captured.append(line)
        match = _LISTENING_PATTERN.search(line)
        if match:
            return int(match.group(1))
    raise TimeoutError(
        f"subprocess never reported listening within {timeout_seconds}s "
        f"(output so far: {''.join(captured)!r})"
    )


def _drain_remaining(q: queue.Queue[str | None]) -> str:
    """Flush whatever the reader thread has already seen on stdout."""
    chunks: list[str] = []
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        if item is None:
            break
        chunks.append(item)
    return "".join(chunks)


def _write_agent_auth_config(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "host": "127.0.0.1",
                "port": 0,
                "shutdown_deadline_seconds": SHUTDOWN_DEADLINE_SECONDS,
            }
        )
    )


def _write_things_bridge_config(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    # ``auth_url`` points at an unreachable loopback port: the shutdown
    # path never contacts agent-auth, so the URL only has to parse.
    (config_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "host": "127.0.0.1",
                "port": 0,
                "auth_url": "http://127.0.0.1:65535",
                "shutdown_deadline_seconds": SHUTDOWN_DEADLINE_SECONDS,
            }
        )
    )


def _start_child(argv: list[str], env: dict[str, str]) -> SpawnedServer:
    proc = subprocess.Popen(
        argv,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    out_queue = _capture_stdout(proc)
    try:
        port = _wait_for_listening(proc, out_queue)
    except BaseException:
        # Reap the partially-started child when readiness fails so a
        # pytest failure here doesn't leak a process until the worker
        # exits. BaseException so KeyboardInterrupt / timeout in the
        # readiness loop still triggers cleanup.
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)
        raise
    return SpawnedServer(proc=proc, port=port, stdout=out_queue)


@pytest.fixture
def spawn_server(tmp_path: Path, subprocess_env: dict[str, str]) -> Iterator[SpawnFactory]:
    """Factory fixture returning ``(proc, port, stdout_queue)`` tuples.

    Tracks every spawned process and kills any that is still running
    at teardown — including cases where an assertion fires before the
    test's own ``proc.wait`` call runs.
    """
    started: list[SpawnedServer] = []

    def _factory(kind: ServerKind) -> SpawnedServer:
        if kind == "agent-auth":
            _write_agent_auth_config(tmp_path / "agent-auth-config")
            argv = [
                sys.executable,
                "-m",
                "agent_auth.cli",
                "--config-dir",
                str(tmp_path / "agent-auth-config"),
                "serve",
            ]
        else:
            _write_things_bridge_config(Path(subprocess_env["XDG_CONFIG_HOME"]) / "things-bridge")
            argv = [sys.executable, "-m", "things_bridge.cli", "serve"]

        spawned = _start_child(argv, subprocess_env)
        started.append(spawned)
        return spawned

    yield _factory

    for spawned in started:
        if spawned.proc.poll() is None:
            spawned.proc.kill()
            with suppress(subprocess.TimeoutExpired):
                spawned.proc.wait(timeout=5.0)


def _assert_port_refuses_connection(port: int) -> None:
    """A fresh TCP connection attempt to ``port`` must fail.

    ``ConnectionRefusedError`` is the normal case when the listening
    socket has been closed; ``OSError`` covers the rarer "host
    unreachable" shape that appears on some kernels when a just-closed
    port hasn't fully cleared the routing table.
    """
    with (
        pytest.raises((ConnectionRefusedError, OSError)),
        socket.create_connection(("127.0.0.1", port), timeout=1.0),
    ):
        pass


class ShutdownResult(NamedTuple):
    exit_code: int
    elapsed_seconds: float
    stdout: str


def _shutdown_and_measure(spawned: SpawnedServer, sig: int) -> ShutdownResult:
    """Deliver ``sig``, wait for exit, return the outcome."""
    start = time.monotonic()
    os.kill(spawned.proc.pid, sig)
    try:
        exit_code = spawned.proc.wait(timeout=WALL_TIME_BUDGET_SECONDS)
    except subprocess.TimeoutExpired:
        spawned.proc.kill()
        spawned.proc.wait(timeout=5.0)
        raise AssertionError(
            f"subprocess did not exit within {WALL_TIME_BUDGET_SECONDS}s of "
            f"{signal.Signals(sig).name} "
            f"(stdout so far: {_drain_remaining(spawned.stdout)!r})"
        ) from None
    return ShutdownResult(
        exit_code=exit_code,
        elapsed_seconds=time.monotonic() - start,
        stdout=_drain_remaining(spawned.stdout),
    )


@pytest.mark.covers_function("Handle Graceful Shutdown", "Handle Serve Command")
@pytest.mark.parametrize(
    "sig",
    [signal.SIGTERM, signal.SIGINT],
    ids=["sigterm", "sigint"],
)
def test_agent_auth_serve_exits_zero_and_closes_socket(
    spawn_server: SpawnFactory, sig: int
) -> None:
    """Pin the end-to-end shutdown contract for ``agent-auth serve``.

    Exercises the three #154 acceptance properties that only a real
    subprocess can cover: exit status 0, bounded wall time, and a
    genuinely closed listening socket on the far side of the signal.
    """
    spawned = spawn_server("agent-auth")
    result = _shutdown_and_measure(spawned, sig)

    assert result.exit_code == 0, (
        f"agent-auth exited with {result.exit_code} on {signal.Signals(sig).name} "
        f"(stdout: {result.stdout!r})"
    )
    assert result.elapsed_seconds < WALL_TIME_BUDGET_SECONDS, (
        f"agent-auth took {result.elapsed_seconds:.2f}s to exit after "
        f"{signal.Signals(sig).name}; budget is {WALL_TIME_BUDGET_SECONDS}s "
        f"(stdout: {result.stdout!r})"
    )
    _assert_port_refuses_connection(spawned.port)


@pytest.mark.covers_function("Handle Bridge Graceful Shutdown")
@pytest.mark.parametrize(
    "sig",
    [signal.SIGTERM, signal.SIGINT],
    ids=["sigterm", "sigint"],
)
def test_things_bridge_serve_exits_zero_and_closes_socket(
    spawn_server: SpawnFactory, sig: int
) -> None:
    """Mirror of the agent-auth test for ``things-bridge serve``."""
    spawned = spawn_server("things-bridge")
    result = _shutdown_and_measure(spawned, sig)

    assert result.exit_code == 0, (
        f"things-bridge exited with {result.exit_code} on {signal.Signals(sig).name} "
        f"(stdout: {result.stdout!r})"
    )
    assert result.elapsed_seconds < WALL_TIME_BUDGET_SECONDS, (
        f"things-bridge took {result.elapsed_seconds:.2f}s to exit after "
        f"{signal.Signals(sig).name}; budget is {WALL_TIME_BUDGET_SECONDS}s "
        f"(stdout: {result.stdout!r})"
    )
    _assert_port_refuses_connection(spawned.port)
