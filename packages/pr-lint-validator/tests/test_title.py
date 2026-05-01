# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for ``pr_lint_validator.title``.

The bundled inline self-test cases (``title._SELF_TEST_CASES``) are
the contract surface — every passing fixture must validate; every
failing fixture must raise ``TitleValidationError``. The test below
parametrises over the same tuple so each fixture surfaces as its own
pytest report line.
"""

from __future__ import annotations

import pytest

from pr_lint_validator import title


def _label_for(case: tuple[object, ...]) -> str:
    # ``label`` is the last positional element in each fixture tuple.
    return str(case[-1])


@pytest.mark.parametrize("case", title._SELF_TEST_CASES, ids=_label_for)
def test_title_self_test_fixture(case: tuple[object, ...]) -> None:
    """Every bundled title fixture matches its declared expect_pass.

    Catches a regression where a validator change silently flips one
    of the canonical fixtures from passing to failing (or vice
    versa). The fixtures are the public contract the cutover in #477
    will rely on, so locking them down at the unit-test layer is
    cheaper than discovering drift in the released artifact's CI run.
    """
    title_str, changed_files, package_scopes, pr_number, expect_pass, _label = case
    if expect_pass:
        title.validate(
            title_str,  # type: ignore[arg-type]
            changed_files,  # type: ignore[arg-type]
            pr_number,  # type: ignore[arg-type]
            package_scopes=package_scopes,  # type: ignore[arg-type]
        )
        return
    with pytest.raises(title.TitleValidationError):
        title.validate(
            title_str,  # type: ignore[arg-type]
            changed_files,  # type: ignore[arg-type]
            pr_number,  # type: ignore[arg-type]
            package_scopes=package_scopes,  # type: ignore[arg-type]
        )


def test_run_self_test_returns_zero_on_full_pass() -> None:
    """``run_self_test`` exits 0 when every bundled fixture matches.

    Locks down the CLI's ``--self-test`` exit-code contract. A
    regression that introduces a new fixture but forgets to keep the
    runner's pass/fail accounting in sync would silently exit 0
    while the parametrised fixture test above would still flag the
    case — pairing both checks gives the orchestrator two
    independent signals.
    """
    captured: list[str] = []

    def write(msg: str, *, error: bool = False) -> None:
        captured.append(msg)

    rc = title.run_self_test(write)
    assert rc == 0
    assert any("self-test cases passed" in line for line in captured)


def test_check_two_tier_scope_skips_when_files_empty() -> None:
    """An empty changed-file list is a no-op (e.g. metadata-only edits).

    The validator must not misfire on a PR whose diff is whitespace
    or whose file list is unavailable — those PRs already get the
    upstream prefix-allowlist check in ``pr-lint.yml``'s ``pr-title``
    job, and the two-tier rule has nothing meaningful to check.
    """
    # Empty list triggers the ``not any(...)`` early return.
    title.check_two_tier_scope("feature(agent-auth): x", [], ("agent-auth",))
    title.check_two_tier_scope("feature(agent-auth): x", [""], ("agent-auth",))


def test_check_length_handles_no_pr_number() -> None:
    """Without ``--pr-number`` the cap applies to the bare title.

    The CLI's ``--pr-number`` is optional so local invocations and
    self-test loops can run without a PR context. The error message
    must drop the "after merge-bot appends..." prose when no suffix
    is being budgeted for, otherwise the diagnostic is misleading.
    """
    over_cap = "fix: " + ("x" * 80)
    with pytest.raises(title.TitleValidationError, match="shorten the summary"):
        title.check_length(over_cap, pr_number=None)


def test_read_changed_files_drops_blank_lines(tmp_path) -> None:
    """``read_changed_files`` mirrors the workflow's gh-output shape.

    The workflow pipes ``gh pr view --json files --jq '.files[].path'``
    into a temp file; that produces trailing newlines which the
    splitlines() in ``read_changed_files`` handles, but a regression
    that switched to ``read_text().split('\\n')`` would drop or
    duplicate entries silently. Lock down the exact shape.
    """
    listing = tmp_path / "files.txt"
    listing.write_text("a\nb\n\nc\n", encoding="utf-8")
    assert title.read_changed_files(str(listing)) == ["a", "b", "", "c"]
