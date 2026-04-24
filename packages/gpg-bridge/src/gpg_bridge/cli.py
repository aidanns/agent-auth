# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI entrypoint for gpg-bridge."""

from __future__ import annotations

import argparse
import sys

from gpg_bridge.authz import AgentAuthClient
from gpg_bridge.config import load_config
from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_bridge.server import run_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpg-bridge",
        description=(
            "HTTP bridge from agent-auth-protected clients to the host gpg binary. "
            "Delegates signing and verification to a configured backend subprocess."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="Start the HTTP bridge server")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    config = load_config()
    if args.command == "serve":
        gpg = GpgSubprocessClient(
            command=config.gpg_backend_command,
            timeout_seconds=config.request_timeout_seconds,
        )
        authz = AgentAuthClient(
            config.auth_url,
            timeout_seconds=config.request_timeout_seconds,
            ca_cert_path=config.auth_ca_cert_path,
        )
        run_server(config, gpg, authz)
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
