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

Per ADR 0042, the client optionally consults a
:class:`gpg_bridge.passphrase_store.KeyringPassphraseStore` on the
sign path. When a passphrase is stored for the requested
fingerprint the bridge spawns ``gpg`` with ``--passphrase-fd`` and
feeds the value through an :func:`os.pipe` — never via argv,
stdin-in-front-of-payload, or an environment variable, all of
which would put the secret on the wrong side of a process boundary
``ps``-style attackers or stderr scrubbers can observe. The
unlocked passphrase only lives in this process for the duration of
one sign call.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING

from gpg_models.errors import (
    GpgBackendUnavailableError,
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

if TYPE_CHECKING:
    from gpg_bridge.passphrase_store import KeyringPassphraseStore

# Default subprocess deadline. A wedged host gpg (typically a
# misconfigured ``gpg-agent`` blocked waiting on a non-existent
# pinentry) needs to surface as a structured
# ``signing_backend_unavailable`` HTTP response well before
# ``gpg-cli``'s own per-request HTTP deadline (default 30.0s). 10s
# leaves comfortable headroom while keeping the user-visible failure
# fast enough to feel like a directed error rather than a hang. See
# issue #331 and the fault-injection test under
# ``packages/gpg-bridge/tests/fault/``.
_DEFAULT_TIMEOUT_SECONDS = 10.0

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
# ``Bad passphrase`` covers the wrong-passphrase path explicitly;
# ``signing failed`` is the secondary diagnostic gpg emits in the
# same case. Both are included so a future gpg release that drops
# one wording (or a host-locale that translates the other) still
# routes to ``signing_backend_unavailable`` instead of falling
# through to the generic ``gpg_unavailable`` 502.
_BAD_PASSPHRASE_PATTERNS = (
    "Bad passphrase",
    "bad passphrase",
    "Invalid passphrase",
    "signing failed: Bad passphrase",
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

    def __init__(
        self,
        command: list[str],
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        passphrase_store: KeyringPassphraseStore | None = None,
    ):
        if not command:
            raise ValueError("GpgSubprocessClient: command must not be empty")
        self._command = list(command)
        self._timeout_seconds = timeout_seconds
        self._passphrase_store = passphrase_store

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
        passphrase = self._lookup_passphrase(request.local_user)
        stdout_bytes, stderr_text, returncode = self._invoke(
            argv, request.payload, passphrase=passphrase
        )
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

    def _lookup_passphrase(self, local_user: str) -> str | None:
        """Return the stored passphrase for ``local_user``, or ``None``.

        Wrapped so a configured-but-empty store cleanly degrades to
        the existing keyless / agent-cached path; a backend failure
        also degrades rather than failing the sign — the host gpg
        will produce its own diagnostic if the absent passphrase is
        actually required.
        """
        store = self._passphrase_store
        if store is None:
            return None
        try:
            return store.get(local_user)
        except Exception:
            # Per ADR 0042: a keyring-backend failure must not be the
            # exclusive failure mode for sign requests that would
            # otherwise hit the keyless / agent-cached path. Surface
            # at most the existing wedge / no-such-key signals from
            # gpg itself.
            return None

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

    def _invoke(
        self,
        argv: list[str],
        stdin_bytes: bytes,
        *,
        passphrase: str | None = None,
    ) -> tuple[bytes, str, int]:
        if passphrase is None:
            return self._invoke_simple(argv, stdin_bytes)
        return self._invoke_with_passphrase(argv, stdin_bytes, passphrase)

    def _invoke_simple(self, argv: list[str], stdin_bytes: bytes) -> tuple[bytes, str, int]:
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
            # Wedge case: gpg never emitted a recognised stderr string
            # before hanging, so the pattern map didn't fire. The
            # most common cause is a misconfigured host gpg-agent
            # (no ``allow-loopback-pinentry``, no primed passphrase
            # cache). Raise the typed error so the bridge maps it to
            # ``signing_backend_unavailable`` instead of a generic
            # ``gpg_unavailable`` 502.
            raise GpgBackendUnavailableError(
                f"gpg subprocess timed out after {self._timeout_seconds}s; "
                "host gpg-agent likely needs allow-loopback-pinentry and a "
                "primed passphrase cache"
            ) from exc
        stderr_text = completed.stderr.decode("utf-8", errors="replace")
        return completed.stdout, stderr_text, completed.returncode

    def _invoke_with_passphrase(
        self, argv: list[str], stdin_bytes: bytes, passphrase: str
    ) -> tuple[bytes, str, int]:
        """Spawn ``gpg`` with ``--passphrase-fd`` plumbed via :func:`os.pipe`.

        The passphrase reaches the child only via the ``read_fd`` end
        of an anonymous pipe; the parent retains the ``write_fd`` end
        long enough to write the bytes, then closes it. ``pass_fds``
        is the only fd-inheritance channel — every other inheritable
        fd in the parent is closed in the child by ``Popen``'s
        ``close_fds=True`` default, so the read end can never reach
        an unintended subprocess.

        The fd plumbing sits inside a ``try / finally`` so a
        ``Popen`` failure, a payload-write failure, or a timeout
        all release every fd. A leaked fd survives across requests
        in a long-running bridge process and is a real exfil risk;
        the explicit close pattern below is the contract that
        prevents it.
        """
        read_fd, write_fd = os.pipe()
        # Track which fds remain to close so the ``finally`` block
        # is idempotent and tolerant of partial setup.
        fds_to_close: dict[str, int | None] = {"read": read_fd, "write": write_fd}
        passphrase_argv = [*argv, "--passphrase-fd", str(read_fd)]

        proc: subprocess.Popen[bytes] | None = None
        try:
            try:
                proc = subprocess.Popen(
                    passphrase_argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    pass_fds=(read_fd,),
                )
            except FileNotFoundError as exc:
                raise GpgError(f"gpg binary not found at {self._command[0]!r}") from exc

            # Hand the read end to the child exclusively. Closing it in
            # the parent immediately after spawn means the child sees
            # EOF as soon as the parent closes its own write end, and
            # eliminates the chance of the parent ever reading from
            # the passphrase pipe by mistake.
            os.close(read_fd)
            fds_to_close["read"] = None

            # ``os.write`` can return short on a pipe so loop until
            # the whole passphrase has reached the kernel buffer.
            # PIPE_BUF (4096 on Linux) is comfortably larger than any
            # realistic passphrase, but the loop is the contract that
            # protects against a future change of buffer or a host
            # whose pipe sizing differs.
            payload_bytes = (passphrase + "\n").encode("utf-8")
            try:
                offset = 0
                while offset < len(payload_bytes):
                    written = os.write(write_fd, payload_bytes[offset:])
                    if written <= 0:
                        # 0 / negative is a kernel-level error on a pipe;
                        # bail out and let the child observe EOF.
                        break
                    offset += written
            finally:
                os.close(write_fd)
                fds_to_close["write"] = None

            try:
                stdout_bytes, stderr_bytes = proc.communicate(
                    input=stdin_bytes, timeout=self._timeout_seconds
                )
            except subprocess.TimeoutExpired as exc:
                _terminate_process(proc)
                stderr_text = ""
                if exc.stderr is not None:
                    stderr_text = bytes(exc.stderr).decode("utf-8", errors="replace")
                if stderr_text:
                    with contextlib.suppress(Exception):
                        _raise_for_stderr(stderr_text, operation=argv[-1])
                raise GpgBackendUnavailableError(
                    f"gpg subprocess timed out after {self._timeout_seconds}s; "
                    "host gpg-agent likely needs allow-loopback-pinentry and a "
                    "primed passphrase cache"
                ) from exc
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            return stdout_bytes, stderr_text, proc.returncode
        finally:
            for handle in ("read", "write"):
                fd = fds_to_close[handle]
                if fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(fd)
            if proc is not None and proc.poll() is None:
                _terminate_process(proc)


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)


def _raise_for_stderr(stderr_text: str, *, operation: str) -> None:
    if _contains_any(stderr_text, _NO_SECRET_KEY_PATTERNS):
        raise GpgNoSuchKeyError(f"gpg {operation}: requested key not in host keyring")
    if _contains_any(stderr_text, _BAD_PASSPHRASE_PATTERNS):
        # Wrong passphrase is a backend-side failure the bridge wants
        # to expose with a directed error code (per ADR 0042). Reusing
        # ``GpgBackendUnavailableError`` keeps the public wire surface
        # at the existing ``signing_backend_unavailable`` discriminator
        # — the structured detail string is intentionally generic so
        # the bridge does not leak whether a stored passphrase was
        # involved (a useful signal to an attacker probing the
        # store's presence).
        raise GpgBackendUnavailableError(
            f"gpg {operation}: signing failed; host gpg rejected the supplied passphrase"
        )
    if _contains_any(stderr_text, _PERMISSION_PATTERNS):
        raise GpgPermissionError(f"gpg {operation}: host keyring unreachable")


def _terminate_process(proc: subprocess.Popen[bytes]) -> None:
    """Best-effort terminate a child process with a short escalation window.

    SIGTERM first, brief wait, then SIGKILL. The ``communicate`` call
    that drives the timeout already harvests the child's pipes; this
    helper only ensures the process descriptor itself is reaped so
    the OS does not accumulate zombies on the long-running bridge.
    """
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    with contextlib.suppress(Exception):
        proc.wait(timeout=1.0)


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
