# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Single source of truth for the project's PR-title taxonomy.

This module owns the canonical lists of PR-title prefixes (``ALLOWED_TYPES``),
allowed scopes (``PACKAGE_SCOPES`` / ``AREA_SCOPES``), and the
type-to-release-bump mapping consumed by the changelog tooling. Every
duplicated definition that previously lived in
``.github/workflows/pr-lint.yml`` (the ``amannn/action-semantic-pull-request``
``types:`` list), ``scripts/changelog/version_logic.py`` (the
``_BUMP_TABLE_POST_1X``), and the prose tables in CONTRIBUTING.md is now
derived from — or self-tested against — the constants here.

## Public surface

- ``ReleaseImpact`` — the SemVer bump category implied by an
  ``ALLOWED_TYPES`` entry. ``version_logic`` re-exports this as
  ``BumpType`` so callers built before #405 keep working unchanged.
- ``ALLOWED_TYPES`` — every PR-title prefix the
  ``pr-lint.yml`` workflow accepts, mapped to the SemVer impact the
  ``release-as`` workflow infers from a YAML carrying that ``type:``.
  ``chore`` maps to ``ReleaseImpact.NONE`` since chore PRs never produce
  a changelog YAML; the six release-bumping types are exposed under
  ``RELEASE_BUMPING_TYPES`` for callers that need to skip ``chore``.
- ``RELEASE_BUMPING_TYPES`` — the subset of ``ALLOWED_TYPES`` whose
  release impact is non-``NONE``. ``version_logic.EntryType`` is
  derived from this set.
