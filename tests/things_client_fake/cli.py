"""CLI entrypoint for ``tests.things_client_fake``.

Reads a YAML fixture from ``--fixtures`` (or ``THINGS_CLIENT_FIXTURES``)
and answers the same read commands as
``things-client-cli-applescript``. Test-only — never shipped.
"""

import argparse
import os
import sys

from things_client_common.cli import add_read_commands, run_cli
from things_models.client import ThingsClient

from tests.things_client_fake.store import (
    FakeThingsClient,
    FakeThingsStore,
    load_fake_store,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="things-client-cli-fake",
        description=(
            "Test-only Things client backed by a YAML fixture. "
            "Invoked by things-bridge during integration/e2e tests."
        ),
    )
    parser.add_argument(
        "--fixtures",
        default=os.environ.get("THINGS_CLIENT_FIXTURES"),
        help=(
            "Path to a YAML fixture file. Omit for an empty store "
            "(or set THINGS_CLIENT_FIXTURES)."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")
    add_read_commands(subparsers)
    return parser


def _build_client(args: argparse.Namespace) -> ThingsClient:
    store = load_fake_store(args.fixtures) if args.fixtures else FakeThingsStore()
    return FakeThingsClient(store)


def main(argv: list[str] | None = None) -> int:
    return run_cli(_build_client, build_parser(), argv)


if __name__ == "__main__":
    sys.exit(main())
