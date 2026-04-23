# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared CLI dispatcher for GPG backend CLIs.

The host backend (``gpg-backend-cli-host``) and the in-tree fake
(``tests.gpg_backend_fake``) share this module so the subprocess
contract — argv shape, stdin framing, JSON envelope — has one
implementation under test.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from gpg_backend_common.protocol import read_verify_input
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
    validate_keyid_format,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NO_SUCH_KEY = 3
EXIT_PERMISSION_DENIED = 4
EXIT_UNAVAILABLE = 5
EXIT_BAD_SIGNATURE = 6
EXIT_UNSUPPORTED = 7


class GpgBackend:
    """Protocol the backend CLIs implement and this module dispatches against."""

    def sign(self, request: SignRequest) -> SignResult:
        raise NotImplementedError

    def verify(self, request: VerifyRequest) -> VerifyResult:
        raise NotImplementedError


def build_parser(prog: str) -> argparse.ArgumentParser:
    """Build the shared argparse surface for a backend CLI."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "GPG signing backend. Reads a payload (and, for verify, a "
            "signature) off stdin and emits a JSON envelope on stdout. "
            "Invoked as a subprocess by gpg-bridge."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    sign = subparsers.add_parser("sign", help="Create a detached signature")
    sign.add_argument("--local-user", required=True, help="Key ID or fingerprint")
    sign.add_argument(
        "--armor",
        action="store_true",
        help="ASCII-armor the signature (git always wants this)",
    )
    sign.add_argument(
        "--keyid-format",
        default="long",
        help="gpg --keyid-format passthrough (short, long, 0xlong, ...)",
    )

    verify = subparsers.add_parser("verify", help="Verify a detached signature")
    verify.add_argument(
        "--keyid-format",
        default="long",
        help="gpg --keyid-format passthrough",
    )

    return parser


def run_cli(
    backend_factory: Callable[[argparse.Namespace], GpgBackend],
    parser: argparse.ArgumentParser,
    argv: list[str] | None = None,
    stdin: Any | None = None,
    stdout: Any | None = None,
) -> int:
    """Parse ``argv`` and run the requested sign / verify operation."""
    stdin_stream = stdin if stdin is not None else sys.stdin.buffer
    stdout_stream = stdout if stdout is not None else sys.stdout

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        _emit_error(stdout_stream, "unsupported_operation", "missing sub-command")
        return EXIT_UNSUPPORTED

    try:
        validate_keyid_format(args.keyid_format)
    except ValueError as exc:
        _emit_error(stdout_stream, "unsupported_operation", str(exc))
        return EXIT_USAGE

    try:
        backend = backend_factory(args)
        if args.command == "sign":
            payload = stdin_stream.read()
            if not isinstance(payload, bytes | bytearray):
                raise GpgError("sign: stdin must be bytes")
            sign_request = SignRequest(
                local_user=args.local_user,
                payload=bytes(payload),
                armor=bool(args.armor),
                status_fd_enabled=True,
                keyid_format=args.keyid_format,
            )
            sign_result = backend.sign(sign_request)
            _emit_result(stdout_stream, sign_result.to_json())
            return EXIT_OK
        if args.command == "verify":
            signature, verify_payload = read_verify_input(stdin_stream)
            verify_request = VerifyRequest(
                signature=signature,
                payload=verify_payload,
                keyid_format=args.keyid_format,
            )
            verify_result = backend.verify(verify_request)
            _emit_result(stdout_stream, verify_result.to_json())
            return EXIT_OK
    except GpgNoSuchKeyError as exc:
        _emit_error(stdout_stream, "no_such_key", str(exc))
        return EXIT_NO_SUCH_KEY
    except GpgBadSignatureError as exc:
        _emit_error(stdout_stream, "bad_signature", str(exc))
        return EXIT_BAD_SIGNATURE
    except GpgPermissionError as exc:
        _emit_error(stdout_stream, "gpg_permission_denied", str(exc))
        return EXIT_PERMISSION_DENIED
    except GpgUnsupportedOperationError as exc:
        _emit_error(stdout_stream, "unsupported_operation", str(exc))
        return EXIT_UNSUPPORTED
    except GpgError as exc:
        _emit_error(stdout_stream, "gpg_unavailable", str(exc))
        return EXIT_UNAVAILABLE

    parser.print_help(sys.stderr)
    _emit_error(stdout_stream, "unsupported_operation", f"unknown command {args.command!r}")
    return EXIT_UNSUPPORTED


def _emit_result(stdout: Any, body: dict[str, Any]) -> None:
    stdout.write(json.dumps(body))
    stdout.write("\n")
    stdout.flush()


def _emit_error(stdout: Any, code: str, detail: str) -> None:
    stdout.write(json.dumps({"error": code, "detail": detail}))
    stdout.write("\n")
    stdout.flush()


__all__ = [
    "EXIT_BAD_SIGNATURE",
    "EXIT_NO_SUCH_KEY",
    "EXIT_OK",
    "EXIT_PERMISSION_DENIED",
    "EXIT_UNAVAILABLE",
    "EXIT_UNSUPPORTED",
    "EXIT_USAGE",
    "GpgBackend",
    "build_parser",
    "run_cli",
]
