# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI entrypoint for the in-tree GPG backend fake."""

from __future__ import annotations

import argparse
import sys

import yaml

from gpg_backend_common.cli import GpgBackend, build_parser, run_cli
from gpg_models.errors import GpgError
from tests.gpg_backend_fake.store import load_fixture


def _parser() -> argparse.ArgumentParser:
    parser = build_parser(prog="gpg-backend-cli-fake")
    parser.add_argument(
        "--fixtures",
        required=True,
        help="Path to a fixture YAML file describing the fake keyring",
    )
    return parser


def _build_backend(args: argparse.Namespace) -> GpgBackend:
    try:
        with open(args.fixtures) as f:
            data = yaml.safe_load(f) or {}
    except OSError as exc:
        raise GpgError(f"fake: failed to read fixtures {args.fixtures!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise GpgError(f"fake: fixtures {args.fixtures!r} must contain a mapping")
    return load_fixture(data)


def main(argv: list[str] | None = None) -> int:
    return run_cli(_build_backend, _parser(), argv)


if __name__ == "__main__":
    sys.exit(main())
