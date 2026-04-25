# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Argv-compatible ``gpg`` substitute for bridge tests.

The bridge invokes its configured ``gpg_command`` followed by a
fixed argv shape (see :mod:`gpg_bridge.gpg_client`). This module is
that ``gpg_command`` for tests: ``python -m gpg_backend_fake
--fixtures PATH`` is the configured prefix, and the bridge appends
the gpg-style flags it would pass to a real ``gpg`` per request.

Exit codes mirror gpg's: 0 on success, 2 on bad signature / missing
key / permission denied. The fake writes the signature bytes (sign
path) or nothing (verify path) to stdout, and writes the
``[GNUPG:] …`` status block plus a free-form error line to the file
descriptor named by ``--status-fd`` (the bridge always sets ``2``).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

import yaml

from gpg_backend_fake.store import (
    BadPassphraseError,
    BadSignatureError,
    FakeKeyring,
    FakeKeyringError,
    NoSuchKeyError,
    PermissionDeniedError,
    load_fixture,
)

EXIT_OK = 0
# gpg uses 2 as its catch-all "operation failed" exit. Matching that
# keeps the bridge's stderr-pattern matching happy: it does not key
# off the exit code, only the stderr text, but a non-zero rc must
# accompany every error path.
EXIT_FAILURE = 2

_STATUS_FAILED = "[GNUPG:] FAILURE\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    fixtures_path = _pop_fixtures(args)
    if fixtures_path is None:
        sys.stderr.write("gpg_backend_fake: --fixtures PATH is required\n")
        return EXIT_FAILURE

    try:
        keyring = _load_keyring(fixtures_path)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"gpg_backend_fake: failed to load fixtures: {exc}\n")
        return EXIT_FAILURE

    parsed = _parse_gpg_argv(args)

    # ``--version`` short-circuits whatever else was passed; gpg
    # itself exits 0 with a header on stdout. The bridge does not
    # invoke ``--version`` today (the health check uses
    # ``shutil.which``), but supporting it keeps the fake behaving
    # like ``gpg`` for any future probe.
    if parsed.want_version:
        sys.stdout.write("gpg (gpg_backend_fake) 2.4.0\n")
        return EXIT_OK

    status_fd = parsed.status_fd if parsed.status_fd is not None else 2
    status_writer = _open_status_writer(status_fd)
    try:
        if parsed.operation == "sign":
            return _handle_sign(keyring, parsed, status_writer)
        if parsed.operation == "verify":
            return _handle_verify(keyring, parsed, status_writer)
        sys.stderr.write(
            "gpg_backend_fake: no operation in argv (need --detach-sign or --verify)\n"
        )
        return EXIT_FAILURE
    finally:
        status_writer.flush()
        if status_fd not in (1, 2):
            status_writer.close()


def _handle_sign(keyring: FakeKeyring, parsed: _GpgArgs, status_writer: _StatusWriter) -> int:
    if not parsed.local_user:
        sys.stderr.write("gpg_backend_fake: --local-user is required for sign\n")
        return EXIT_FAILURE
    # Read the passphrase off ``--passphrase-fd`` *before* the
    # payload — the bridge writes the passphrase first and closes
    # that pipe end, then writes the payload to stdin. Reading the
    # passphrase first matches gpg's own ordering.
    supplied_passphrase: str | None = None
    if parsed.passphrase_fd is not None:
        try:
            supplied_passphrase = _read_fd(parsed.passphrase_fd)
        except OSError as exc:
            sys.stderr.write(f"gpg_backend_fake: failed to read --passphrase-fd: {exc}\n")
            return EXIT_FAILURE
    if keyring.behaviours.record_passphrase_path and supplied_passphrase is not None:
        try:
            with open(keyring.behaviours.record_passphrase_path, "a") as fh:
                fh.write(supplied_passphrase + "\n")
        except OSError:
            # Recording is a test affordance; failure here must not
            # mask a sign result the caller will assert against.
            pass
    payload = sys.stdin.buffer.read()
    try:
        signature, status_text = keyring.sign(
            local_user=parsed.local_user,
            payload=payload,
            armor=parsed.armor,
            supplied_passphrase=supplied_passphrase,
        )
    except FakeKeyringError as exc:
        return _emit_failure(status_writer, exc)
    sys.stdout.buffer.write(signature)
    sys.stdout.buffer.flush()
    status_writer.write(status_text)
    return EXIT_OK


