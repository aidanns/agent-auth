# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for ``scripts/changelog/build_release.py``.

Public-API only — every test exercises ``compute_release``,
``apply_release``, ``render_changelog_section``,
``render_release_notes``, ``render_commit_msg_block``, or
``render_pr_body``. The module is the version-inference glue between
the YAML schema and the release-PR / release-tag workflows; a
regression here changes the published release notes.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from build_release import (
    SECTION_HEADINGS,
    SECTION_ORDER,
    apply_release,
    compute_release,
    render_changelog_section,
    render_commit_msg_block,
    render_pr_body,
    render_release_notes,
)
from build_release import (
    main as build_release_main,
)
from version_logic import ChangelogValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_unreleased(repo: Path, name: str, body: str) -> Path:
    path = repo / "changelog" / "@unreleased" / name
    _write(path, body)
    return path


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A minimal repo layout with the directories the planner walks."""
    (tmp_path / "changelog" / "@unreleased").mkdir(parents=True)
    return tmp_path


# --- compute_release ---------------------------------------------------------


def test_compute_release_returns_none_when_no_entries(repo: Path) -> None:
    assert compute_release(repo, "0.4.0") is None


def test_compute_release_single_feature_minor_bumps_on_zero_x(repo: Path) -> None:
    _seed_unreleased(
        repo,
        "pr-100-x.yml",
        "type: feature\nfeature:\n  description: New thing.\n",
    )
    plan = compute_release(repo, "0.4.0", today=_dt.date(2026, 4, 25))
    assert plan is not None
    assert plan.next_version == "0.5.0"
    assert plan.current_version == "0.4.0"
    assert len(plan.entries) == 1
    assert len(plan.moves) == 1
    assert plan.moves[0].dst == Path("changelog/0.5.0/pr-100-x.yml")
    assert "## [0.5.0] - 2026-04-25" in plan.changelog_section
    assert "Features" in plan.changelog_section
    assert "Release v0.5.0." in plan.release_notes


def test_compute_release_single_break_minor_on_zero_x(repo: Path) -> None:
    _seed_unreleased(
        repo,
        "pr-100-x.yml",
        "type: break\nbreak:\n  description: Drops /v0.\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    assert plan.next_version == "0.5.0"  # demoted from major


def test_compute_release_single_break_major_on_one_x(repo: Path) -> None:
    _seed_unreleased(
        repo,
        "pr-100-x.yml",
        "type: break\nbreak:\n  description: Drops /v0.\n",
    )
    plan = compute_release(repo, "1.2.3")
    assert plan is not None
    assert plan.next_version == "2.0.0"


def test_compute_release_honours_release_as_override(repo: Path) -> None:
    _seed_unreleased(
        repo,
        "pr-100-graduate.yml",
        ("type: feature\n" "feature:\n" "  description: Graduate to 1.0.\n" "release-as: 1.0.0\n"),
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    assert plan.next_version == "1.0.0"
    assert "## [1.0.0]" in plan.changelog_section


def test_compute_release_rejects_release_as_below_inferred(repo: Path) -> None:
    _seed_unreleased(
        repo,
        "pr-100-x.yml",
        ("type: feature\n" "feature:\n" "  description: Bump.\n" "release-as: 0.4.3\n"),
    )
    # Inferred from the FEATURE bump on 0.4.0 would be 0.5.0; 0.4.3 < 0.5.0.
    with pytest.raises(ChangelogValidationError):
        compute_release(repo, "0.4.0")


def test_compute_release_rejects_conflicting_release_as(repo: Path) -> None:
    _seed_unreleased(
        repo,
        "pr-100-a.yml",
        ("type: feature\n" "feature:\n" "  description: A.\n" "release-as: 1.0.0\n"),
    )
    _seed_unreleased(
        repo,
        "pr-100-b.yml",
        ("type: fix\n" "fix:\n" "  description: B.\n" "release-as: 2.0.0\n"),
    )
    with pytest.raises(ChangelogValidationError):
        compute_release(repo, "0.4.0")


def test_compute_release_picks_largest_bump(repo: Path) -> None:
    _seed_unreleased(
        repo,
        "pr-100-fix.yml",
        "type: fix\nfix:\n  description: A bug fix.\n",
    )
    _seed_unreleased(
        repo,
        "pr-101-feature.yml",
        "type: feature\nfeature:\n  description: A new thing.\n",
    )
    plan = compute_release(repo, "0.4.2")
    assert plan is not None
    assert plan.next_version == "0.5.0"
    assert len(plan.moves) == 2


# --- render_changelog_section -----------------------------------------------


def test_render_changelog_section_groups_by_section_order():
    """Entries render in SECTION_ORDER regardless of input order."""
    from version_logic import ChangelogEntry, EntryType

    entries = [
        ChangelogEntry(
            entry_type=EntryType.FIX,
            description="Fix it.",
            links=(),
            packages=None,
            release_as=None,
            source_path=Path("changelog/@unreleased/pr-1-fix.yml"),
        ),
        ChangelogEntry(
            entry_type=EntryType.BREAK,
            description="Break it.",
            links=(),
            packages=None,
            release_as=None,
            source_path=Path("changelog/@unreleased/pr-2-break.yml"),
        ),
        ChangelogEntry(
            entry_type=EntryType.FEATURE,
            description="Add it.",
            links=(),
            packages=None,
            release_as=None,
            source_path=Path("changelog/@unreleased/pr-3-feat.yml"),
        ),
    ]
    section = render_changelog_section(entries, "1.0.0", _dt.date(2026, 4, 25))
    # Heading order matches SECTION_ORDER (BREAK before FEATURE before FIX).
    break_idx = section.index(SECTION_HEADINGS[EntryType.BREAK])
    feature_idx = section.index(SECTION_HEADINGS[EntryType.FEATURE])
    fix_idx = section.index(SECTION_HEADINGS[EntryType.FIX])
    assert break_idx < feature_idx < fix_idx
    assert section.startswith("## [1.0.0] - 2026-04-25")


def test_render_changelog_section_omits_empty_groups():
    from version_logic import ChangelogEntry, EntryType

    entries = [
        ChangelogEntry(
            entry_type=EntryType.FIX,
            description="Fix it.",
            links=(),
            packages=None,
            release_as=None,
            source_path=Path("changelog/@unreleased/pr-1-fix.yml"),
        ),
    ]
    section = render_changelog_section(entries, "0.4.3", _dt.date(2026, 4, 25))
    assert SECTION_HEADINGS[EntryType.FIX] in section
    assert SECTION_HEADINGS[EntryType.FEATURE] not in section
    assert SECTION_HEADINGS[EntryType.BREAK] not in section


# --- render_commit_msg_block satisfies the PR-body validator ----------------


def _load_commit_msg_validator():
    """Import scripts/validate-commit-msg-block.py as a module.

    The script's filename has a hyphen so a normal `import` would fail —
    use importlib to load it under a plain module name for the test.
    """
    path = REPO_ROOT / "scripts" / "validate-commit-msg-block.py"
    spec = importlib.util.spec_from_file_location("validate_commit_msg_block", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_commit_msg_block"] = module
    spec.loader.exec_module(module)
    return module


def test_render_pr_body_passes_validate_commit_msg_block(repo: Path) -> None:
    """The auto-generated PR body must survive the PR-body lint."""
    _seed_unreleased(
        repo,
        "pr-100-feat.yml",
        ("type: feature\n" "feature:\n" "  description: A wonderful new behaviour for users.\n"),
    )
    _seed_unreleased(
        repo,
        "pr-101-fix.yml",
        "type: fix\nfix:\n  description: A small but important fix.\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    body = render_pr_body(plan)

    validator = _load_commit_msg_validator()
    # Should not raise.
    validator.validate(body)


def test_render_commit_msg_block_keeps_lines_under_72(repo: Path) -> None:
    """Long YAML descriptions must still wrap so the validator passes."""
    long_desc = "This is a long description " * 12  # > 72 chars
    _seed_unreleased(
        repo,
        "pr-100-feat.yml",
        f"type: feature\nfeature:\n  description: {long_desc.strip()}\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    block = render_commit_msg_block(plan.entries, plan.next_version)
    for line in block.splitlines():
        assert len(line) <= 72, f"line too wide: {line!r}"


# --- bullet shape (#397) ----------------------------------------------------
#
# The ==COMMIT_MSG== block historically joined entries with `; ` into
# a single prose paragraph per section heading. That shape was hard
# to scan once a release accumulated several entries, and the
# inconsistency between single-entry sections (one prose sentence)
# and multi-entry sections (semicolon-joined run-on) was the worst
# of it. #397 switched the renderer to always emit a bulleted list
# under each section heading, regardless of entry count.
#
# These tests pin the user-visible shape: bullets are present, the
# semicolon-joined run-on is absent, and the same shape applies to
# single-entry sections as to multi-entry ones.


def test_render_commit_msg_block_emits_bullet_per_entry_in_multi_entry_section(
    repo: Path,
) -> None:
    """Multi-entry sections render one ``- `` bullet per entry, not ``; ``."""
    _seed_unreleased(
        repo,
        "pr-100-imp-a.yml",
        "type: improvement\nimprovement:\n  description: First improvement.\n",
    )
    _seed_unreleased(
        repo,
        "pr-101-imp-b.yml",
        "type: improvement\nimprovement:\n  description: Second improvement.\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    block = render_commit_msg_block(plan.entries, plan.next_version)

    # Each bullet ends with the per-entry `(#N)` PR-link suffix (#411)
    # taken from the YAML filename — no trailing period, matching the
    # changelog and release-notes renderers.
    assert "Improvements:\n- First improvement (#100)\n- Second improvement (#101)" in block
    # The historical semicolon-joined run-on must not reappear.
    assert "; " not in block


def test_render_commit_msg_block_emits_bullet_for_single_entry_section(
    repo: Path,
) -> None:
    """Single-entry sections render the same bullet shape as multi-entry."""
    _seed_unreleased(
        repo,
        "pr-100-fix.yml",
        "type: fix\nfix:\n  description: Only fix.\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    block = render_commit_msg_block(plan.entries, plan.next_version)

    # Single-entry sections render the same bullet shape, including
    # the per-entry `(#N)` PR-link suffix (#411).
    assert block == "Fixes:\n- Only fix (#100)"


# --- numbered-reference wrap regressions ------------------------------------
#
# Greedy wrap on 72 chars used to land tokens like `0011.` (from
# `ADR 0011.`) at line start when the noun and the digits straddled
# the wrap point — see issue #357 and the broken
# `chore(release): 0.14.0` PR. Pre-#345 this was a hard validator
# failure (the `numbered list item` rule rejected any block line
# matching `^\s*\d+[.)]\s+\S`); post-#345 the validator no longer
# bans those, but a wrapped numeric-reference opener still reads
# as a list bullet at a glance and the renderer's `_wrap_paragraph`
# keeps such tokens off the start of a wrapped line by moving the
# preceding token down with them.
#
# Tests exercise `render_commit_msg_block` (public API, per
# testing-standards.md) rather than reaching into `_wrap_paragraph`
# directly: the readability invariant only matters at the rendered
# surface, and render-then-check is the contract a regression
# would break.


_NUMBERED_REFERENCE_LINE_RE = re.compile(r"^\s*\d+[.)]\s+\S")


def _assert_block_satisfies_validator(block: str) -> None:
    """Assert no line opens like a numbered list AND every line wraps at 72.

    The 72-char rule is enforced by ``validate-commit-msg-block.py``.
    The "no numbered-reference opener" rule used to be too (the
    pre-#345 ``numbered list item`` predicate); post-#345 it is a
    readability invariant the renderer keeps voluntarily — a
    wrapped numeric reference at line start reads as a list
    bullet at a glance and confuses the eye. The renderer must
    satisfy both simultaneously: an early version of the fix
    glued the numeric token to the previous one but pushed the line
    past 72 chars, trading one regression for another. This
    helper guards against that.
    """
    numbered = [
        (idx, line)
        for idx, line in enumerate(block.splitlines(), start=1)
        if _NUMBERED_REFERENCE_LINE_RE.match(line)
    ]
    assert not numbered, "wrapped numeric reference at line start: " + ", ".join(
        f"line {idx}: {line!r}" for idx, line in numbered
    )
    too_wide = [
        (idx, line) for idx, line in enumerate(block.splitlines(), start=1) if len(line) > 72
    ]
    assert not too_wide, "block line over 72 chars: " + ", ".join(
        f"line {idx} ({len(line)} chars): {line!r}" for idx, line in too_wide
    )


def test_render_commit_msg_block_does_not_wrap_before_adr_number(repo: Path) -> None:
    """`ADR 0011.` must never end up split across a soft wrap point.

    Reproduces issue #357: the source prose mirrors the wording from
    PR #355 that broke the `==COMMIT_MSG==` lint, with enough prefix
    text to push the `0011.` token onto a wrap boundary at width 72.
    """
    # Crafted so the buggy greedy wrapper would land `0011.` at the
    # start of the second line: `Features: ` + the prose below packs
    # exactly to 72 chars at `… from ADR`, leaving the `0011.` token
    # (digits + period) to overflow onto the next line — exactly the
    # failure mode from PR #355's `chore(release): 0.14.0` body.
    description = (
        "Switch back to the single-use refresh contract design "
        "from ADR 0011. Then verify the rebuilt wrap."
    )
    _seed_unreleased(
        repo,
        "pr-100-feat.yml",
        f"type: feature\nfeature:\n  description: {description}\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    block = render_commit_msg_block(plan.entries, plan.next_version)
    _assert_block_satisfies_validator(block)


def test_render_commit_msg_block_does_not_wrap_before_close_paren_number(
    repo: Path,
) -> None:
    """`issue 1234)` must not split with `1234)` opening a wrapped line.

    Same failure mode as the `<digits>.` case but for the close-paren
    variant rejected by the same validator rule.
    """
    # Crafted so `Fixes: ` + the prose below ends the first line at
    # `… in (issue` (68 chars), leaving the buggy wrapper to drop
    # `1234)` onto the next line — i.e. `1234) and verify the …`.
    description = (
        "Restore the long-standing renderer regression noted in "
        "(issue 1234) and verify the rebuilt wrap."
    )
    _seed_unreleased(
        repo,
        "pr-100-fix.yml",
        f"type: fix\nfix:\n  description: {description}\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    block = render_commit_msg_block(plan.entries, plan.next_version)
    _assert_block_satisfies_validator(block)


def test_render_commit_msg_block_wraps_normally_around_hyphen_joined_id(
    repo: Path,
) -> None:
    """Hyphen-joined identifiers like `CVE-2024-12345` must wrap normally.

    The fix targets `\\d+[.)]` tokens specifically. A token containing
    digits but joined with hyphens does not match `NUMERIC_PERIOD_RE`,
    so the standard greedy wrap should apply and the resulting lines
    must still satisfy the 72-char width and numbered-list rules.
    """
    description = (
        "Mitigate the upstream advisory tracked as CVE-2024-12345 by "
        "pinning the affected dependency and adding a regression test."
    )
    _seed_unreleased(
        repo,
        "pr-100-fix.yml",
        f"type: fix\nfix:\n  description: {description}\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    block = render_commit_msg_block(plan.entries, plan.next_version)
    _assert_block_satisfies_validator(block)
    # Sanity: the identifier survives unbroken — it must not be split
    # across a wrap point either (the existing URL-preservation rule).
    assert "CVE-2024-12345" in block


# --- PR-link suffix (#411) --------------------------------------------------
#
# The audience-link-back convention: every rendered release-note entry
# carries a trailing `(#N)` that GitHub auto-renders to a clickable PR
# link, restoring the path to the verbose context that the terse
# `description:` field deliberately omits (#407). The PR number is
# derived from the YAML filename, not the human-authored `links:`
# field. Tests exercise the public renderer surfaces — a regression
# would change the bytes published to CHANGELOG.md, the GitHub
# release body, or the release-PR `==COMMIT_MSG==` block.


def test_render_changelog_section_appends_pr_link_suffix(repo: Path) -> None:
    """A CHANGELOG.md bullet ends with `(#NNN)` taken from the YAML filename."""
    _seed_unreleased(
        repo,
        "pr-411-example.yml",
        "type: improvement\nimprovement:\n  description: A short user-facing fix.\n",
    )
    plan = compute_release(repo, "0.4.0", today=_dt.date(2026, 4, 27))
    assert plan is not None
    bullet_lines = [line for line in plan.changelog_section.splitlines() if line.startswith("- ")]
    assert bullet_lines, "expected at least one bullet in the rendered section"
    assert bullet_lines[0].endswith(" (#411)")


def test_render_release_notes_appends_pr_link_suffix(repo: Path) -> None:
    """The shared GitHub-release body inherits the same `(#N)` suffix."""
    _seed_unreleased(
        repo,
        "pr-411-example.yml",
        "type: improvement\nimprovement:\n  description: A short user-facing fix.\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    bullet_lines = [line for line in plan.release_notes.splitlines() if line.startswith("- ")]
    assert bullet_lines and bullet_lines[0].endswith(" (#411)")


def test_render_commit_msg_block_appends_pr_link_suffix_per_entry(repo: Path) -> None:
    """Each bullet under a section heading keeps its own `(#N)` suffix."""
    _seed_unreleased(
        repo,
        "pr-411-a.yml",
        "type: improvement\nimprovement:\n  description: First short improvement.\n",
    )
    _seed_unreleased(
        repo,
        "pr-412-b.yml",
        "type: improvement\nimprovement:\n  description: Second short improvement.\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    block = render_commit_msg_block(plan.entries, plan.next_version)
    assert "(#411)" in block
    assert "(#412)" in block
    # Each bullet line under the Improvements heading must carry its
    # own suffix at the visible end of the entry — the eye should find
    # the link where the bullet finishes, not orphaned on a wrap line.
    improvements_section = next(
        para for para in block.split("\n\n") if para.startswith("Improvements:")
    )
    bullet_lines = [line for line in improvements_section.splitlines() if line.startswith("- ")]
    assert any(line.endswith(" (#411)") for line in bullet_lines)
    assert any(line.endswith(" (#412)") for line in bullet_lines)


def test_render_commit_msg_block_does_not_wrap_before_pr_link_suffix(
    repo: Path,
) -> None:
    """A long-bullet description must keep `(#N)` bound to the preceding token.

    Reproduces the wrap-boundary failure mode the issue calls out: a
    description long enough that a naive greedy wrapper would drop
    ``(#411)`` alone onto a wrapped line. The suffix being visually
    divorced from the entry it links to defeats the audience-link-back
    motive (#411). The fixture's prose is sized so the buggy wrapper
    would land the suffix on its own wrapped line under the Improvements
    bullet; the fix moves the preceding token down with it.

    Sanity-checked against an unbound wrapper: monkey-patching
    ``PR_SUFFIX_RE`` to never match yields a wrapped line opening with
    ``(#411)``, which is exactly the failure mode the assertions
    here forbid. The fixture would not detect a missing suffix-binding
    branch otherwise.
    """
    # Crafted so the bullet body's wrap leaves ``(#411)`` orphaned on
    # its own line under the unbound wrapper: the prose fills the
    # second wrapped continuation line right up to the 70-char bullet
    # width, so the 7-char suffix overflows and lands on a third line
    # with nothing else next to it.
    description = (
        "Auto-update a PR whose head sits behind main instead of "
        "treating the merge API's 405 as a hard failure mode that "
        "we previously skipped over"
    )
    _seed_unreleased(
        repo,
        "pr-411-merge-bot.yml",
        f"type: improvement\nimprovement:\n  description: {description}.\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    block = render_commit_msg_block(plan.entries, plan.next_version)
    _assert_block_satisfies_validator(block)
    # No wrapped line opens with `(#NNN)` (alone or with trailing
    # punctuation): the suffix must always sit after a token from the
    # entry's prose, never at line start.
    pr_suffix_opener = re.compile(r"^\s*\(#\d+\)")
    offenders = [line for line in block.splitlines() if pr_suffix_opener.match(line)]
    assert not offenders, "PR-link suffix orphaned at line start: " + repr(offenders)
    # And the suffix must still appear in the rendered block.
    assert "(#411)" in block


def test_pr_link_suffix_binding_fixture_actually_exercises_binding_rule(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Meta-guard: the long-description fixture must depend on the binding rule.

    Earlier wording of the long-description regression test happened
    to wrap such that ``(#411).`` already fit on the second line by
    accident — monkey-patching ``PR_SUFFIX_RE`` produced byte-identical
    output, so the test passed even with the suffix-binding branch of
    ``_wrap_paragraph`` removed. This meta-test pins the fixture sized
    so disabling ``PR_SUFFIX_RE`` orphans ``(#NNN)`` at the start of a
    wrapped line, restoring the regression test's teeth. If a future
    edit shortens the prose below the threshold this assertion will
    fail loudly rather than the regression test silently degrading
    into a smoke test.
    """
    import build_release

    description = (
        "Auto-update a PR whose head sits behind main instead of "
        "treating the merge API's 405 as a hard failure mode that "
        "we previously skipped over"
    )
    _seed_unreleased(
        repo,
        "pr-411-merge-bot.yml",
        f"type: improvement\nimprovement:\n  description: {description}.\n",
    )
    plan = compute_release(repo, "0.4.0")
    assert plan is not None
    # Disable the suffix-binding rule and confirm the resulting block
    # *would* orphan `(#411)` at line start — proving the fixture
    # actually depends on the binding logic for its assertions.
    monkeypatch.setattr(build_release, "PR_SUFFIX_RE", re.compile("a^"))
    unbound_block = render_commit_msg_block(plan.entries, plan.next_version)
    pr_suffix_opener = re.compile(r"^\s*\(#\d+\)")
    unbound_offenders = [
        line for line in unbound_block.splitlines() if pr_suffix_opener.match(line)
    ]
    assert unbound_offenders, (
        "Long-description fixture no longer exercises the PR_SUFFIX_RE "
        "binding rule — disabling the regex still produced bound output. "
        "Adjust the fixture so the unbound wrapper would orphan `(#NNN)` "
        "at line start, otherwise "
        "test_render_commit_msg_block_does_not_wrap_before_pr_link_suffix "
        "is a smoke test rather than a regression guard."
    )


def test_render_changelog_bullet_skips_suffix_when_filename_unconventional() -> None:
    """Fail-soft: an entry whose filename doesn't match the pattern gets no suffix.

    The PR-time lint (`check_present_file_naming`) blocks new
    offenders, but the renderer must still degrade gracefully if a
    legacy or hand-edited file slips through — better to drop the
    link than crash on a release-PR that's already past CI.
    """
    from version_logic import ChangelogEntry, EntryType

    entries = [
        ChangelogEntry(
            entry_type=EntryType.IMPROVEMENT,
            description="A change without a conventional filename.",
            links=(),
            packages=None,
            release_as=None,
            source_path=Path("changelog/@unreleased/legacy-handauthored.yml"),
        ),
    ]
    section = render_changelog_section(entries, "0.5.0", _dt.date(2026, 4, 27))
    assert "A change without a conventional filename." in section
    # No `(#…)` suffix anywhere (no PR number to derive).
    assert "(#" not in section


# --- render_release_notes ---------------------------------------------------


def test_render_release_notes_includes_version_header():
    from version_logic import ChangelogEntry, EntryType

    entries = [
        ChangelogEntry(
            entry_type=EntryType.FEATURE,
            description="A new thing.",
            links=(),
            packages=None,
            release_as=None,
            source_path=Path("changelog/@unreleased/pr-1-x.yml"),
        ),
    ]
    notes = render_release_notes(entries, "0.5.0")
    assert notes.startswith("Release v0.5.0.")
    assert "Features" in notes
    assert "A new thing." in notes


# --- apply_release ----------------------------------------------------------


def test_apply_release_moves_files_and_rewrites_changelog(repo: Path) -> None:
    src = _seed_unreleased(
        repo,
        "pr-100-feat.yml",
        "type: feature\nfeature:\n  description: New thing.\n",
    )
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.4.0] - 2026-04-01\n\n- previous\n",
        encoding="utf-8",
    )
    plan = compute_release(repo, "0.4.0", today=_dt.date(2026, 4, 25))
    assert plan is not None

    apply_release(plan, repo)

    # Source moved.
    assert not src.exists()
    assert (repo / "changelog" / "0.5.0" / "pr-100-feat.yml").exists()

    # CHANGELOG rewritten with new section above old.
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.5.0] - 2026-04-25" in text
    assert text.index("## [0.5.0]") < text.index("## [0.4.0]")
    assert "previous" in text


def test_apply_release_idempotent_on_re_run(repo: Path) -> None:
    """Re-applying the same plan after success leaves identical state."""
    _seed_unreleased(
        repo,
        "pr-100-feat.yml",
        "type: feature\nfeature:\n  description: New thing.\n",
    )
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.4.0] - 2026-04-01\n\n- previous\n",
        encoding="utf-8",
    )
    plan = compute_release(repo, "0.4.0", today=_dt.date(2026, 4, 25))
    assert plan is not None

    apply_release(plan, repo)
    first_changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")

    # Re-run with the same plan. The moves should no-op (sources gone),
    # and the CHANGELOG section already exists, so the rewrite drops
    # and replaces in place.
    apply_release(plan, repo)
    second_changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")

    assert first_changelog == second_changelog


