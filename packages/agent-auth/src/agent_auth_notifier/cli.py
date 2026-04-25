# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI entrypoint for ``agent-auth-notifier``.

Subcommands:
    terminal    Run the terminal-prompt notifier HTTP server.

The URL this server binds to is what an operator supplies as
``notification_plugin_url`` in agent-auth's config.
"""

from __future__ import annotations

import argparse
import sys

from agent_auth_notifier.terminal_server import run_terminal_notifier
from cli_meta import add_version_flag


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-auth-notifier")
    # ``agent-auth-notifier`` ships from the ``agent-auth`` distribution
    # (see ``packages/agent-auth/pyproject.toml``); resolve its version
    # against that distribution name.
    add_version_flag(parser, "agent-auth")
    sub = parser.add_subparsers(dest="command")
    terminal = sub.add_parser(
        "terminal",
        help="Serve a terminal-prompt HTTP approval notifier.",
    )
    terminal.add_argument("--host", default="127.0.0.1")
    terminal.add_argument("--port", type=int, default=9150)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    if args.command == "terminal":
        run_terminal_notifier(args.host, args.port)
        return
    parser.error(f"unknown command {args.command}")
