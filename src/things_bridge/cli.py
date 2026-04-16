"""CLI entrypoint for things-bridge."""

import argparse
import sys

from things_bridge.authz import AuthzClient
from things_bridge.config import load_config
from things_bridge.server import run_server
from things_bridge.things import AppleScriptRunner, ThingsClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="things-bridge",
        description="HTTP bridge from agent-auth-protected clients to the Things 3 AppleScript API.",
    )
    parser.add_argument("--config-dir", help="Override configuration directory")

    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start the HTTP bridge server")
    serve_parser.add_argument("--host", help="Bind address (default: from config)")
    serve_parser.add_argument("--port", type=int, help="Bind port (default: from config)")
    serve_parser.add_argument("--auth-url", help="agent-auth base URL (default: from config)")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    config = load_config(args.config_dir)
    if args.command == "serve":
        if args.host:
            config.host = args.host
        if args.port:
            config.port = args.port
        if args.auth_url:
            config.auth_url = args.auth_url

        runner = AppleScriptRunner(
            osascript_path=config.osascript_path, timeout=config.request_timeout_seconds,
        )
        things = ThingsClient(runner)
        authz = AuthzClient(config.auth_url, timeout=config.request_timeout_seconds)
        run_server(config, things, authz)
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
