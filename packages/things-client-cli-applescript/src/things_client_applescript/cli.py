# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI entrypoint for ``things-client-cli-applescript``.

Reads Things 3 via ``osascript`` and prints JSON on stdout. Configured
by argv (``--osascript-path``, ``--timeout-seconds``) and the
``THINGS_CLIENT_OSASCRIPT_PATH`` / ``THINGS_CLIENT_TIMEOUT_SECONDS``
environment variables. No authentication is performed — the trust
boundary is the local user invoking it.
"""

import argparse
import os
import sys

from cli_meta import add_version_flag
from things_client_applescript.things import (
    AppleScriptRunner,
    ThingsApplescriptClient,
)
from things_client_common.cli import add_read_commands, run_cli
from things_models.client import ThingsClient

_DEFAULT_OSASCRIPT_PATH = "/usr/bin/osascript"
_DEFAULT_TIMEOUT_SECONDS = 30.0


def _env_float(name: str, fallback: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return fallback
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name}: expected a float, got {raw!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="things-client-cli-applescript",
        description=(
            "Read-only Things 3 client that shells to osascript. Emits JSON on "
            "stdout. Invoked as a subprocess by things-bridge; also runnable "
            "directly on macOS."
        ),
    )
    add_version_flag(parser, "things-client-cli-applescript")
    parser.add_argument(
        "--osascript-path",
        default=os.environ.get("THINGS_CLIENT_OSASCRIPT_PATH", _DEFAULT_OSASCRIPT_PATH),
        help=(
            "Path to the osascript binary (default: env "
            "THINGS_CLIENT_OSASCRIPT_PATH or /usr/bin/osascript)"
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=_env_float("THINGS_CLIENT_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS),
        help=(
            "Per-call osascript timeout in seconds (default: env "
            "THINGS_CLIENT_TIMEOUT_SECONDS or 30)"
        ),
    )
    subparsers = parser.add_subparsers(dest="command")
    add_read_commands(subparsers)
    return parser


def _build_client(args: argparse.Namespace) -> ThingsClient:
    runner = AppleScriptRunner(
        osascript_path=args.osascript_path,
        timeout_seconds=args.timeout_seconds,
    )
    return ThingsApplescriptClient(runner)


def main(argv: list[str] | None = None) -> int:
    return run_cli(_build_client, build_parser(), argv)


if __name__ == "__main__":
    sys.exit(main())
