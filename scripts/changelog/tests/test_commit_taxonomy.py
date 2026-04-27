# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for ``scripts/lint/commit_taxonomy``.

The module is the canonical source for the PR-title prefix allowlist
and the type-to-release-impact mapping; the tests below pin its public
contract so a regression here surfaces before downstream importers
(``version_logic``, the ``pr-lint.yml`` self-test) silently change
behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from commit_taxonomy import (
    ALLOWED_TYPES,
    AREA_SCOPES,
    INTERNAL_ONLY_SCOPES,
    PACKAGE_SCOPES,
    RELEASE_BUMPING_TYPES,
    ReleaseImpact,
    assert_pr_lint_yaml_in_sync,
)

# --- ALLOWED_TYPES ------------------------------------------------------------


def test_allowed_types_covers_every_palantir_prefix() -> None:
    """The seven Palantir-style prefixes (ADR 0037) must all be present.

    Confirms that the canonical allowlist documents every prefix the
    project accepts. ``chore`` is included even though it never produces
    a changelog YAML — it is still a valid PR-title prefix.
    """
    assert set(ALLOWED_TYPES) == {
        "break",
        "chore",
        "deprecation",
        "feature",
        "fix",
        "improvement",
        "migration",
    }


def test_allowed_types_release_impact_matches_contributing_table() -> None:
    """The bump table mirrors CONTRIBUTING.md "Type / Release impact".

    Pinning each row stops a one-sided edit (e.g. flipping
    ``improvement`` to MINOR in one place but not the other) from
    sliding past review. CONTRIBUTING.md is prose so it can't be
    asserted directly, but the table is small enough to enumerate.
    """
    assert ALLOWED_TYPES == {
        "break": ReleaseImpact.MAJOR,
        "chore": ReleaseImpact.NONE,
        "deprecation": ReleaseImpact.PATCH,
        "feature": ReleaseImpact.MINOR,
        "fix": ReleaseImpact.PATCH,
        "improvement": ReleaseImpact.PATCH,
        "migration": ReleaseImpact.PATCH,
    }


def test_allowed_types_is_alphabetical() -> None:
    """Iteration order matches the keep-sorted block in ``pr-lint.yml``.

    The YAML self-test (:func:`assert_pr_lint_yaml_in_sync`) compares
    ``list(ALLOWED_TYPES)`` against the YAML literal. Both surfaces are
    alphabetical; this test pins the Python side so the YAML
    comparison stays well-defined.
    """
    assert list(ALLOWED_TYPES) == sorted(ALLOWED_TYPES)


def test_release_bumping_types_excludes_chore() -> None:
    """The release-bumping subset is exactly ``ALLOWED_TYPES`` minus ``chore``.

    ``version_logic.EntryType`` is built from this set; if ``chore`` ever
    leaks in, the YAML schema's ``_ALLOWED_TOP_LEVEL_KEYS`` would start
    accepting a ``chore:`` nested key, which makes no sense.
    """
    assert frozenset(ALLOWED_TYPES) - {"chore"} == RELEASE_BUMPING_TYPES


# --- PACKAGE_SCOPES -----------------------------------------------------------


def test_package_scopes_match_packages_dir(repo_root: Path) -> None:
    """Each ``packages/<svc>/`` directory shows up in PACKAGE_SCOPES.

    The list is discovered at import time so a new package never drifts
    out of the lint allowlist; this test pins the discovery against the
    on-disk truth.
    """
    expected = sorted(p.name for p in (repo_root / "packages").iterdir() if p.is_dir())
    assert list(PACKAGE_SCOPES) == expected


def test_package_scopes_is_sorted() -> None:
    assert list(PACKAGE_SCOPES) == sorted(PACKAGE_SCOPES)


# --- AREA_SCOPES --------------------------------------------------------------


def test_area_scopes_match_contributing_md() -> None:
    """Pin the cross-cutting scope list against CONTRIBUTING.md § Allowed scopes.

    #402 will refine this — it'll likely add per-package interaction
    rules and may rename or extend the set. Until then, this test
    catches drive-by edits that drop one of the canonical area scopes.
    """
    assert set(AREA_SCOPES) == {
        "ci",
        "claude",
        "deps",
        "deps-dev",
        "design",
        "docs",
        "release",
        "security",
    }


# --- INTERNAL_ONLY_SCOPES -----------------------------------------------------


def test_internal_only_scopes_starts_empty() -> None:
    """#405 lands the constant; #401 lands the first restriction.

    Defining the symbol upfront with an empty default lets #401 be a
    one-line edit. This test makes the empty-by-default contract
    explicit so a casual edit doesn't sneak in a half-implemented
    restriction.
    """
    assert frozenset() == INTERNAL_ONLY_SCOPES


# --- assert_pr_lint_yaml_in_sync ---------------------------------------------


def test_pr_lint_yaml_matches_allowed_types() -> None:
    """The live ``pr-lint.yml`` is in sync with ``ALLOWED_TYPES``.

    Same assertion the ``pr-title-types-self-test`` job runs in CI;
    repeating it here catches drift on a developer machine before push.
    """
    assert_pr_lint_yaml_in_sync()


def test_assert_pr_lint_yaml_detects_drift(tmp_path: Path) -> None:
    """A fabricated YAML that omits a type triggers ``AssertionError``.

    Validates the self-check actually compares — a regression that
    silently returns ``None`` on every input would otherwise pass the
    happy-path test above.
    """
    yaml = tmp_path / "pr-lint.yml"
    yaml.write_text(
        """jobs:
  pr-title:
    steps:
      - with:
          types: |
            break
            feature
""",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="drift"):
        assert_pr_lint_yaml_in_sync(yaml)


def test_assert_pr_lint_yaml_detects_missing_block(tmp_path: Path) -> None:
    """A YAML with no ``types: |`` block is reported, not silently passed."""
    yaml = tmp_path / "pr-lint.yml"
    yaml.write_text("# nothing relevant here\njobs: {}\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="could not locate"):
        assert_pr_lint_yaml_in_sync(yaml)


# --- version_logic re-export contract ----------------------------------------


def test_version_logic_entry_type_members_match_release_bumping_types() -> None:
    """``version_logic.EntryType`` stays derived from the canonical taxonomy.

    Importers (lint, build_release, release workflow) all read
    ``EntryType`` from ``version_logic``; if it ever drifts away from
    ``RELEASE_BUMPING_TYPES`` the bump table breaks silently because
    the dict comprehension that builds ``_BUMP_TABLE_POST_1X`` skips
    members that aren't in ``ALLOWED_TYPES``.
    """
    from version_logic import EntryType

    assert {member.value for member in EntryType} == RELEASE_BUMPING_TYPES


def test_version_logic_bump_type_is_release_impact() -> None:
    """``BumpType`` is preserved as an alias for ``ReleaseImpact``.

    Existing call sites import ``BumpType`` from ``version_logic``;
    keeping the alias means #405 doesn't have to touch each of them.
    """
    from version_logic import BumpType

    assert BumpType is ReleaseImpact


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def repo_root() -> Path:
    """Path to the repo root (two parents up from this test file)."""
    return Path(__file__).resolve().parent.parent.parent.parent
