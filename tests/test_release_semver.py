"""Unit tests for scripts/lib/semver.sh.

These tests exercise `compute_bump` and `apply_bump` via `bash -c 'source lib;
<fn> …'` against fixture git repos built per-test. The release script is the
single entry point for cutting a tag — the bump-resolution logic is
high-consequence (a wrong bump produces a tag that can't be un-cut), so the
library is pinned down with tests even though the rest of the repo's bash is
not.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SEMVER_LIB = REPO_ROOT / "scripts" / "lib" / "semver.sh"


def _git(cwd: Path, *args: str, input: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        input=input,
    )
    return result.stdout


def _init_repo(path: Path) -> None:
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    _git(path, "config", "tag.gpgsign", "false")
    # Seed commit — compute_bump wants a range with a base tag.
    _git(path, "commit", "--allow-empty", "-q", "-m", "chore: initial")


def _commit(path: Path, message: str) -> None:
    _git(path, "commit", "--allow-empty", "-q", "-F", "-", input=message)


def _tag(path: Path, name: str, ref: str = "HEAD") -> None:
    _git(path, "tag", "-f", name, ref)


def _compute_bump(cwd: Path, tag: str) -> str:
    cmd = f'source "{SEMVER_LIB}" && compute_bump "{tag}..HEAD"'
    result = subprocess.run(
        ["bash", "-c", cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"compute_bump failed: {result.stderr}"
    return result.stdout.strip()


def _apply_bump(last_tag: str, bump: str) -> str:
    cmd = f'source "{SEMVER_LIB}" && apply_bump "{last_tag}" "{bump}"'
    result = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"apply_bump failed: {result.stderr}"
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    _tag(tmp_path, "v0.1.0")
    return tmp_path


class TestComputeBump:
    def test_empty_range_returns_none(self, repo: Path) -> None:
        assert _compute_bump(repo, "v0.1.0") == "none"

    def test_docs_only_returns_none(self, repo: Path) -> None:
        _commit(repo, "docs: update README")
        _commit(repo, "chore: bump deps")
        assert _compute_bump(repo, "v0.1.0") == "none"

    def test_fix_returns_patch(self, repo: Path) -> None:
        _commit(repo, "fix: off-by-one")
        assert _compute_bump(repo, "v0.1.0") == "patch"

    def test_fix_with_scope_returns_patch(self, repo: Path) -> None:
        _commit(repo, "fix(scopes): off-by-one")
        assert _compute_bump(repo, "v0.1.0") == "patch"

    def test_feat_returns_minor(self, repo: Path) -> None:
        _commit(repo, "feat: new capability")
        assert _compute_bump(repo, "v0.1.0") == "minor"

    def test_feat_outranks_fix(self, repo: Path) -> None:
        _commit(repo, "fix: a")
        _commit(repo, "feat: b")
        _commit(repo, "fix: c")
        assert _compute_bump(repo, "v0.1.0") == "minor"

    def test_bang_subject_returns_major(self, repo: Path) -> None:
        _commit(repo, "feat!: breaking")
        assert _compute_bump(repo, "v0.1.0") == "major"

    def test_bang_with_scope_returns_major(self, repo: Path) -> None:
        _commit(repo, "refactor(api)!: rename endpoint")
        assert _compute_bump(repo, "v0.1.0") == "major"

    def test_breaking_change_footer_returns_major(self, repo: Path) -> None:
        _commit(
            repo,
            "feat: new thing\n\nBREAKING CHANGE: removed old thing",
        )
        assert _compute_bump(repo, "v0.1.0") == "major"

    def test_breaking_change_hyphen_footer_returns_major(self, repo: Path) -> None:
        _commit(
            repo,
            "feat: new thing\n\nBREAKING-CHANGE: removed old thing",
        )
        assert _compute_bump(repo, "v0.1.0") == "major"

    def test_uppercase_subject_does_not_match(self, repo: Path) -> None:
        # Conventional Commits requires lowercase types. `Feat!:` and `FIX:`
        # must not silently trigger a release — regression guard for the
        # breaking_re / feat_re asymmetry that an earlier revision had.
        _commit(repo, "Feat!: uppercase")
        _commit(repo, "FIX: shouting")
        assert _compute_bump(repo, "v0.1.0") == "none"

    def test_unknown_type_does_not_match_even_with_bang(self, repo: Path) -> None:
        # An unknown lowercase type with `!:` still promotes to major, which
        # is spec-aligned (any `<type>!:` means breaking). Documents the
        # intentional behaviour so a later tightening of the whitelist is a
        # deliberate test change, not a silent regression.
        _commit(repo, "custom!: something")
        assert _compute_bump(repo, "v0.1.0") == "major"

    def test_pure_revert_does_not_re_trigger_breaking(self, repo: Path) -> None:
        # Regression guard: when a `git revert` commit is the only thing in
        # the range (the reverted commit was already released), the revert's
        # body contains 'This reverts commit <sha>.' which `git revert -e`
        # may follow with the reverted commit's full message including any
        # BREAKING CHANGE footer. The compute_bump parser strips from the
        # 'This reverts commit' marker onward so a lone revert doesn't
        # silently promote to a major bump.
        target = repo / "feature.txt"
        target.write_text("new feature\n")
        _git(repo, "add", "feature.txt")
        _git(
            repo,
            "commit",
            "-q",
            "-m",
            "feat!: breaking thing\n\nBREAKING CHANGE: removed the old API",
        )
        breaking_sha = _git(repo, "rev-parse", "HEAD").strip()
        # Move v0.1.0 to after the breaking commit so only the revert is in
        # the range.
        _git(repo, "tag", "-f", "v0.1.0", "HEAD")
        # Use -e with a no-op editor so we get git's default revert template
        # that appends the reverted commit's full message (the case that
        # would otherwise trigger the BREAKING regex).
        _git(
            repo,
            "-c",
            "core.editor=true",
            "revert",
            breaking_sha,
        )
        assert _compute_bump(repo, "v0.1.0") == "none"

    def test_multi_line_body_does_not_swallow_next_commit(self, repo: Path) -> None:
        # Regression guard for the tempfile-based parser: an earlier
        # SHA-list implementation forked `git log -1 --format=%b` per
        # commit, which sidestepped multi-line parsing. This test ensures
        # bodies with newlines don't bleed into the next record.
        _commit(repo, "fix: first\n\nThis is a multi-line\nexplanation.")
        _commit(repo, "feat: second")
        assert _compute_bump(repo, "v0.1.0") == "minor"

    def test_invalid_range_returns_failure(self, repo: Path) -> None:
        # Process-substitution error swallowing was a real bug: `done <
        # <(git log ...)` silently printed 'none' when git failed. This
        # test pins down that the refactored parser reports failure
        # instead, via a non-zero exit code.
        cmd = f'source "{SEMVER_LIB}" && compute_bump "nonexistent..HEAD"'
        result = subprocess.run(
            ["bash", "-c", cmd],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "failed to list commits" in result.stderr


class TestApplyBump:
    @pytest.mark.parametrize(
        "last_tag,bump,expected",
        [
            ("v0.1.0", "patch", "0.1.1"),
            ("v0.1.0", "minor", "0.2.0"),
            ("v0.1.0", "major", "1.0.0"),
            ("v0.9.5", "minor", "0.10.0"),
            ("v1.2.3", "patch", "1.2.4"),
            ("v1.2.3", "minor", "1.3.0"),
            ("v1.2.3", "major", "2.0.0"),
            ("v10.0.0", "patch", "10.0.1"),
            ("v10.0.0", "minor", "10.1.0"),
            ("v10.0.0", "major", "11.0.0"),
        ],
    )
    def test_applies_correct_bump(
        self, last_tag: str, bump: str, expected: str
    ) -> None:
        assert _apply_bump(last_tag, bump) == expected

    def test_unknown_bump_returns_failure(self) -> None:
        cmd = f'source "{SEMVER_LIB}" && apply_bump "v0.1.0" "bogus"'
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "unknown bump" in result.stderr


def test_lib_passes_shellcheck() -> None:
    # Keep the library clean even though it's sourced (not executed). Ensures
    # the test suite fails if someone modifies semver.sh with a latent bug.
    result = subprocess.run(
        ["shellcheck", "--source-path=SCRIPTDIR", str(SEMVER_LIB)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"shellcheck failed:\n{result.stdout}\n{result.stderr}")


def test_lib_passes_shfmt() -> None:
    env = os.environ.copy()
    result = subprocess.run(
        ["shfmt", "-d", str(SEMVER_LIB)],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        pytest.fail(f"shfmt reports diffs:\n{result.stdout}")
