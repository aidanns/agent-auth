# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for ``scripts/changelog/lint.py``.

Exercise the public CLI surface (``main`` + ``run_lint``) against
fixture git repos rather than reaching into private state. ``main`` is
exercised via argv + exit code; ``run_lint`` is exercised via
keyword args + report inspection so failure messages can be asserted
without parsing stderr.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from lint import (
    MAX_DESCRIPTION_WORDS,
    NO_CHANGELOG_LABEL,
    LintReport,
    detect_current_version,
    list_added_changelog_files,
    list_present_changelog_files,
    list_workspace_packages,
    main,
    parse_pr_labels,
    run_lint,
)

# --- fixture helpers ---------------------------------------------------------


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run ``git`` in ``repo`` with deterministic identity and date config."""
    base_env = os.environ.copy()
    base_env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        }
    )
    if env:
        base_env.update(env)
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        env=base_env,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Initialise a throwaway git repo with a workspace-shaped layout."""
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    # Minimal workspace layout: two packages so list_workspace_packages
    # has real names to validate against.
    for name in ("agent-auth", "agent-auth-common"):
        pkg_dir = tmp_path / "packages" / name
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\n',
            encoding="utf-8",
        )

    (tmp_path / "changelog" / "@unreleased").mkdir(parents=True)
    (tmp_path / "changelog" / "@unreleased" / ".gitkeep").write_text("", encoding="utf-8")

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


def _commit_added(repo: Path, relpath: str, content: str, message: str) -> str:
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", relpath)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


# --- list_workspace_packages -------------------------------------------------


def test_list_workspace_packages_reads_each_pyproject(repo: Path):
    names = list_workspace_packages(repo)
    assert names == ["agent-auth", "agent-auth-common"]


def test_list_workspace_packages_returns_empty_when_packages_missing(tmp_path: Path):
    assert list_workspace_packages(tmp_path) == []


# --- list_added_changelog_files ----------------------------------------------


def test_list_added_changelog_files_returns_only_added_files(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-7-feature.yml",
        "type: feature\nfeature:\n  description: x.\n",
        "add changelog entry",
    )
    files = list_added_changelog_files(base, head, repo_root=repo)
    assert [p.name for p in files] == ["pr-7-feature.yml"]


