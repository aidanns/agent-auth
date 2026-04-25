# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Subprocess-backed :class:`ThingsClient` used by things-bridge.

The bridge no longer embeds Things 3 logic. Each request is translated
into an argv for the configured ``things_client_command`` (default:
``things-client-cli-applescript``), which returns a JSON envelope on
stdout. This module is the only place the bridge reasons about the
subprocess protocol.
"""

import contextlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from typing import IO, Any, cast

from things_bridge.types import ThingsClientCommand
from things_models.errors import (
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)
from things_models.models import Area, AreaId, Project, ProjectId, Todo, TodoId

STDERR_TAIL_MAX_CHARS = 64 * 1024
"""Upper bound on the stderr tail retained for diagnostic messages.

The bridge forwards client stderr to its own stderr *live* so nothing is
buffered indefinitely in memory. The tail only exists so the timeout
diagnostic can include a last-gasp excerpt when the child hung before
writing a structured error.
"""

SUBPROCESS_ENV_EXACT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "TZ",
    }
)
"""Environment variable names passed through to the client subprocess verbatim.

The bridge process may hold secrets in its environment — agent-auth
bearer tokens the operator sets via ``AGENT_AUTH_*``, future signing-key
env fallbacks, unrelated API keys a shell happened to export. The
client CLI runs as the same local user, so no privilege boundary is
crossed by the spawn, but a buggy or rogue client binary inherits read
access to any env var it was handed. Starting from an empty env and
adding only what the shipped client documents it reads prevents that
quiet disclosure. Anything outside this set plus the prefix allowlist
is dropped.
"""

SUBPROCESS_ENV_PREFIX_ALLOWLIST: tuple[str, ...] = (
    "LC_",
    "THINGS_CLIENT_",
)
"""Prefix families forwarded to the client subprocess.

