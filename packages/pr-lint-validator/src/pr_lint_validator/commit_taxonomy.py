# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Bundled snapshot of ``scripts/lint/commit_taxonomy.py`` (issue #446).

This file mirrors the canonical taxonomy module that lives at
``scripts/lint/commit_taxonomy.py`` in the agent-auth repo. The
package needs the same constants the historical script imported
(``ALLOWED_TYPES``, ``AREA_SCOPES``, ``INTERNAL_ONLY_SCOPES``,
``PACKAGE_SCOPES``) so that, when the wheel is installed in a
consumer's CI runner, the validator runs without the consumer needing
``scripts/`` on ``sys.path``.

Drift protection: ``tests/test_commit_taxonomy_in_sync.py`` imports
this module alongside the canonical script via path-spec and asserts
the three static constants (``ALLOWED_TYPES``, ``AREA_SCOPES``,
``INTERNAL_ONLY_SCOPES``) compare equal. The dynamic
``PACKAGE_SCOPES`` is intentionally divergent — see the
``discover_package_scopes`` docstring below.
"""

from __future__ import annotations

import enum
from pathlib import Path


class ReleaseImpact(enum.IntEnum):
    """SemVer bump category implied by a PR's ``type:``.

    Ordered so ``max(impacts)`` yields the largest bump — the same
    contract callers in ``version_logic`` rely on. Mirrors the
    canonical enum in ``scripts/lint/commit_taxonomy.py``; kept
    in-sync via ``tests/test_commit_taxonomy_in_sync.py``.
    """

    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3


# --- Type allowlist -----------------------------------------------------------

# Canonical PR-title prefix allowlist (ADR 0037). The keys here are the
# only values accepted by ``amannn/action-semantic-pull-request`` in
# ``.github/workflows/pr-lint.yml``; the values are the SemVer impact
# inferred when a YAML changelog entry carries that ``type:``.
#
# Order matters for the YAML self-test (the canonical module renders
# ``ALLOWED_TYPES.keys()`` in dict-iteration order); keep it
# alphabetical so the rendered list matches the ``keep-sorted`` block
# in ``pr-lint.yml``. The in-sync test compares the dicts as ordered
# mappings so an order divergence here surfaces immediately.
ALLOWED_TYPES: dict[str, ReleaseImpact] = {
    "break": ReleaseImpact.MAJOR,
    "chore": ReleaseImpact.NONE,
    "deprecation": ReleaseImpact.PATCH,
    "feature": ReleaseImpact.MINOR,
    "fix": ReleaseImpact.PATCH,
    "improvement": ReleaseImpact.PATCH,
    "migration": ReleaseImpact.PATCH,
}

# The release-bumping subset (``ALLOWED_TYPES`` minus ``chore``).
RELEASE_BUMPING_TYPES: frozenset[str] = frozenset(
    name for name, impact in ALLOWED_TYPES.items() if impact is not ReleaseImpact.NONE
)


# --- Scope allowlists ---------------------------------------------------------


def discover_package_scopes(repo_root: Path | None = None) -> tuple[str, ...]:
    """Return the sorted names of every directory under ``packages/``.

    Discovery is rooted at ``repo_root`` when provided, else at the
    current working directory. This is the principal divergence from
    the canonical ``scripts/lint/commit_taxonomy.py`` discovery, which
    walks up from ``__file__``: when the wheel runs from
    ``site-packages/``, ``__file__`` resolves outside the consumer's
    repo and the package list would always come back empty. CWD-rooted
    discovery matches how the validator is invoked on a CI runner
    (``cd $GITHUB_WORKSPACE && pr-lint-validator title ...``).

    Returns an empty tuple if ``packages/`` is missing — same fallback
    contract the canonical module uses. The CLI exposes a
    ``--repo-root`` flag so a non-standard layout can override the CWD
    default without monkey-patching.
    """
    base = repo_root if repo_root is not None else Path.cwd()
    packages_dir = base / "packages"
    if not packages_dir.is_dir():
        return ()
    return tuple(sorted(p.name for p in packages_dir.iterdir() if p.is_dir()))


# Cross-cutting concern scopes. Curated rather than discovered: these
# names refer to areas of the repo (CI, docs, design, security) rather
# than packages, and the prose definition lives in CONTRIBUTING.md
# § "Allowed scopes". Keep alphabetical so review diffs are easy to
# read; the in-sync test asserts byte-equality with the canonical
# tuple.
AREA_SCOPES: tuple[str, ...] = (
    "ci",
    "claude",
    "deps",
    "deps-dev",
    "design",
    "docs",
    "release",
    "security",
)

# Scopes that can only combine with ``chore`` / ``fix``. See the
# canonical ``scripts/lint/commit_taxonomy.py`` for the full prose
# rationale; the in-sync test asserts the two frozensets compare
# equal.
INTERNAL_ONLY_SCOPES: frozenset[str] = frozenset(
    {
        "ci",
        "claude",
        "deps-dev",
        "design",
        "docs",
        "python",
        "setup-toolchain",
        "typecheck",
        "verify-standards",
        "vscode",
    }
)


__all__ = [
    "ALLOWED_TYPES",
    "AREA_SCOPES",
    "INTERNAL_ONLY_SCOPES",
    "RELEASE_BUMPING_TYPES",
    "ReleaseImpact",
    "discover_package_scopes",
]
