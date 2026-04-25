# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Argparse-free gpg argv parser and CLI entrypoint for gpg-cli.

Git invokes ``gpg`` with argv shapes that argparse cannot cleanly
handle (short-option clustering like ``-bsau KEY``, positional
filename arguments, status-fd wired to an integer file descriptor). We
hand-parse the subset git actually drives. Anything outside that
subset exits 2 with ``{"error": "unsupported_operation"}`` on stderr,
so scripts that try to use this binary as a general-purpose gpg see a
clean failure mode.

Supported argv shapes (see ADR 0030 § Supported gpg CLI surface):

- ``gpg --version``
- ``gpg [--status-fd N] [--keyid-format FMT] -bsau KEY`` (sign, stdin → stdout)
- ``gpg [--status-fd N] [--keyid-format FMT] --detach-sign --sign --armor
   --local-user KEY`` (same as above, long form)
- ``gpg [--status-fd N] [--keyid-format FMT] --verify SIGFILE -`` (verify)
- ``gpg [--status-fd N] [--keyid-format FMT] --verify SIGFILE DATAFILE``
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

from gpg_cli.client import BridgeClient
from gpg_cli.config import FileStore, load_config
from gpg_cli.errors import (
    BridgeBadSignatureError,
    BridgeForbiddenError,
    BridgeNotFoundError,
    BridgeRateLimitedError,
    BridgeUnauthorizedError,
    BridgeUnavailableError,
    ConfigMigrationRequiredError,
)
from gpg_models.models import SignRequest, VerifyRequest, validate_keyid_format

EXIT_OK = 0
EXIT_BAD_SIG = 1
EXIT_USAGE = 2
EXIT_UNAUTHORIZED = 3
EXIT_FORBIDDEN = 4
EXIT_UNAVAILABLE = 5

_VERSION_TEXT = (
    "gpg (GnuPG) 2.4.0-agent-auth-gpg-cli\n"
    "libgcrypt agent-auth compat shim\n"
    "Home: ~/.gnupg\n"
    "Supported algorithms:\n"
    "Pubkey: RSA, ELG, DSA, ECDH, ECDSA, EDDSA\n"
    "Cipher: IDEA, 3DES, CAST5, BLOWFISH, AES, AES192, AES256, TWOFISH, "
    "CAMELLIA128, CAMELLIA192, CAMELLIA256\n"
    "Hash: SHA1, RIPEMD160, SHA256, SHA384, SHA512, SHA224\n"
    "Compression: Uncompressed, ZIP, ZLIB, BZIP2\n"
)


def _empty_str_list() -> list[str]:
    return []


@dataclass
class _ParsedArgs:
    action: str = ""
    status_fd: int | None = None
    keyid_format: str = "long"
    local_user: str = ""
    armor: bool = False
    detach_sign: bool = False
    sign: bool = False
    verify: bool = False
    version: bool = False
    positional: list[str] = field(default_factory=_empty_str_list)


class UsageError(Exception):
    """Raised when the gpg-shape argv is one gpg-cli does not support."""