``LC_*`` covers every locale category (``LC_ALL``, ``LC_CTYPE``, …) in
one rule so a user with a non-default locale doesn't see surprise
mojibake in the child's output. ``THINGS_CLIENT_*`` is the documented
knob surface of ``things-client-cli-applescript`` (e.g.
``THINGS_CLIENT_OSASCRIPT_PATH``, ``THINGS_CLIENT_TIMEOUT_SECONDS``) —
stripping these would silently break operator overrides.
"""


def build_subprocess_env(parent_env: Mapping[str, str]) -> dict[str, str]:
    """Return the env dict the client subprocess should see.

    Callers pass the parent environment (typically ``os.environ``); the
    returned dict is a fresh copy containing only allowlisted names.
    """
    env: dict[str, str] = {}
    for name, value in parent_env.items():
        if name in SUBPROCESS_ENV_EXACT_ALLOWLIST or name.startswith(
            SUBPROCESS_ENV_PREFIX_ALLOWLIST
        ):
            env[name] = value
    return env


class ThingsSubprocessClient:
    """Invoke a configured Things client CLI as a subprocess per request.

    ``command`` is a validated argv prefix (e.g.
    ``make_things_client_command(["things-client-cli-applescript"])`` or
    ``make_things_client_command([sys.executable, "-m",
    "things_client_fake", "--fixtures", P])``); sub-commands
    matching the request are appended. ``timeout_seconds`` caps the
    per-call wall clock. Subprocess stderr is forwarded to the bridge's
    own stderr line-by-line as the child writes it, so a misbehaving
    client cannot pin bridge memory by streaming multi-megabyte
    diagnostics. The HTTP response body never contains subprocess
    output.
    """

    def __init__(self, command: ThingsClientCommand, timeout_seconds: float = 35.0):
        # The NewType invariant guarantees non-empty + all-str; no
        # re-validation needed here. Keep the defensive check cheap so
        # a raw list slipping past the type checker still fails loud.
        if not command:
            raise ValueError("ThingsSubprocessClient: command must not be empty")
        self._command = command
        self._timeout_seconds = timeout_seconds

    def list_todos(
        self,
        *,
        list_id: str | None = None,
        project_id: ProjectId | None = None,
        area_id: AreaId | None = None,
        tag: str | None = None,
        status: str | None = None,
    ) -> list[Todo]:
        argv = ["todos", "list"]
        if list_id is not None:
            argv.extend(["--list", list_id])
        if project_id is not None:
            argv.extend(["--project", project_id])
        if area_id is not None:
            argv.extend(["--area", area_id])
        if tag is not None:
            argv.extend(["--tag", tag])
        if status is not None:
            argv.extend(["--status", status])
        payload = self._invoke(argv)
        return [Todo.from_json(t) for t in payload.get("todos", [])]

    def get_todo(self, todo_id: TodoId) -> Todo:
        payload = self._invoke(["todos", "show", todo_id])
        return Todo.from_json(payload["todo"])

    def list_projects(self, *, area_id: AreaId | None = None) -> list[Project]:
        argv = ["projects", "list"]
        if area_id is not None:
            argv.extend(["--area", area_id])
        payload = self._invoke(argv)
        return [Project.from_json(p) for p in payload.get("projects", [])]

    def get_project(self, project_id: ProjectId) -> Project:
        payload = self._invoke(["projects", "show", project_id])
        return Project.from_json(payload["project"])

    def list_areas(self) -> list[Area]:
        payload = self._invoke(["areas", "list"])
        return [Area.from_json(a) for a in payload.get("areas", [])]

    def get_area(self, area_id: AreaId) -> Area:
        payload = self._invoke(["areas", "show", area_id])
        return Area.from_json(payload["area"])

    def _invoke(self, argv: list[str]) -> dict[str, Any]:
        full_command = [*self._command, *argv]
        try:
            process = subprocess.Popen(
                full_command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=build_subprocess_env(os.environ),
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise ThingsError(f"things client not found at {self._command[0]!r}") from exc

        stdout_parts: list[str] = []
        stderr_tail = _BoundedTail(STDERR_TAIL_MAX_CHARS)

        stdout_thread = threading.Thread(
            target=_drain_stdout,
            args=(process.stdout, stdout_parts),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_drain_stderr_forward_and_tail,
            args=(process.stderr, stderr_tail),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            process.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=1.0)
            stdout_thread.join(timeout=1.0)
            stderr_thread.join(timeout=1.0)
            partial = stderr_tail.text().strip()
            print(
                f"things-bridge: things client subprocess timed out after "
                f"{self._timeout_seconds}s: {partial or '<empty stderr>'}",
                file=sys.stderr,
                flush=True,
            )
            raise ThingsError(
                f"things client subprocess timed out after {self._timeout_seconds}s"
            ) from exc

        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)

        stdout = "".join(stdout_parts)
        payload = _parse_payload(stdout, full_command, process.returncode)

        if "error" in payload:
            raise _error_from_payload(payload)

        if process.returncode != 0:
            raise ThingsError(
                f"things client exited {process.returncode} without a structured error body"
            )

        return payload


class _BoundedTail:
    """Append-only tail buffer that drops oldest content past a char cap."""

    def __init__(self, max_chars: int):
        if max_chars <= 0:
            raise ValueError("_BoundedTail: max_chars must be positive")
        self._max = max_chars
        self._parts: list[str] = []
        self._size = 0
        self._lock = threading.Lock()

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        with self._lock:
            if len(chunk) >= self._max:
                self._parts = [chunk[-self._max :]]
                self._size = len(self._parts[0])
                return
            self._parts.append(chunk)
            self._size += len(chunk)
            while self._size > self._max and self._parts:
                dropped = self._parts.pop(0)
                self._size -= len(dropped)

    def text(self) -> str:
        with self._lock:
            return "".join(self._parts)


def _drain_stdout(stream: IO[str] | None, sink: list[str]) -> None:
    if stream is None:
        return
    try:
        for chunk in iter(lambda: stream.read(4096), ""):
            sink.append(chunk)
    finally:
        stream.close()


def _drain_stderr_forward_and_tail(stream: IO[str] | None, tail: _BoundedTail) -> None:
    if stream is None:
        return
    try:
        for chunk in iter(lambda: stream.read(4096), ""):
            sys.stderr.write(chunk)
            sys.stderr.flush()
            tail.append(chunk)
    finally:
        stream.close()


def _parse_payload(stdout: str, command: list[str], returncode: int) -> dict[str, Any]:
    if not stdout or stdout.isspace():
        raise ThingsError(f"things client {command[0]!r} emitted no JSON output (rc={returncode})")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ThingsError(
            f"things client {command[0]!r} emitted non-JSON output (rc={returncode})"
        ) from exc
    if not isinstance(payload, dict):
        raise ThingsError(
            f"things client {command[0]!r} emitted non-object JSON "
            f"(rc={returncode}, got {type(payload).__name__})"
        )
    return cast(dict[str, Any], payload)


def _error_from_payload(payload: dict[str, Any]) -> ThingsError:
    code = payload.get("error")
    detail = payload.get("detail") or ""
    if code == "not_found":
        return ThingsNotFoundError(detail or "not found")
    if code == "things_permission_denied":
        return ThingsPermissionError(detail or "permission denied")
    message = f"{code}: {detail}" if code and detail else detail or code or "things unavailable"
    return ThingsError(message)


__all__ = [
    "SUBPROCESS_ENV_EXACT_ALLOWLIST",
    "SUBPROCESS_ENV_PREFIX_ALLOWLIST",
    "ThingsSubprocessClient",
    "build_subprocess_env",
]
