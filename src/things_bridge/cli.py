"""CLI entrypoint for things-bridge."""

import argparse
import sys

from things_bridge.authz import AgentAuthClient
from things_bridge.config import load_config
from things_bridge.fake import FakeThingsClient, FakeThingsStore, load_fake_store
from things_bridge.server import run_server
from things_bridge.things import AppleScriptRunner, ThingsApplescriptClient, ThingsClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="things-bridge",
        description="HTTP bridge from agent-auth-protected clients to the Things 3 AppleScript API.",
    )

    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="Start the HTTP bridge server")
    serve.add_argument(
        "--fake-things",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help=(
            "Serve against an in-memory fake ThingsClient instead of shelling to "
            "osascript. PATH is an optional YAML fixtures file; omit it for an "
            "empty store. Intended for Linux devcontainer / CI use — never run "
            "against real traffic."
        ),
    )

    return parser


def _print_fake_banner(path: str) -> None:
    source = path or "empty in-memory store"
    print(
        f"things-bridge: --fake-things active (NOT talking to Things 3); fixtures={source}",
        file=sys.stderr,
    )


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    config = load_config()
    if args.command == "serve":
        things: ThingsClient
        if args.fake_things is not None:
            store = load_fake_store(args.fake_things) if args.fake_things else FakeThingsStore()
            things = FakeThingsClient(store)
            _print_fake_banner(args.fake_things)
        else:
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