- ``PACKAGE_SCOPES`` — sorted list of workspace package names, derived
  at import time from ``packages/*/`` so adding a new package never
  drifts from the lint.
- ``AREA_SCOPES`` — fixed list of cross-cutting concern scopes
  (release, ci, deps, deps-dev, docs, design, security, claude).
- ``INTERNAL_ONLY_SCOPES`` — scopes that can only combine with
  ``chore`` / ``fix``. Initial value is the empty set; #401 (the
  type x scope matrix) lands the first restriction. Defined here so
  #401 is a one-line edit rather than a fresh source of truth.

## Stability

The module is internal tooling, not a packaged surface. The constants
are stable as long as the lint and the changelog tooling import them;
renaming or shape changes require simultaneous updates to:

- ``scripts/changelog/version_logic.py`` (re-derives ``EntryType`` and
  the bump table).
- ``.github/workflows/pr-lint.yml`` (the explicit ``types:`` list, kept
  in sync via the ``pr-title-types-self-test`` job that calls
  :func:`assert_pr_lint_yaml_in_sync`).
- ``CONTRIBUTING.md`` (the prose ``Type / Release impact`` table, kept
  honest by code review against this file).
"""

from __future__ import annotations

import argparse
import enum
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class ReleaseImpact(enum.IntEnum):
    """SemVer bump category implied by a PR's ``type:``.

    Ordered so ``max(impacts)`` yields the largest bump — the same
    contract callers in ``version_logic`` rely on. ``version_logic``
    re-exports this as ``BumpType`` to keep its existing public API
    stable; new code should import ``ReleaseImpact`` directly from
    this module.
    """

    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3


# --- Type allowlist -----------------------------------------------------------

# Canonical PR-title prefix allowlist (ADR 0037). The keys here are the
# only values accepted by ``amannn/action-semantic-pull-request`` in
# ``.github/workflows/pr-lint.yml``; the values are the SemVer impact
# inferred when a YAML changelog entry carries that ``type:``. ``chore``
# maps to ``NONE`` because chore PRs do not produce a changelog YAML —
# but it is still a valid PR-title prefix, so it belongs in this dict.
#
# Order matters for the YAML self-test (we render ``ALLOWED_TYPES.keys()``
# in dict-iteration order); keep it alphabetical so the rendered list
# matches the ``keep-sorted`` block in ``pr-lint.yml``.
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
# ``version_logic.EntryType`` is built from this set — every member of
# ``EntryType`` is a valid YAML ``type:`` whose entry contributes to the
# release calculation.
RELEASE_BUMPING_TYPES: frozenset[str] = frozenset(
    name for name, impact in ALLOWED_TYPES.items() if impact is not ReleaseImpact.NONE
)


# --- Scope allowlists ---------------------------------------------------------


def _discover_package_scopes() -> tuple[str, ...]:
    """Return the sorted names of every directory under ``packages/``.

    Uses on-disk discovery so the allowlist tracks the workspace without
    a hand-maintained list. Falls back to an empty tuple if ``packages/``
    is missing — this happens only when the module is imported from a
    checkout where the workspace tree was not vendored (e.g. a release
    sdist of just the scripts).
    """
    packages_dir = _REPO_ROOT / "packages"
    if not packages_dir.is_dir():
        return ()
    return tuple(sorted(p.name for p in packages_dir.iterdir() if p.is_dir()))


PACKAGE_SCOPES: tuple[str, ...] = _discover_package_scopes()

# Cross-cutting concern scopes. Curated rather than discovered: these
# names refer to areas of the repo (CI, docs, design, security) rather
# than packages, and the prose definition lives in CONTRIBUTING.md
# § "Allowed scopes". Keep alphabetical so review diffs are easy to read.
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

# Scopes that can only combine with ``chore`` / ``fix``. Empty at the
# time #405 landed — #401 (the type x scope matrix) populates it. Defined
# here so #401 is a single-line edit and so other importers (CONTRIBUTING
# doc-drift checks, lint helpers) can refer to a stable name.
INTERNAL_ONLY_SCOPES: frozenset[str] = frozenset()


# --- pr-lint.yml self-test ----------------------------------------------------

# Path to the YAML this module is the source of truth for. Resolved
# at runtime so the self-test works in both worktree and CI checkouts.
_PR_LINT_YAML = _REPO_ROOT / ".github" / "workflows" / "pr-lint.yml"


def _extract_pr_lint_types(yaml_text: str) -> list[str]:
    """Pull the ``types:`` block from ``pr-lint.yml`` as a list of strings.

    Hand-rolled rather than using ``PyYAML`` so the self-test works on
    a vanilla Python without optional deps and so the parser narrows to
    the one block we care about (the ``with: types: |`` literal under
    the ``amannn/action-semantic-pull-request`` step). The shape we
    expect is:

        with:
          ...
          # keep-sorted start
          types: |
            break
            chore
            ...
          # keep-sorted end

    The function returns an empty list if the marker is missing — the
    caller (``assert_pr_lint_yaml_in_sync``) raises with a useful
    message in that case.
    """
    lines = yaml_text.splitlines()
    out: list[str] = []
    in_block = False
    block_indent: int | None = None
    for raw in lines:
        stripped = raw.strip()
        if not in_block:
            if stripped.startswith("types: |"):
                in_block = True
                # Indent of the *items* is the indent of `types:` plus
                # any further indentation YAML adds to a literal block.
                # We discover it from the first non-blank item line.
                block_indent = None
            continue
        # In-block: blank lines end the block.
        if not stripped:
            break
        indent = len(raw) - len(raw.lstrip())
        if block_indent is None:
            block_indent = indent
        # A line dedented past the items' indent ends the block. A
        # ``#`` comment at the same indent is tolerated (the
        # keep-sorted markers in ``pr-lint.yml`` sit alongside the
        # items).
        if indent < block_indent:
            break
        if stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


def assert_pr_lint_yaml_in_sync(yaml_path: Path | None = None) -> None:
    """Raise ``AssertionError`` if ``pr-lint.yml`` drifts from ``ALLOWED_TYPES``.

    Compares the ordered list of types declared in the workflow with
    ``list(ALLOWED_TYPES)``. The keep-sorted block in the workflow
    enforces alphabetical order, and ``ALLOWED_TYPES`` is itself written
    alphabetically, so an exact list-equality check is the right
    invariant — it catches drift in either direction (a type added to
    one place but not the other, an ordering mistake, etc.).
    """
    target = yaml_path if yaml_path is not None else _PR_LINT_YAML
    text = target.read_text(encoding="utf-8")
    actual = _extract_pr_lint_types(text)
    expected = list(ALLOWED_TYPES)
    if not actual:
        raise AssertionError(
            f"could not locate the `types: |` block in {target}; the YAML "
            "shape changed and `assert_pr_lint_yaml_in_sync` needs updating."
        )
    if actual != expected:
        raise AssertionError(
            "pr-lint.yml `types:` list drift:\n"
            f"  yaml:     {actual}\n"
            f"  expected: {expected}\n"
            "Update either `.github/workflows/pr-lint.yml` or "
            "`scripts/lint/commit_taxonomy.py::ALLOWED_TYPES` so they agree."
        )


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or self-test the canonical PR-title taxonomy. The "
            "`--check-pr-lint-yaml` mode is wired into pr-lint.yml so a "
            "drift between the YAML and ALLOWED_TYPES fails CI."
        )
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = False  # default action is `list-types`

    sub.add_parser(
        "list-types",
        help="Print every key of ALLOWED_TYPES, one per line.",
    )
    check_yaml = sub.add_parser(
        "check-pr-lint-yaml",
        help="Assert pr-lint.yml's `types:` list matches ALLOWED_TYPES.",
    )
    check_yaml.add_argument(
        "--yaml-path",
        default=None,
        help=(
            "Override the path to pr-lint.yml (defaults to "
            ".github/workflows/pr-lint.yml at the repo root)."
        ),
    )

    args = parser.parse_args(argv)
    if args.command == "check-pr-lint-yaml":
        target = Path(args.yaml_path) if args.yaml_path else None
        try:
            assert_pr_lint_yaml_in_sync(target)
        except AssertionError as err:
            print(str(err), file=sys.stderr)
            return 1
        print("commit_taxonomy: pr-lint.yml `types:` matches ALLOWED_TYPES")
        return 0

    # Default: list-types.
    for name in ALLOWED_TYPES:
        print(name)
    return 0


__all__ = [
    "ALLOWED_TYPES",
    "AREA_SCOPES",
    "INTERNAL_ONLY_SCOPES",
    "PACKAGE_SCOPES",
    "RELEASE_BUMPING_TYPES",
    "ReleaseImpact",
    "assert_pr_lint_yaml_in_sync",
]


if __name__ == "__main__":
    sys.exit(main())