def _parse_argv(argv: list[str]) -> _ParsedArgs:
    """Hand-parse the subset of gpg argv the CLI supports."""
    parsed = _ParsedArgs()
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in ("--version", "--help"):
            parsed.version = token == "--version"
            if token == "--help":
                parsed.action = "help"
            i += 1
            continue
        if token == "--status-fd":
            fd_value = _next_value(argv, i)
            parsed.status_fd = _parse_fd(fd_value)
            i += 2
            continue
        if token.startswith("--status-fd="):
            parsed.status_fd = _parse_fd(token.split("=", 1)[1])
            i += 1
            continue
        if token == "--keyid-format":
            parsed.keyid_format = _next_value(argv, i)
            i += 2
            continue
        if token.startswith("--keyid-format="):
            parsed.keyid_format = token.split("=", 1)[1]
            i += 1
            continue
        if token == "--local-user" or token == "-u":
            parsed.local_user = _next_value(argv, i)
            i += 2
            continue
        if token.startswith("--local-user="):
            parsed.local_user = token.split("=", 1)[1]
            i += 1
            continue
        if token == "--armor" or token == "-a":
            parsed.armor = True
            i += 1
            continue
        if token == "--detach-sign" or token == "-b":
            parsed.detach_sign = True
            i += 1
            continue
        if token == "--sign" or token == "-s":
            parsed.sign = True
            i += 1
            continue
        if token == "--verify":
            parsed.verify = True
            i += 1
            continue
        if token.startswith("-") and not token.startswith("--") and len(token) > 1:
            # Short-option cluster like ``-bsau``. The cluster may be followed
            # by a space-separated argument for ``u`` (local-user).
            cluster = token[1:]
            if "u" in cluster and i + 1 < len(argv):
                parsed.local_user = argv[i + 1]
                consumed_extra = True
            else:
                consumed_extra = False
            for ch in cluster:
                if ch == "b":
                    parsed.detach_sign = True
                elif ch == "s":
                    parsed.sign = True
                elif ch == "a":
                    parsed.armor = True
                elif ch == "u":
                    pass
                else:
                    raise UsageError(f"gpg-cli: unsupported short option '-{ch}'")
            i += 2 if consumed_extra else 1
            continue
        if token.startswith("--"):
            raise UsageError(f"gpg-cli: unsupported long option {token!r}")
        parsed.positional.append(token)
        i += 1

    if parsed.version:
        parsed.action = "version"
    elif parsed.verify:
        parsed.action = "verify"
    elif parsed.detach_sign and parsed.sign:
        parsed.action = "sign"
    elif parsed.action == "help":
        pass
    else:
        raise UsageError(
            "gpg-cli: unsupported argv — expected --version, --verify, "
            "or a detached sign invocation (-bsau/--detach-sign --sign)"
        )
    return parsed


def _next_value(argv: list[str], idx: int) -> str:
    if idx + 1 >= len(argv):
        raise UsageError(f"gpg-cli: {argv[idx]} requires a value")
    return argv[idx + 1]


def _parse_fd(raw: str) -> int:
    try:
        fd = int(raw)
    except ValueError as exc:
        raise UsageError(f"gpg-cli: --status-fd expects an integer, got {raw!r}") from exc
    if fd < 0:
        raise UsageError(f"gpg-cli: --status-fd must be non-negative, got {fd}")
    return fd


def _write_status(parsed: _ParsedArgs, status_text: str) -> None:
    if not status_text or parsed.status_fd is None:
        return
    try:
        with os.fdopen(parsed.status_fd, "ab", closefd=False) as stream:
            stream.write(status_text.encode("utf-8"))
    except OSError as exc:
        # Status-fd write failure is non-fatal — git may have closed the fd.
        print(f"gpg-cli: status-fd write failed: {exc}", file=sys.stderr)


def _handle_version(
    stdout: Any | None = None,
) -> int:
    target = stdout if stdout is not None else sys.stdout
    target.write(_VERSION_TEXT)
    return EXIT_OK


def _load_bytes(path: str, stdin: Any) -> bytes:
    if path == "-":
        return _read_binary_stream(stdin)
    with open(path, "rb") as f:
        return f.read()


def _read_binary_stream(stream: Any) -> bytes:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        data: bytes = buffer.read()
        return data
    data = stream.read()
    return data


def _handle_sign(
    parsed: _ParsedArgs,
    client: BridgeClient,
    stdin: Any,
    stdout: Any,
) -> int:
    if not parsed.local_user:
        raise UsageError("gpg-cli: sign requires --local-user / -u <key>")
    validate_keyid_format(parsed.keyid_format)
    payload = _read_binary_stream(stdin)
    request = SignRequest(
        local_user=parsed.local_user,
        payload=payload,
        armor=parsed.armor,
        status_fd_enabled=parsed.status_fd is not None,
        keyid_format=parsed.keyid_format,
    )
    result = client.sign(request)
    _write_binary_stream(stdout, result.signature)
    _write_status(parsed, result.status_text)
    return EXIT_OK