def _handle_verify(keyring: FakeKeyring, parsed: _GpgArgs, status_writer: _StatusWriter) -> int:
    if len(parsed.verify_files) != 2:
        sys.stderr.write(
            "gpg_backend_fake: --verify needs <sigfile> <datafile>; "
            f"got {parsed.verify_files!r}\n"
        )
        return EXIT_FAILURE
    sig_path, data_path = parsed.verify_files
    try:
        signature = _read_file(sig_path)
        payload = _read_file(data_path)
    except OSError as exc:
        sys.stderr.write(f"gpg_backend_fake: failed to read verify input: {exc}\n")
        return EXIT_FAILURE
    try:
        status_text = keyring.verify(signature=signature, payload=payload)
    except FakeKeyringError as exc:
        return _emit_failure(status_writer, exc)
    status_writer.write(status_text)
    return EXIT_OK


def _emit_failure(status_writer: _StatusWriter, exc: FakeKeyringError) -> int:
    status_writer.write(_STATUS_FAILED)
    if isinstance(exc, BadSignatureError):
        # Match gpg's BADSIG status line so the bridge's verify
        # error-classification (looking for ``BADSIG`` /
        # ``ERRSIG`` in the status block, or one of the
        # ``_BAD_SIGNATURE_PATTERNS`` strings in stderr) maps it
        # to ``GpgBadSignatureError``.
        status_writer.write("[GNUPG:] BADSIG 0000000000000000 fake\n")
        sys.stderr.write(f"gpg: BAD signature: {exc}\n")
        return EXIT_FAILURE
    if isinstance(exc, NoSuchKeyError):
        sys.stderr.write(f"gpg: skipped: No secret key: {exc}\n")
        return EXIT_FAILURE
    if isinstance(exc, PermissionDeniedError):
        sys.stderr.write(f"gpg: gpg-agent is not available: {exc}\n")
        return EXIT_FAILURE
    if isinstance(exc, BadPassphraseError):
        # Match the gpg wording the bridge's stderr classifier looks
        # for when the supplied passphrase is wrong (per ADR 0042).
        sys.stderr.write("gpg: signing failed: Bad passphrase\n")
        return EXIT_FAILURE
    sys.stderr.write(f"gpg: {exc}\n")
    return EXIT_FAILURE


