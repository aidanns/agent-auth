#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Verify the workspace dep graph matches the allowlist in ADR 0036.

With eight workspace packages under ``packages/*/`` it is trivial to
introduce an unintended edge — e.g. ``agent-auth-common`` starting to
import from ``agent-auth`` (a reverse dep that would re-couple the
common library to the service it was extracted from), or a bridge
picking up a CLI as a runtime dependency. pyproject.toml review
alone does not catch these.

This script parses every ``packages/*/pyproject.toml``, extracts the
``[project].dependencies`` list, narrows to workspace-member names
(the ones that also appear as ``[project].name`` elsewhere in the
workspace), and asserts the resulting edge set is a subset of
``ALLOWED_EDGES``. Any unexpected edge — including reverse deps —
fails the check. Missing allowlisted edges also fail so the
allowlist can't drift out of sync with reality.

Allowed edges are maintained in
``design/decisions/0036-workspace-dep-graph-allowlist.md`` — any
addition requires an ADR update.

Usage::

    scripts/verify_workspace_deps.py [--packages-dir DIR]

``--packages-dir`` defaults to ``packages/`` under the repo root; it
is plumbed through so the self-test in
``tests/test_verify_workspace_deps.py`` can point the script at a
fixture tree containing an injected reverse-dep.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every edge in the current workspace. Ordering is (dependent,
# dependency) — so ``("agent-auth", "agent-auth-common")`` reads
# "agent-auth depends on agent-auth-common".
#
# Keep this sorted. Adding an edge requires updating ADR 0036 with
# the justification.
ALLOWED_EDGES: frozenset[tuple[str, str]] = frozenset(
    {
        ("agent-auth", "agent-auth-common"),
        ("gpg-backend-cli-host", "agent-auth-common"),
        ("gpg-bridge", "agent-auth-common"),
        ("gpg-cli", "agent-auth-common"),
        ("things-bridge", "agent-auth-common"),
        ("things-cli", "agent-auth-common"),
        ("things-client-cli-applescript", "agent-auth-common"),
    }
)

# PEP 508 package name: first segment before any version specifier,
# extra bracket, environment marker, or whitespace. ``re`` is used
# rather than ``packaging.requirements.Requirement`` so the script
# stays stdlib-only (Python 3.11 gives us ``tomllib``).
_NAME_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)")


def _dependency_name(requirement: str) -> str:
    match = _NAME_RE.match(requirement.strip())
    if match is None:
        raise ValueError(f"could not parse dependency name from {requirement!r}")
    return match.group(1)


def load_workspace(packages_dir: Path) -> dict[str, set[str]]:
    """Return a mapping of workspace-member name → declared dep names.

    Only ``[project].dependencies`` is consulted; optional extras are
    out of scope for the allowlist (they do not affect the
    production install closure).
    """
    members: dict[str, set[str]] = {}
    for pyproject in sorted(packages_dir.glob("*/pyproject.toml")):
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
        project = data.get("project", {})
        name = project.get("name")
        if not name:
            raise ValueError(f"{pyproject} has no [project].name")
        deps = {_dependency_name(dep) for dep in project.get("dependencies", [])}
        members[name] = deps
    return members


def observed_edges(members: dict[str, set[str]]) -> set[tuple[str, str]]:
    """Narrow every package's dep list to workspace-internal edges."""
    workspace_names = set(members)
    return {(name, dep) for name, deps in members.items() for dep in deps if dep in workspace_names}


def check(
    members: dict[str, set[str]],
    allowed: frozenset[tuple[str, str]] = ALLOWED_EDGES,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Return ``(unexpected, missing)`` sets of edges versus the allowlist."""
    observed = observed_edges(members)
    return observed - allowed, allowed - observed


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--packages-dir",
        type=Path,
        default=REPO_ROOT / "packages",
        help="Path to the workspace packages directory (default: packages/ under the repo root).",
    )
    args = parser.parse_args(argv)

    packages_dir: Path = args.packages_dir
    if not packages_dir.is_dir():
        print(f"verify-workspace-deps: {packages_dir} is not a directory", file=sys.stderr)
        return 2

    members = load_workspace(packages_dir)
    if not members:
        print(
            f"verify-workspace-deps: no pyproject.toml files under {packages_dir}/*/",
            file=sys.stderr,
        )
        return 2

    unexpected, missing = check(members)

    ok = True
    if unexpected:
        print(
            "verify-workspace-deps: unexpected workspace-internal edges (not in ALLOWED_EDGES):",
            file=sys.stderr,
        )
        for src, dst in sorted(unexpected):
            print(f"  - {src} -> {dst}", file=sys.stderr)
        print(
            "\n"
            "Fix: drop the dependency, OR add an ADR justifying the new edge "
            "and extend ALLOWED_EDGES in scripts/verify_workspace_deps.py.",
            file=sys.stderr,
        )
        ok = False

    if missing:
        print(
            "verify-workspace-deps: allowlisted edges not observed in pyproject.toml:",
            file=sys.stderr,
        )
        for src, dst in sorted(missing):
            print(f"  - {src} -> {dst}", file=sys.stderr)
        print(
            "\n"
            "Fix: restore the dependency, OR remove the edge from "
            "ALLOWED_EDGES (and update ADR 0036).",
            file=sys.stderr,
        )
        ok = False

    if not ok:
        return 1

    observed = observed_edges(members)
    print(
        f"verify-workspace-deps: workspace dep graph matches the ADR 0036 allowlist "
        f"({len(observed)} edges across {len(members)} members)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(_main())
