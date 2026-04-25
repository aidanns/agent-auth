# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Subprocess-backed GPG client used by gpg-bridge.

The only place the bridge reasons about how to drive the host
``gpg`` binary. Per ADR 0033 (collapse-the-backend-hop amendment,
2026-04-25), the bridge invokes ``gpg`` directly rather than
delegating to a separate backend CLI; argv construction and exit-code
classification live here so the HTTP handler can stay protocol-free.
The class name is preserved across the collapse — the subprocess
under management is still a per-request subprocess, just one process
shorter than the original ADR shape.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import tempfile

from gpg_models.errors import (
    GpgBadSignatureError,
    GpgError,
    GpgNoSuchKeyError,
    GpgPermissionError,
)
from gpg_models.models import (
    SignRequest,
    SignResult,
    VerifyRequest,
    VerifyResult,
)

_DEFAULT_TIMEOUT_SECONDS = 35.0

# gpg's stderr does not return structured codes; pattern-match the
# strings the host gpg emits for the failure modes the bridge
# distinguishes. The lists are tight enough that a benign string in a
# user's commit message can't trigger them — these are gpg's own
# diagnostics, not user payload.
_NO_SECRET_KEY_PATTERNS = (
    "No secret key",
    "secret key not available",
    "skipped: No secret key",
    "No such user ID",
    "skipped: No public key",
)
_PERMISSION_PATTERNS = (
    "No pinentry",
    "Inappropriate ioctl for device",
    "gpg-agent is not available",
    "Permission denied",
)
_BAD_SIGNATURE_PATTERNS = (
    "BAD signature",
    "bad signature",
    "BADSIG",
)

# gpg status-fd field layout varies per event (SIG_CREATED has timestamp
# fields before the fingerprint; VALIDSIG has the fingerprint first).
# Match the last 40-char hex run on each status line to avoid
# hard-coding the per-event layout.
_FINGERPRINT_TOKEN = re.compile(r"\b(?P<fp>[0-9A-Fa-f]{40})\b")


class GpgSubprocessClient:
    """Per-request driver of the host ``gpg`` binary.

    The class name is unchanged from the pre-collapse shape so the
    Prometheus metric labels and the ``GpgBridgeServer`` constructor
    surface stay stable; the underlying subprocess is now ``gpg``
    itself rather than a backend CLI.
    """

    def __init__(self, command: list[str], timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS):
        if not command:
            raise ValueError("GpgSubprocessClient: command must not be empty")
        self._command = list(command)
        self._timeout_seconds = timeout_seconds

    def sign(self, request: SignRequest) -> SignResult:
        argv = [
            *self._command,
            "--batch",
            "--no-tty",
            "--pinentry-mode",
            "loopback",
            "--status-fd",
            "2",
            "--keyid-format",
            request.keyid_format,
            "--local-user",
            request.local_user,
            "--detach-sign",
        ]
        if request.armor:
            argv.append("--armor")
        stdout_bytes, stderr_text, returncode = self._invoke(argv, request.payload)
        status_text = _extract_status_lines(stderr_text)
        if returncode != 0:
            _raise_for_stderr(stderr_text, operation="sign")
            raise GpgError(f"gpg sign exited {returncode} without a recognised error")
        fingerprint = _extract_fingerprint(status_text)
        return SignResult(
            signature=stdout_bytes,
            status_text=status_text,
            exit_code=returncode,
            resolved_key_fingerprint=fingerprint,
        )

    def verify(self, request: VerifyRequest) -> VerifyResult:
        # ``gpg --verify`` reads the signature from a file path and the
        # signed payload from a second file path (or ``-`` for stdin);
        # there is no purely-stdin form for a detached verify. A
        # tempdir-per-request is the smallest shape that matches gpg's
        # own contract without leaking partial files into the user's
        # working directory.
        with tempfile.TemporaryDirectory() as workdir:
            sig_path = os.path.join(workdir, "sig")
            data_path = os.path.join(workdir, "data")
            with open(sig_path, "wb") as f:
                f.write(request.signature)
            with open(data_path, "wb") as f:
                f.write(request.payload)
            argv = [
                *self._command,
                "--batch",
                "--no-tty",
                "--status-fd",
                "2",
                "--keyid-format",
                request.keyid_format,
                "--verify",
                sig_path,
                data_path,
            ]
            _, stderr_text, returncode = self._invoke(argv, b"")

        status_text = _extract_status_lines(stderr_text)
        if returncode != 0:
            if _contains_any(stderr_text, _BAD_SIGNATURE_PATTERNS) or (
                "[GNUPG:] BADSIG" in status_text or "[GNUPG:] ERRSIG" in status_text
            ):
                raise GpgBadSignatureError("gpg reported an invalid signature")
            _raise_for_stderr(stderr_text, operation="verify")
            raise GpgError(f"gpg verify exited {returncode} without a recognised error")
        return VerifyResult(status_text=status_text, exit_code=returncode)

    def _invoke(self, argv: list[str], stdin_bytes: bytes) -> tuple[bytes, str, int]:
        try:
            completed = subprocess.run(
                argv,
                input=stdin_bytes,
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GpgError(f"gpg binary not found at {self._command[0]!r}") from exc
        except subprocess.TimeoutExpired as exc:
            with contextlib.suppress(Exception):
                if exc.stderr is not None:
                    stderr_text = bytes(exc.stderr).decode("utf-8", errors="replace")
                    if stderr_text:
                        _raise_for_stderr(stderr_text, operation=argv[-1])
            raise GpgError(f"gpg subprocess timed out after {self._timeout_seconds}s") from exc
        stderr_text = completed.stderr.decode("utf-8", errors="replace")
        return completed.stdout, stderr_text, completed.returncode


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)


def _raise_for_stderr(stderr_text: str, *, operation: str) -> None:
    if _contains_any(stderr_text, _NO_SECRET_KEY_PATTERNS):
        raise GpgNoSuchKeyError(f"gpg {operation}: requested key not in host keyring")
    if _contains_any(stderr_text, _PERMISSION_PATTERNS):
        raise GpgPermissionError(f"gpg {operation}: host keyring unreachable")


def _extract_status_lines(stderr_text: str) -> str:
    lines = [line for line in stderr_text.splitlines() if line.startswith("[GNUPG:]")]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _extract_fingerprint(status_text: str) -> str:
    wanted_prefixes = ("[GNUPG:] SIG_CREATED", "[GNUPG:] VALIDSIG", "[GNUPG:] GOODSIG")
    for line in status_text.splitlines():
        if not line.startswith(wanted_prefixes):
            continue
        match = _FINGERPRINT_TOKEN.search(line)
        if match:
            return match.group("fp").upper()
    return ""


__all__ = ["GpgSubprocessClient"]
