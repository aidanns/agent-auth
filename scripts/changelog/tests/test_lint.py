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
