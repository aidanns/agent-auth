"""CLI entrypoint for things-bridge."""

import argparse
import sys

from things_bridge.authz import AgentAuthClient
from things_bridge.config import load_config
from things_bridge.server import run_server
from things_bridge.things import AppleScriptRunner, ThingsApplescriptClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="things-bridge",
        description="HTTP bridge from agent-auth-protected clients to the Things 3 AppleScript API.",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="Start the HTTP bridge server")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    config = load_config()
    if args.command == "serve":
        runner = AppleScriptRunner(
            osascript_path=config.osascript_path, timeout=config.request_timeout_seconds,
        )
        things = ThingsApplescriptClient(runner)
        authz = AgentAuthClient(config.auth_url, timeout_seconds=config.request_timeout_seconds)
        run_server(config, things, authz)
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