def _handle_verify(
    parsed: _ParsedArgs,
    client: BridgeClient,
    stdin: Any,
) -> int:
    # git invokes `gpg --verify <sigfile> -` (payload on stdin) or
    # `gpg --verify <sigfile> <datafile>`. We support both.
    if not parsed.positional:
        raise UsageError("gpg-cli: --verify requires a signature file path")
    sig_path = parsed.positional[0]
    if not os.path.exists(sig_path):
        raise UsageError(f"gpg-cli: signature file {sig_path!r} not found")
    with open(sig_path, "rb") as f:
        signature = f.read()
    if len(parsed.positional) >= 2:
        payload = _load_bytes(parsed.positional[1], stdin)
    else:
        payload = _read_binary_stream(stdin)
    request = VerifyRequest(
        signature=signature,
        payload=payload,
        keyid_format=parsed.keyid_format,
    )
    try:
        result = client.verify(request)
    except BridgeBadSignatureError:
        _write_status(parsed, "[GNUPG:] BADSIG 0000000000000000 unknown\n")
        return EXIT_BAD_SIG
    _write_status(parsed, result.status_text)
    return EXIT_OK


def _write_binary_stream(stream: Any, data: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
        return
    stream.write(data)


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    try:
        parsed = _parse_argv(args)
    except UsageError as exc:
        print(f'{{"error": "unsupported_operation", "detail": "{exc}"}}', file=sys.stderr)
        return EXIT_USAGE

    if parsed.action == "version":
        return _handle_version()
    if parsed.action == "help":
        print("gpg-cli: agent-auth gpg forwarder; see ADR 0030.", file=sys.stderr)
        return EXIT_OK

    try:
        config = load_config().validated()
    except ConfigMigrationRequiredError as exc:
        # Schema-migration failures land on stderr at exit 2 with the
        # same message the loader composed; the message already names
        # ``scripts/setup-devcontainer-signing.sh`` as the recovery
        # command (see :mod:`gpg_cli.config` for the message template).
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:
        print(f"gpg-cli: {exc}", file=sys.stderr)
        return EXIT_USAGE

    store = FileStore(config.config_path)
    client = BridgeClient(
        config.credentials,
        store,
        bridge_url=config.bridge_url,
        timeout_seconds=config.timeout_seconds,
        ca_cert_path=config.ca_cert_path,
    )

    try:
        if parsed.action == "sign":
            return _handle_sign(parsed, client, sys.stdin, sys.stdout)
        if parsed.action == "verify":
            return _handle_verify(parsed, client, sys.stdin)
    except UsageError as exc:
        print(f"gpg-cli: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except BridgeUnauthorizedError as exc:
        # Reached only when refresh + reissue both failed terminally
        # (or the bridge returned a non-``token_expired`` 401). Point
        # the operator at the bootstrap script — there is no in-CLI
        # recovery path.
        print(
            f"gpg-cli: unauthorized: {exc}. Re-run "
            f"scripts/setup-devcontainer-signing.sh to bootstrap a new "
            f"credential pair.",
            file=sys.stderr,
        )
        return EXIT_UNAUTHORIZED
    except BridgeForbiddenError as exc:
        print(f"gpg-cli: forbidden: {exc}", file=sys.stderr)
        return EXIT_FORBIDDEN
    except BridgeNotFoundError as exc:
        print(f"gpg-cli: not found: {exc}", file=sys.stderr)
        return EXIT_FORBIDDEN
    except BridgeRateLimitedError as exc:
        print(
            f"gpg-cli: rate limited, retry after {exc.retry_after_seconds}s",
            file=sys.stderr,
        )
        return EXIT_UNAVAILABLE
    except BridgeUnavailableError as exc:
        print(f"gpg-cli: bridge unavailable: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE

    print("gpg-cli: unknown action", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
