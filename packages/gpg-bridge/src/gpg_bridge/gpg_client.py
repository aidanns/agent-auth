# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Subprocess-backed GPG client used by gpg-bridge.

Mirrors :mod:`things_bridge.things_client` — the only place the bridge
reasons about the backend CLI subprocess protocol.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import IO, Any, cast

from gpg_backend_common.protocol import write_verify_input
from gpg_models.errors import (
    GpgBadSignatureError,
    GpgError,
    GpgNoSuchKeyError,
    GpgPermissionError,
    GpgUnsupportedOperationError,
)
from gpg_models.models import (
    SignRequest,
    SignResult,
    VerifyRequest,
    VerifyResult,
)

STDERR_TAIL_MAX_CHARS = 64 * 1024


class GpgSubprocessClient:
    """Invoke a configured GPG backend CLI as a subprocess per request."""

    def __init__(self, command: list[str], timeout_seconds: float = 35.0):
        if not command:
            raise ValueError("GpgSubprocessClient: command must not be empty")
        self._command = list(command)
        self._timeout_seconds = timeout_seconds

    def sign(self, request: SignRequest) -> SignResult:
        argv = ["sign", "--local-user", request.local_user, "--keyid-format", request.keyid_format]
        if request.armor:
            argv.append("--armor")
        payload = self._invoke(argv, request.payload)
        return SignResult.from_json(payload)

    def verify(self, request: VerifyRequest) -> VerifyResult:
        argv = ["verify", "--keyid-format", request.keyid_format]

        def write_stdin(stream: IO[bytes]) -> None:
            write_verify_input(stream, request.signature, request.payload)

        payload = self._invoke(argv, write_stdin)
        return VerifyResult.from_json(payload)

    def _invoke(
        self,
        argv: list[str],
        stdin_writer: bytes | Callable[[IO[bytes]], None],
    ) -> dict[str, Any]:
        full_command = [*self._command, *argv]
        try:
            process = subprocess.Popen(
                full_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            raise GpgError(f"gpg backend not found at {self._command[0]!r}") from exc

        stdout_parts: list[bytes] = []
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

        stdin_stream = process.stdin
        if stdin_stream is None:
            raise GpgError("gpg backend subprocess stdin is unavailable")
        try:
            if callable(stdin_writer):
                stdin_writer(stdin_stream)
            else:
                stdin_stream.write(stdin_writer)
        except BrokenPipeError:
            pass
        finally:
            with contextlib.suppress(Exception):
                stdin_stream.close()

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
                f"gpg-bridge: backend subprocess timed out after "
                f"{self._timeout_seconds}s: {partial or '<empty stderr>'}",
                file=sys.stderr,
                flush=True,
            )
            raise GpgError(
                f"gpg backend subprocess timed out after {self._timeout_seconds}s"
            ) from exc

        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)

        stdout_bytes = b"".join(stdout_parts)
        payload = _parse_payload(stdout_bytes, full_command, process.returncode)

        if "error" in payload:
            raise _error_from_payload(payload)

        if process.returncode != 0:
            raise GpgError(
                f"gpg backend exited {process.returncode} without a structured error body"
            )

        return payload


class _BoundedTail:
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


def _drain_stdout(stream: IO[bytes] | None, sink: list[bytes]) -> None:
    if stream is None:
        return
    try:
        for chunk in iter(lambda: stream.read(4096), b""):
            sink.append(chunk)
    finally:
        stream.close()


def _drain_stderr_forward_and_tail(stream: IO[bytes] | None, tail: _BoundedTail) -> None:
    if stream is None:
        return
    try:
        for chunk in iter(lambda: stream.read(4096), b""):
            text = chunk.decode("utf-8", errors="replace")
            sys.stderr.write(text)
            sys.stderr.flush()
            tail.append(text)
    finally:
        stream.close()


def _parse_payload(stdout: bytes, command: list[str], returncode: int) -> dict[str, Any]:
    if not stdout or stdout.isspace():
        raise GpgError(f"gpg backend {command[0]!r} emitted no JSON output (rc={returncode})")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise GpgError(
            f"gpg backend {command[0]!r} emitted non-JSON output (rc={returncode})"
        ) from exc
    if not isinstance(payload, dict):
        raise GpgError(
            f"gpg backend {command[0]!r} emitted non-object JSON "
            f"(rc={returncode}, got {type(payload).__name__})"
        )
    return cast(dict[str, Any], payload)


def _error_from_payload(payload: dict[str, Any]) -> GpgError:
    code = payload.get("error")
    detail = payload.get("detail") or ""
    if code == "no_such_key":
        return GpgNoSuchKeyError(detail or "key not found")
    if code == "bad_signature":
        return GpgBadSignatureError(detail or "invalid signature")
    if code == "gpg_permission_denied":
        return GpgPermissionError(detail or "permission denied")
    if code == "unsupported_operation":
        return GpgUnsupportedOperationError(detail or "unsupported operation")
    message = f"{code}: {detail}" if code and detail else detail or code or "gpg unavailable"
    return GpgError(message)


__all__ = ["GpgSubprocessClient"]
