# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for ``scripts/changelog/add.py``.

Exercise the public surface (``main``, ``compose_yaml``,
``derive_slug``, ``gate_write``, ``check_branch_has_entry``) against
fixture git repos. Interactive prompts are tested by feeding
``StringIO`` into ``main(stdin=…, stdout=…)`` so the test runner does
not need a real TTY (the non-interactive branch fires; the
``_is_interactive`` gate is exercised separately).
"""

from __future__ import annotations

import io
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from add import (
    MAX_SLUG_RETRIES,
    TYPE_CHOICES,
    CliError,
    EntryDraft,
    build_draft_non_interactive,
    candidate_path,
    check_branch_has_entry,
    compose_yaml,
    derive_slug,
    derive_unique_path,
    gate_write,
    main,
    parse_packages_csv,
)
from version_logic import EntryType, parse_entry_file
from wordlist import WORDS

# --- fixture helpers ---------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    """Run ``git`` in ``repo`` with deterministic identity / date config."""
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        }
    )
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Throwaway repo with a workspace-shaped layout (matches ``test_lint``)."""
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    for name in ("agent-auth", "agent-auth-common"):
        pkg = tmp_path / "packages" / name
        pkg.mkdir(parents=True)
        (pkg / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\n',
            encoding="utf-8",
        )
    (tmp_path / "changelog" / "@unreleased").mkdir(parents=True)
    (tmp_path / "changelog" / "@unreleased" / ".gitkeep").write_text("", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


# --- compose_yaml ------------------------------------------------------------


def test_compose_yaml_minimal_entry_passes_lint(tmp_path: Path) -> None:
    draft = EntryDraft(
        entry_type=EntryType.FEATURE,
        description="Add a thing.",
        pr_number=1,
        packages=None,
        release_as=None,
    )
    body = compose_yaml(draft)
    target = tmp_path / "pr-1-cli.yml"
    target.write_text(body, encoding="utf-8")
    entry = parse_entry_file(target)
    assert entry.entry_type == EntryType.FEATURE
    assert "Add a thing." in entry.description
    assert entry.packages is None
    assert entry.release_as is None
    assert entry.links == ("https://github.com/aidanns/agent-auth/pull/1",)


def test_compose_yaml_with_packages_passes_lint(tmp_path: Path) -> None:
    draft = EntryDraft(
        entry_type=EntryType.FIX,
        description="Tighten HMAC comparison.",
        pr_number=42,
        packages=("agent-auth", "agent-auth-common"),
        release_as=None,
    )
    body = compose_yaml(draft)
    target = tmp_path / "pr-42-cli.yml"
    target.write_text(body, encoding="utf-8")
    entry = parse_entry_file(target)
    assert entry.packages == ("agent-auth", "agent-auth-common")


def test_compose_yaml_with_release_as_passes_lint(tmp_path: Path) -> None:
    draft = EntryDraft(
        entry_type=EntryType.FEATURE,
        description="Graduate to 1.0.0.",
        pr_number=99,
        packages=None,
        release_as="1.0.0",
    )
    body = compose_yaml(draft)
    target = tmp_path / "pr-99-cli.yml"
    target.write_text(body, encoding="utf-8")
    entry = parse_entry_file(target)
    assert entry.release_as == "1.0.0"


def test_compose_yaml_starts_with_spdx_header() -> None:
    draft = EntryDraft(
        entry_type=EntryType.FIX,
        description="x",
        pr_number=7,
        packages=None,
        release_as=None,
    )
    assert compose_yaml(draft).startswith("# SPDX-FileCopyrightText:")


def test_compose_yaml_rejects_empty_description() -> None:
    draft = EntryDraft(
        entry_type=EntryType.FIX,
        description="   \n   ",
        pr_number=7,
        packages=None,
        release_as=None,
    )
    with pytest.raises(CliError):
        compose_yaml(draft)


@pytest.mark.parametrize("type_value", TYPE_CHOICES)
def test_compose_yaml_every_type_passes_lint(type_value: str, tmp_path: Path) -> None:
    draft = EntryDraft(
        entry_type=EntryType(type_value),
        description=f"A change of type {type_value}.",
        pr_number=12,
        packages=None,
        release_as=None,
    )
    body = compose_yaml(draft)
    target = tmp_path / f"pr-12-{type_value}.yml"
    target.write_text(body, encoding="utf-8")
    entry = parse_entry_file(target)
    assert entry.entry_type.value == type_value


# --- derive_slug -------------------------------------------------------------


def test_derive_slug_uses_two_words() -> None:
    rng = random.Random(0)
    slug = derive_slug(rng)
    a, _, b = slug.partition("-")
    assert a in WORDS
    assert b in WORDS


def test_derive_slug_matches_lint_filename_pattern() -> None:
    """Every slug we emit must satisfy the lint's ``[A-Za-z0-9_-]+`` rule."""
    import re

    pattern = re.compile(r"^pr-\d+-[A-Za-z0-9_-]+\.yml$")
    rng = random.Random(0)
    for _ in range(100):
        slug = derive_slug(rng)
        assert pattern.match(f"pr-1-{slug}.yml"), slug


def test_derive_slug_is_deterministic_under_seeded_rng() -> None:
    a = derive_slug(random.Random(0))
    b = derive_slug(random.Random(0))
    assert a == b


# --- derive_unique_path ------------------------------------------------------


def test_derive_unique_path_avoids_existing_files(repo: Path) -> None:
    rng = random.Random(0)
    first = derive_unique_path(repo, 7, rng)
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("placeholder", encoding="utf-8")

    rng = random.Random(0)  # same seed; collision should force retry
    second = derive_unique_path(repo, 7, rng)
    assert second != first
    assert not second.exists()


def test_derive_unique_path_raises_after_max_retries(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pinned slug forces every retry to collide so we hit the cap."""

    def constant_slug(_rng: random.Random) -> str:
        return "stuck-slug"

    import add as add_mod

    monkeypatch.setattr(add_mod, "derive_slug", constant_slug)
    target = candidate_path(repo, 7, "stuck-slug")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("placeholder", encoding="utf-8")
    with pytest.raises(CliError) as info:
        derive_unique_path(repo, 7, random.Random(), max_retries=MAX_SLUG_RETRIES)
    assert "unique slug" in str(info.value)


# --- parse_packages_csv ------------------------------------------------------


def test_parse_packages_csv_returns_none_for_empty() -> None:
    assert parse_packages_csv(None) is None
    assert parse_packages_csv("") is None
    assert parse_packages_csv("   ") is None
    assert parse_packages_csv(",,") is None


def test_parse_packages_csv_strips_and_splits() -> None:
    assert parse_packages_csv("a, b, c") == ("a", "b", "c")


# --- gate_write --------------------------------------------------------------


def test_gate_write_passes_for_well_formed_minimal_entry(repo: Path) -> None:
    draft = EntryDraft(
        entry_type=EntryType.FIX,
        description="A fix.",
        pr_number=12,
        packages=None,
        release_as=None,
    )
    gate_write(draft, repo, "0.4.2")


def test_gate_write_rejects_unknown_packages(repo: Path) -> None:
    draft = EntryDraft(
        entry_type=EntryType.FIX,
        description="A fix.",
        pr_number=12,
        packages=("imaginary-svc",),
        release_as=None,
    )
    with pytest.raises(CliError) as info:
        gate_write(draft, repo, "0.4.2")
    assert "imaginary-svc" in str(info.value)


def test_gate_write_rejects_release_as_not_strictly_greater(repo: Path) -> None:
    # FEATURE on 0.4.2 infers 0.5.0; release-as: 0.5.0 violates the
    # strictly-greater rule.
    draft = EntryDraft(
        entry_type=EntryType.FEATURE,
        description="Graduate.",
        pr_number=12,
        packages=None,
        release_as="0.5.0",
    )
    with pytest.raises(CliError) as info:
        gate_write(draft, repo, "0.4.2")
    assert "release-as" in str(info.value)
    assert "strictly greater" in str(info.value)


def test_gate_write_accepts_release_as_strictly_greater(repo: Path) -> None:
    draft = EntryDraft(
        entry_type=EntryType.FEATURE,
        description="Graduate.",
        pr_number=12,
        packages=None,
        release_as="1.0.0",
    )
    gate_write(draft, repo, "0.4.2")


def test_gate_write_rejects_zero_pr_number(repo: Path) -> None:
    draft = EntryDraft(
        entry_type=EntryType.FIX,
        description="x",
        pr_number=0,
        packages=None,
        release_as=None,
    )
    with pytest.raises(CliError):
        gate_write(draft, repo, "0.4.2")


# --- build_draft_non_interactive --------------------------------------------


def test_build_draft_non_interactive_requires_type() -> None:
    args = _ns(type=None, description="x", pr=1)
    with pytest.raises(CliError) as info:
        build_draft_non_interactive(args)
    assert "--type" in str(info.value)


def test_build_draft_non_interactive_requires_description() -> None:
    args = _ns(type="fix", description=None, pr=1)
    with pytest.raises(CliError) as info:
        build_draft_non_interactive(args)
    assert "--description" in str(info.value)


def test_build_draft_non_interactive_requires_pr() -> None:
    args = _ns(type="fix", description="x", pr=None)
    with pytest.raises(CliError) as info:
        build_draft_non_interactive(args)
    assert "--pr" in str(info.value)


def test_build_draft_non_interactive_returns_populated_draft() -> None:
    args = _ns(type="fix", description="x", pr=12, packages="agent-auth")
    draft = build_draft_non_interactive(args)
    assert draft.entry_type == EntryType.FIX
    assert draft.description == "x"
    assert draft.pr_number == 12
    assert draft.packages == ("agent-auth",)


# --- main (CLI) --------------------------------------------------------------


def test_main_writes_yaml_on_non_interactive_success(repo: Path) -> None:
    rc = main(
        [
            "--type",
            "fix",
            "--description",
            "tighten the comparison",
            "--pr",
            "42",
            "--repo-root",
            str(repo),
            "--current-version",
            "0.4.2",
        ],
        stdin=io.StringIO(),  # not a TTY -> non-interactive path
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert rc == 0
    written = list((repo / "changelog" / "@unreleased").glob("pr-42-*.yml"))
    assert len(written) == 1
    entry = parse_entry_file(written[0])
    assert entry.entry_type == EntryType.FIX
    assert "tighten the comparison" in entry.description


def test_main_returns_one_on_validation_error(repo: Path) -> None:
    err = io.StringIO()
    rc = main(
        [
            "--type",
            "fix",
            "--description",
            "x",
            "--pr",
            "12",
            "--packages",
            "imaginary-svc",
            "--repo-root",
            str(repo),
            "--current-version",
            "0.4.2",
        ],
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        stderr=err,
    )
    assert rc == 1
    assert "imaginary-svc" in err.getvalue()


def test_main_non_interactive_missing_field_returns_one(repo: Path) -> None:
    err = io.StringIO()
    rc = main(
        [
            "--type",
            "fix",
            "--repo-root",
            str(repo),
            "--current-version",
            "0.4.2",
        ],
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        stderr=err,
    )
    assert rc == 1
    rendered = err.getvalue()
    assert "--description" in rendered
    assert "--pr" in rendered


# --- --check mode ------------------------------------------------------------


def test_check_branch_has_entry_returns_true_when_yaml_added(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    target = repo / "changelog" / "@unreleased" / "pr-7-foo-bar.yml"
    target.write_text(
        "type: fix\nfix:\n  description: x\n",
        encoding="utf-8",
    )
    _git(repo, "checkout", "-b", "feature")
    _git(repo, "add", str(target))
    _git(repo, "commit", "-m", "add entry")
    assert check_branch_has_entry(repo, base) is True


def test_check_branch_has_entry_returns_false_when_no_yaml(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "feature")
    (repo / "scratch.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "scratch.txt")
    _git(repo, "commit", "-m", "unrelated")
    assert check_branch_has_entry(repo, base) is False


def test_check_branch_has_entry_returns_true_on_unknown_base_ref(repo: Path) -> None:
    """Defensive: an unknown base ref shouldn't surface a false alarm."""
    assert check_branch_has_entry(repo, "origin/this-ref-does-not-exist") is True


def test_main_check_mode_warns_on_missing_entry(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "feature")
    (repo / "scratch.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "scratch.txt")
    _git(repo, "commit", "-m", "unrelated")
    err = io.StringIO()
    rc = main(
        ["--check", "--base-ref", base, "--repo-root", str(repo)],
        stderr=err,
    )
    assert rc == 0  # advisory only
    assert "no changelog/@unreleased" in err.getvalue()


def test_main_check_strict_mode_fails_on_missing_entry(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "feature")
    (repo / "scratch.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "scratch.txt")
    _git(repo, "commit", "-m", "unrelated")
    err = io.StringIO()
    rc = main(
        ["--check", "--strict", "--base-ref", base, "--repo-root", str(repo)],
        stderr=err,
    )
    assert rc == 1


def test_main_check_mode_silent_when_entry_present(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    target = repo / "changelog" / "@unreleased" / "pr-7-foo-bar.yml"
    target.write_text("type: fix\nfix:\n  description: x\n", encoding="utf-8")
    _git(repo, "checkout", "-b", "feature")
    _git(repo, "add", str(target))
    _git(repo, "commit", "-m", "add entry")
    err = io.StringIO()
    rc = main(
        ["--check", "--base-ref", base, "--repo-root", str(repo)],
        stderr=err,
    )
    assert rc == 0
    assert err.getvalue() == ""


# --- editor flow -------------------------------------------------------------


def test_editor_flow_uses_editor_env(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--editor`` opens $EDITOR; the script's writes round-trip into the YAML."""
    editor_script = tmp_path / "fake_editor.sh"
    editor_script.write_text(
        "#!/usr/bin/env bash\n" 'printf "Captured via fake editor.\\nWith two lines.\\n" > "$1"\n',
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(editor_script))

    # Force the interactive path by faking isatty on both streams.
    class _TtyStream(io.StringIO):
        def isatty(self) -> bool:
            return True

    stdin = _TtyStream("fix\n\n\n")  # type, packages prompt (empty), pr (default)
    stdout = _TtyStream()
    err = io.StringIO()

    # ``gh pr view`` is unlikely to resolve in the throwaway repo, so
    # pre-supply the PR number via the flag (sidestep the prompt).
    rc = main(
        [
            "--editor",
            "--pr",
            "55",
            "--repo-root",
            str(repo),
            "--current-version",
            "0.4.2",
        ],
        stdin=stdin,
        stdout=stdout,
        stderr=err,
    )
    assert rc == 0, err.getvalue()
    written = list((repo / "changelog" / "@unreleased").glob("pr-55-*.yml"))
    assert len(written) == 1
    body = written[0].read_text(encoding="utf-8")
    assert "Captured via fake editor." in body
    assert "With two lines." in body


# --- helpers -----------------------------------------------------------------


def _ns(**kwargs: object):
    """Minimal argparse.Namespace stand-in for the non-interactive tests."""
    import argparse

    defaults = {
        "type": None,
        "description": None,
        "pr": None,
        "packages": None,
        "release_as": None,
        "release_as_present": False,
        "editor": False,
        "repo_root": ".",
        "current_version": "",
        "check": False,
        "strict": False,
        "base_ref": "origin/main",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# Acknowledge module-level import side effects: ``add`` is on sys.path
# via conftest.py, but importing it for the first time inside a test
# would warm the path. Keep an explicit reference so static analysers
# don't flag the imports as unused.
_ = sys
