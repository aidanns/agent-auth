# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI entrypoint for things-bridge."""

import argparse
import sys

from agent_auth_client import AgentAuthClient
from cli_meta import add_version_flag
from things_bridge.config import load_config
from things_bridge.server import run_server
from things_bridge.things_client import ThingsSubprocessClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="things-bridge",
        description=(
            "HTTP bridge from agent-auth-protected clients to the Things 3 API. "
            "Delegates Things interaction to a configured things-client subprocess."
        ),
    )
    add_version_flag(parser, "things-bridge")
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
        things = ThingsSubprocessClient(
            command=config.things_client_command,
            timeout_seconds=config.request_timeout_seconds,
        )
        authz = AgentAuthClient(
            config.auth_url,
            timeout_seconds=config.request_timeout_seconds,
            ca_cert_path=config.auth_ca_cert_path,
        )
        run_server(config, things, authz)
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
