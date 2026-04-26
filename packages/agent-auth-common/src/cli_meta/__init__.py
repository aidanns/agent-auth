# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared CLI metadata helpers for the agent-auth family of CLIs.

The single helper exposed here, :func:`add_version_flag`, wires an
argparse ``--version`` action onto a parser using
:func:`importlib.metadata.version` to resolve the package version at
runtime. Every package in the workspace declares
``dynamic = ["version"]`` with ``setuptools_scm`` so the installed
distribution metadata is the single source of truth — there is no
hard-coded version literal anywhere in the source tree.

The helper is consumed by every argparse-backed CLI entrypoint in the
workspace (``agent-auth``, ``agent-auth-notifier``, ``gpg-bridge``,
``things-bridge``, ``things-cli``, ``things-client-cli-applescript``).
``gpg-cli`` is a special case: it impersonates ``gpg`` for git, so its
``--version`` argv is reserved for the gpg-shaped output that git's
probe expects, and it surfaces the package's own version under a
separate ``--gpg-cli-version`` flag implemented inline.
"""

from __future__ import annotations

import argparse
from importlib.metadata import version as _dist_version


def add_version_flag(parser: argparse.ArgumentParser, dist_name: str) -> None:
    """Attach a ``--version`` action to ``parser``.

    The version string is resolved from installed distribution metadata
    via :func:`importlib.metadata.version`. The argparse default format
    (``%(prog)s <version>``) is used so the program name follows the
    parser's ``prog`` attribute without further wiring.
    """
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_dist_version(dist_name)}",
    )


__all__ = ["add_version_flag"]