def test_list_added_changelog_files_skips_unrelated_paths(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(repo, "scripts/random.txt", "x", "unrelated change")
    files = list_added_changelog_files(base, head, repo_root=repo)
    assert files == []


# --- list_present_changelog_files --------------------------------------------


def test_list_present_changelog_files_lists_only_yml_files(repo: Path):
    target = repo / "changelog" / "@unreleased"
    (target / "pr-1-a.yml").write_text("type: fix\nfix:\n  description: x.\n", encoding="utf-8")
    (target / "README.md").write_text("# notes", encoding="utf-8")
    paths = list_present_changelog_files(repo)
    assert [p.name for p in paths] == ["pr-1-a.yml"]


# --- parse_pr_labels ---------------------------------------------------------


def test_parse_pr_labels_handles_empty_input():
    assert parse_pr_labels(None) == set()
    assert parse_pr_labels("") == set()
    assert parse_pr_labels(",,") == set()


def test_parse_pr_labels_strips_and_dedupes():
    assert parse_pr_labels("a, b, a") == {"a", "b"}


# --- detect_current_version --------------------------------------------------


def test_detect_current_version_prefers_explicit_override(repo: Path):
    assert detect_current_version(repo, "v1.2.3") == "1.2.3"
    assert detect_current_version(repo, "1.2.3") == "1.2.3"


def test_detect_current_version_falls_back_to_zero_when_no_tag(repo: Path):
    assert detect_current_version(repo, None) == "0.0.0"


def test_detect_current_version_reads_latest_tag(repo: Path):
    _git(repo, "tag", "v0.4.2")
    assert detect_current_version(repo, None) == "0.4.2"


# --- run_lint ----------------------------------------------------------------


def test_run_lint_passes_for_well_formed_entry(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-add-thing.yml",
        "type: feature\nfeature:\n  description: Adds a thing.\n",
        "add entry",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_fails_when_no_entry_added_and_no_bypass(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(repo, "scripts/random.txt", "x", "unrelated")
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    assert "no changelog entry" in report.render()


def test_run_lint_passes_with_no_changelog_label_bypass(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(repo, "scripts/random.txt", "x", "unrelated")
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels={NO_CHANGELOG_LABEL},
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_fails_when_filename_pr_number_mismatches(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-99-mismatch.yml",
        "type: fix\nfix:\n  description: x.\n",
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    rendered = report.render()
    assert "embedded PR number `99`" in rendered
    # File-presence check also fires because no PR-12 file exists.
    assert "no changelog entry" in rendered


def test_run_lint_fails_when_filename_does_not_match_pattern(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/wrong-name.yml",
        "type: fix\nfix:\n  description: x.\n",
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    assert "filename must match" in report.render()


def test_run_lint_emits_single_filename_error_when_added_file_is_non_conforming(
    repo: Path,
):
    """A non-conforming filename added in this PR yields one error, not two.

    Both ``check_file_naming`` (added files) and
    ``check_present_file_naming`` (every file currently in
    ``@unreleased/``) inspect the filename pattern; without explicit
    deduplication a single non-conforming filename added in one PR
    produces two near-duplicate "filename must match" lines in the
    rendered report. The contributor sees the same path twice with
    slightly different remediation prose, which is noisy and obscures
    the real action: rename the file. This regression guard pins the
    behaviour at exactly one "filename must match" line per offending
    path so the report stays terse.
    """
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/wrong-name.yml",
        "type: fix\nfix:\n  description: x.\n",
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    rendered = report.render()
    matching_lines = [
        line
        for line in rendered.splitlines()
        if "wrong-name.yml" in line and "filename must match" in line
    ]
    assert len(matching_lines) == 1, (
        "expected exactly one `filename must match` line for "
        "wrong-name.yml; got:\n" + "\n".join(matching_lines)
    )


def test_run_lint_fails_when_unreleased_file_lacks_pr_prefix(repo: Path):
    """Files already on `main` must also match `pr-<N>-<slug>.yml` (#411).

    The release-PR renderer derives the per-entry `(#N)` PR-link
    suffix from the filename; an unreleased entry that doesn't match
    the pattern would silently lose its link in the published
    release notes. The lint catches it at PR-time so the offender is
    renamed before it reaches the release.
    """
    # Pre-existing entry on `main` that doesn't conform: committed
    # before the PR branch is opened so it shows up in
    # ``list_present_changelog_files`` but not ``list_added_…``.
    legacy = repo / "changelog" / "@unreleased" / "legacy-no-prefix.yml"
    legacy.write_text(
        "type: fix\nfix:\n  description: legacy.\n",
        encoding="utf-8",
    )
    _git(repo, "add", str(legacy))
    _git(repo, "commit", "-m", "land legacy entry")

    base = _git(repo, "rev-parse", "HEAD")
    # Add an unrelated file to give the PR a non-empty diff.
    head = _commit_added(repo, "scripts/random.txt", "x", "unrelated")

    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels={NO_CHANGELOG_LABEL},
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    rendered = report.render()
    assert "legacy-no-prefix.yml" in rendered
    assert "filename must match" in rendered


def test_run_lint_fails_on_schema_error_with_path_in_message(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-bad.yml",
        "type: nonsense\n",
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    rendered = report.render()
    assert "pr-12-bad.yml" in rendered
    assert "unknown type" in rendered


def test_run_lint_validates_packages_against_workspace_members(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-bad-pkg.yml",
        ("type: fix\n" "fix:\n" "  description: x.\n" "packages:\n" "  - imaginary-svc\n"),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    assert "imaginary-svc" in report.render()


def test_run_lint_fails_on_release_as_not_strictly_greater(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-graduate.yml",
        ("type: feature\n" "feature:\n" "  description: x.\n" "release-as: 0.5.0\n"),
        "add",
    )
    # Inferred = 0.5.0 (FEATURE bumps minor on 0.4.2). Override == inferred fails.
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    assert "strictly greater" in report.render()


def test_run_lint_passes_on_release_as_strictly_greater(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-graduate.yml",
        ("type: feature\n" "feature:\n" "  description: x.\n" "release-as: 1.0.0\n"),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_fails_on_conflicting_release_as_across_files(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    _commit_added(
        repo,
        "changelog/@unreleased/pr-12-a.yml",
        "type: feature\nfeature:\n  description: x.\nrelease-as: 1.0.0\n",
        "add a",
    )
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-b.yml",
        "type: feature\nfeature:\n  description: y.\nrelease-as: 2.0.0\n",
        "add b",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    assert "conflicting" in report.render()


# --- main (CLI) --------------------------------------------------------------


def test_main_returns_zero_on_success(repo: Path, monkeypatch: pytest.MonkeyPatch):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-x.yml",
        "type: fix\nfix:\n  description: x.\n",
        "add",
    )
    monkeypatch.delenv("PR_LABELS", raising=False)
    rc = main(
        [
            "--pr-number",
            "12",
            "--base-sha",
            base,
            "--head-sha",
            head,
            "--current-version",
            "0.4.2",
            "--repo-root",
            str(repo),
        ]
    )
    assert rc == 0


def test_main_returns_one_on_lint_failure(repo: Path, monkeypatch: pytest.MonkeyPatch):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(repo, "scripts/random.txt", "x", "unrelated")
    monkeypatch.delenv("PR_LABELS", raising=False)
    rc = main(
        [
            "--pr-number",
            "12",
            "--base-sha",
            base,
            "--head-sha",
            head,
            "--current-version",
            "0.4.2",
            "--repo-root",
            str(repo),
        ]
    )
    assert rc == 1


def test_main_returns_two_when_pr_number_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("PR_NUMBER", raising=False)
    monkeypatch.delenv("PR_LABELS", raising=False)
    rc = main(
        [
            "--base-sha",
            "deadbeef",
            "--head-sha",
            "deadbeef",
            "--current-version",
            "0.4.2",
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 2


def test_main_returns_two_when_shas_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("BASE_SHA", raising=False)
    monkeypatch.delenv("HEAD_SHA", raising=False)
    monkeypatch.delenv("PR_LABELS", raising=False)
    rc = main(
        [
            "--pr-number",
            "12",
            "--current-version",
            "0.4.2",
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 2


# --- LintReport --------------------------------------------------------------


def test_lint_report_has_no_errors_when_unused():
    report = LintReport()
    assert not report.has_errors
    assert report.render() == ""


def test_lint_report_accumulates_messages():
    report = LintReport()
    report.fail("first")
    report.fail("second")
    assert report.has_errors
    assert report.render().splitlines() == ["first", "second"]


# --- description-style lint (#407) -------------------------------------------


def _make_description_yaml(description: str) -> str:
    """Render a minimal `type: improvement` YAML carrying ``description``.

    The block-scalar style ``description: |`` mirrors the project's
    on-disk shape and exercises the lint's whitespace normalisation.
    """
    indented = "\n".join(f"    {line}" if line else "" for line in description.splitlines())
    return "type: improvement\nimprovement:\n  description: |\n" + indented + "\n"


def test_run_lint_passes_for_terse_single_sentence_description(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-terse.yml",
        _make_description_yaml(
            "`merge-bot` now auto-updates a PR whose head sits behind `main` "
            "instead of failing on the merge API's 405."
        ),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_fails_when_description_exceeds_word_cap(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    # Construct a deliberately long single-sentence description so the
    # word cap is the only failure mode being asserted.
    long_words = " ".join(["word"] * (MAX_DESCRIPTION_WORDS + 5))
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-long.yml",
        _make_description_yaml(f"{long_words}."),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    rendered = report.render()
    assert f"{MAX_DESCRIPTION_WORDS + 5} words" in rendered
    assert "==COMMIT_MSG==" in rendered


def test_run_lint_passes_when_description_is_exactly_word_cap(repo: Path):
    """The cap is inclusive: exactly ``MAX_DESCRIPTION_WORDS`` words must pass.

    Pinned so that a future regression flipping the comparison from
    ``>`` to ``>=`` (silently rejecting descriptions at the boundary)
    fails this test rather than slipping into CI.
    """
    base = _git(repo, "rev-parse", "HEAD")
    boundary_words = " ".join(["word"] * MAX_DESCRIPTION_WORDS)
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-boundary.yml",
        _make_description_yaml(f"{boundary_words}."),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_fails_when_description_has_multiple_sentences(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-multi.yml",
        _make_description_yaml("First sentence ends here. Second sentence is the problem."),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    rendered = report.render()
    assert "single sentence" in rendered
    assert "==COMMIT_MSG==" in rendered


def test_run_lint_fails_when_quoted_sentence_hides_a_boundary(repo: Path):
    """Embedded boundary detection must look past a closing quote.

    Pattern: a sentence-terminator immediately followed by a closing
    quote (``."``) and then whitespace. Without quote-aware handling
    the regex only matches `terminator + space` so the multi-sentence
    description below would slip past the lint despite clearly
    breaking the single-sentence rule.
    """
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-quoted.yml",
        _make_description_yaml('He said "Hello world." Then exited.'),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    assert "single sentence" in report.render()


def test_run_lint_passes_when_single_sentence_contains_embedded_quote(repo: Path):
    """A single sentence with an inline quoted phrase must still pass.

    Guards against an over-eager fix to the quote-aware boundary
    detection that would treat any embedded quote as a sentence break.
    The description below has exactly one terminal `.` and no embedded
    terminator-then-whitespace sequence.
    """
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-inline-quote.yml",
        _make_description_yaml('Adds support for "scoped" tokens.'),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_passes_when_abbreviation_is_parenthesised(repo: Path):
    """Parenthesised abbreviations must still match the allowlist.

    Authors writing natural release-note asides like
    ``Adds X (e.g. Y) here.`` would otherwise be falsely flagged: the
    abbreviation tokeniser walks back to the most recent space and
    captures ``(e.g.``, which is not in the allowlist. The fix strips
    leading opening-bracket characters before the membership check.
    """
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-paren-eg.yml",
        _make_description_yaml("Adds X (e.g. Y) here."),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_fails_when_description_lacks_terminal_punctuation(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-no-period.yml",
        _make_description_yaml("Adds a thing without ending punctuation"),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert report.has_errors
    assert "must end with" in report.render()


def test_run_lint_passes_when_description_uses_eg_abbreviation(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-eg.yml",
        _make_description_yaml("Adds support for common abbreviations, e.g. timestamps."),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_passes_when_description_uses_ie_etc_abbreviations(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-ie-etc.yml",
        _make_description_yaml("Drops the legacy backend, i.e. the v1 sync path, etc."),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_passes_when_description_uses_initial(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-initial.yml",
        _make_description_yaml("Adopts the J. Doe convention for author records."),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_passes_when_block_scalar_wraps_a_long_single_sentence(repo: Path):
    """Whitespace from `description: |` block-scalar wraps must collapse cleanly.

    The fixture's description spans two lines; after normalisation the
    embedded newline becomes a single space and the line still parses
    as a single 13-word sentence terminated by `.`.
    """
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-wrapped.yml",
        _make_description_yaml(
            "Tightens the HMAC comparison so it is constant-time\n"
            "across every supported Python build."
        ),
        "add",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors


def test_run_lint_does_not_recheck_existing_unreleased_entries(repo: Path):
    """Forward-only: pre-existing `@unreleased/*.yml` files aren't re-validated.

    Documents the deliberate scope choice so a regression that widens
    the description-style check to the union (added + already-present)
    fails this test instead of silently breaking historical entries.
    """
    # Stage a verbose multi-sentence description that pre-dates the
    # PR — committed on an earlier commit so it shows up under the
    # "already present" set but NOT the "added in this PR" set.
    target = repo / "changelog" / "@unreleased" / "pr-7-verbose.yml"
    target.write_text(
        _make_description_yaml(
            "First sentence pre-dates the lint. Second sentence is "
            "still here because the rule is forward-only."
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "changelog/@unreleased/pr-7-verbose.yml")
    _git(repo, "commit", "-m", "historical entry")

    base = _git(repo, "rev-parse", "HEAD")
    head = _commit_added(
        repo,
        "changelog/@unreleased/pr-12-fresh.yml",
        _make_description_yaml("Adds a fresh, terse single-sentence entry."),
        "add fresh",
    )
    report = run_lint(
        pr_number=12,
        base_sha=base,
        head_sha=head,
        labels=set(),
        current_version="0.4.2",
        repo_root=repo,
    )
    assert not report.has_errors