def test_apply_release_creates_changelog_when_absent(repo: Path) -> None:
    _seed_unreleased(
        repo,
        "pr-100-feat.yml",
        "type: feature\nfeature:\n  description: New thing.\n",
    )
    plan = compute_release(repo, "0.0.0", today=_dt.date(2026, 4, 25))
    assert plan is not None

    apply_release(plan, repo)

    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.startswith("# Changelog")
    assert "## [0.1.0] - 2026-04-25" in text


# --- CLI --------------------------------------------------------------------


def test_cli_compute_emits_skip_when_empty(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = build_release_main(["compute", "--repo-root", str(repo), "--current-version", "0.4.0"])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload == {"skip": True, "reason": "no unreleased entries"}


def test_cli_compute_emits_plan(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_unreleased(
        repo,
        "pr-100-feat.yml",
        "type: feature\nfeature:\n  description: New thing.\n",
    )
    rc = build_release_main(["compute", "--repo-root", str(repo), "--current-version", "0.4.0"])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["next_version"] == "0.5.0"
    assert payload["branch"] == "release/0.5.0"
    assert payload["title"] == "chore(release): 0.5.0"
    assert "==COMMIT_MSG==" in payload["pr_body"]


def test_cli_apply_writes_to_disk(repo: Path) -> None:
    _seed_unreleased(
        repo,
        "pr-100-feat.yml",
        "type: feature\nfeature:\n  description: New thing.\n",
    )
    rc = build_release_main(["apply", "--repo-root", str(repo), "--current-version", "0.4.0"])
    assert rc == 0
    assert (repo / "CHANGELOG.md").exists()
    assert (repo / "changelog" / "0.5.0" / "pr-100-feat.yml").exists()


def test_cli_render_notes_reads_versioned_dir(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Mimic a post-merge state: file moved to changelog/0.5.0/.
    target = repo / "changelog" / "0.5.0" / "pr-100-feat.yml"
    target.parent.mkdir(parents=True)
    target.write_text(
        "type: feature\nfeature:\n  description: A thing.\n",
        encoding="utf-8",
    )
    rc = build_release_main(["render-notes", "--repo-root", str(repo), "--version", "0.5.0"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Release v0.5.0." in captured.out
    assert "A thing." in captured.out


def test_cli_render_notes_fails_when_version_missing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = build_release_main(["render-notes", "--repo-root", str(repo), "--version", "0.5.0"])
    assert rc == 1


# --- script-mode invocation -------------------------------------------------


def test_script_mode_executes_via_python(repo: Path) -> None:
    """``python scripts/changelog/build_release.py compute …`` works.

    The release workflow invokes the module as a script (so it doesn't
    need the workspace venv); pin the script-mode entrypoint so a
    refactor doesn't break the workflow contract.
    """
    _seed_unreleased(
        repo,
        "pr-100-feat.yml",
        "type: feature\nfeature:\n  description: x.\n",
    )
    script = REPO_ROOT / "scripts" / "changelog" / "build_release.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "compute",
            "--repo-root",
            str(repo),
            "--current-version",
            "0.4.0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["next_version"] == "0.5.0"


def test_section_order_matches_palantir_priority():
    """`break` first, `migration` last — the Palantir convention."""
    assert SECTION_ORDER[0].value == "break"
    assert SECTION_ORDER[-1].value == "migration"
