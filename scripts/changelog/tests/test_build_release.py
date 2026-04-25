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
