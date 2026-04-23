# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI entrypoint for ``gpg-backend-cli-host``.

Shells out to the real host ``gpg`` binary. Configured by argv flags
and the ``GPG_BACKEND_GPG_PATH`` / ``GPG_BACKEND_TIMEOUT_SECONDS``
environment variables. No authentication — the trust boundary is the
local user.
"""

from __future__ import annotations

import argparse
import os
import sys

from gpg_backend_cli_host.gpg import HostGpgBackend
from gpg_backend_common.cli import GpgBackend, build_parser, run_cli

_DEFAULT_GPG_PATH = "gpg"
_DEFAULT_TIMEOUT_SECONDS = 30.0


def _env_float(name: str, fallback: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return fallback
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name}: expected a float, got {raw!r}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = build_parser(prog="gpg-backend-cli-host")
    parser.add_argument(
        "--gpg-path",
        default=os.environ.get("GPG_BACKEND_GPG_PATH", _DEFAULT_GPG_PATH),
        help="Path to the host gpg binary (default: env GPG_BACKEND_GPG_PATH or 'gpg')",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=_env_float("GPG_BACKEND_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS),
        help="Per-call gpg subprocess timeout in seconds",
    )
    return parser


def _build_backend(args: argparse.Namespace) -> GpgBackend:
    return HostGpgBackend(
        gpg_path=args.gpg_path,
        timeout_seconds=args.timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(_build_backend, _parser(), argv)


if __name__ == "__main__":
    sys.exit(main())