def _read_file(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _read_fd(fd: int) -> str:
    """Drain a file-descriptor to EOF and return the contents as text.

    Strips a single trailing newline because the bridge writes the
    passphrase as ``passphrase + "\\n"`` and gpg itself strips the
    line terminator on read.
    """
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        chunks.append(chunk)
    os.close(fd)
    raw = b"".join(chunks).decode("utf-8", errors="replace")
    if raw.endswith("\n"):
        raw = raw[:-1]
    return raw


def _load_keyring(fixtures_path: str) -> FakeKeyring:
    with open(fixtures_path) as fh:
        data = yaml.safe_load(fh) or {}
    return load_fixture(data)


def _pop_fixtures(args: list[str]) -> str | None:
    """Remove and return the ``--fixtures`` value from ``args``."""
    for i, token in enumerate(args):
        if token == "--fixtures":
            if i + 1 >= len(args):
                return None
            value = args[i + 1]
            del args[i : i + 2]
            return value
        if token.startswith("--fixtures="):
            value = token.split("=", 1)[1]
            del args[i]
            return value
    return None


class _GpgArgs:
    """Subset of gpg argv the bridge actually emits."""

    def __init__(self) -> None:
        self.operation: str | None = None
        self.local_user: str = ""
        self.armor: bool = False
        self.status_fd: int | None = None
        self.keyid_format: str = "long"
        self.verify_files: list[str] = []
        self.want_version: bool = False
        self.passphrase_fd: int | None = None


def _parse_gpg_argv(args: list[str]) -> _GpgArgs:
    parsed = _GpgArgs()
    n = len(args)
    i = 0
    while i < n:
        token = args[i]
        if token == "--version":
            parsed.want_version = True
            i += 1
            continue
        if token == "--detach-sign":
            parsed.operation = "sign"
            i += 1
            continue
        if token == "--armor":
            parsed.armor = True
            i += 1
            continue
        if token == "--local-user":
            parsed.local_user = _next_value(args, i, "--local-user")
            i += 2
            continue
        if token.startswith("--local-user="):
            parsed.local_user = token.split("=", 1)[1]
            i += 1
            continue
        if token == "--status-fd":
            value = _next_value(args, i, "--status-fd")
            parsed.status_fd = _parse_int(value, "--status-fd")
            i += 2
            continue
        if token.startswith("--status-fd="):
            parsed.status_fd = _parse_int(token.split("=", 1)[1], "--status-fd")
            i += 1
            continue
        if token == "--keyid-format":
            parsed.keyid_format = _next_value(args, i, "--keyid-format")
            i += 2
            continue
        if token.startswith("--keyid-format="):
            parsed.keyid_format = token.split("=", 1)[1]
            i += 1
            continue
        if token == "--passphrase-fd":
            parsed.passphrase_fd = _parse_int(
                _next_value(args, i, "--passphrase-fd"), "--passphrase-fd"
            )
            i += 2
            continue
        if token.startswith("--passphrase-fd="):
            parsed.passphrase_fd = _parse_int(token.split("=", 1)[1], "--passphrase-fd")
            i += 1
            continue
        if token == "--verify":
            parsed.operation = "verify"
            # Everything after --verify is positional file path(s).
            parsed.verify_files = [a for a in args[i + 1 :] if not a.startswith("-")]
            i = n
            continue
        # Silently accept the noise flags the bridge emits but the
        # fake does not need to model: --batch, --no-tty,
        # --pinentry-mode VALUE, etc.
        if token == "--pinentry-mode":
            i += 2
            continue
        if token in ("--batch", "--no-tty"):
            i += 1
            continue
        # Discard anything else as well — a real gpg would honour
        # more flags, but the bridge only emits the set above.
        i += 1
    return parsed


def _next_value(args: list[str], index: int, flag: str) -> str:
    if index + 1 >= len(args):
        raise ValueError(f"gpg_backend_fake: {flag} requires a value")
    return args[index + 1]


def _parse_int(raw: str, flag: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"gpg_backend_fake: {flag} expected an int, got {raw!r}") from exc


class _StatusWriter:
    """Write the ``--status-fd`` block as text on the named fd."""

    def __init__(self, raw: object):
        self._raw = raw  # file-like object opened in text mode

    def write(self, text: str) -> None:
        self._raw.write(text)  # type: ignore[attr-defined]

    def flush(self) -> None:
        flush = getattr(self._raw, "flush", None)
        if callable(flush):
            flush()

    def close(self) -> None:
        close = getattr(self._raw, "close", None)
        if callable(close):
            close()


def _open_status_writer(fd: int) -> _StatusWriter:
    if fd == 1:
        return _StatusWriter(sys.stdout)
    if fd == 2:
        return _StatusWriter(sys.stderr)
    # Anything else: open the fd as a writable text stream. The
    # bridge always passes ``2`` today; this branch is for parity
    # with gpg, which honours arbitrary fds.
    return _StatusWriter(os.fdopen(fd, "w", closefd=True))


if __name__ == "__main__":
    sys.exit(main())
