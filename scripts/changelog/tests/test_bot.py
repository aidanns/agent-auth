# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for ``scripts/changelog/bot.py``.

Covers the pure-function surface (prefix mapping, marker extraction,
slug generation, YAML composition, lockout) plus the decision tree
end-to-end against a fake gh-API and a throwaway git repo. The
decision-tree tests exercise the module's public ``decide_and_act``
entry point with ``dry_run=True`` so no real ``gh api`` calls are
issued.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from bot import (
    NO_CHANGELOG_LABEL,
    PREFIX_TO_TYPE,
    BotError,
    BotIdentity,
    BotOutcome,
    PullRequest,
    candidate_yaml_path,
    compose_yaml,
    decide_and_act,
    derive_slug,
    existing_pr_yaml_files,
    extract_changelog_msg,
    file_authors,
    has_no_changelog_marker,
    is_locked_out,
    map_prefix_to_type,
    parse_pr_title_prefix,
)

# Tests don't import a real validator; verify the lint script accepts
# the bot's output by importing parse_entry_file from the sibling
# module.
from version_logic import EntryType, parse_entry_file

BOT_IDENTITY = BotIdentity(
    login="agent-auth-changelog-bot[bot]",
    name="agent-auth-changelog-bot[bot]",
    email="123+agent-auth-changelog-bot[bot]@users.noreply.github.com",
)


# --- prefix mapping ----------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected_prefix"),
    [
        ("feature: add knob", "feature"),
        ("Feature: add knob", "feature"),  # case-insensitive
        ("feature(ci): add knob", "feature"),
        ("improvement(metrics): cut p99", "improvement"),
        ("fix: tighten hmac", "fix"),
        ("break: remove legacy api", "break"),
        ("deprecation(scopes): mark old", "deprecation"),
        ("migration: rename column", "migration"),
        ("chore(ci): bump action", "chore"),
    ],
)
def test_parse_pr_title_prefix(title: str, expected_prefix: str) -> None:
    assert parse_pr_title_prefix(title) == expected_prefix


@pytest.mark.parametrize(
    "title",
    ["no-colon-here", "", ":missing", "(scope-only): nope"],
)
def test_parse_pr_title_prefix_rejects_malformed(title: str) -> None:
    with pytest.raises(BotError):
        parse_pr_title_prefix(title)


@pytest.mark.parametrize(
    ("prefix", "expected_type"),
    [
        ("feature", "feature"),
        ("improvement", "improvement"),
        ("fix", "fix"),
        ("break", "break"),
        ("deprecation", "deprecation"),
        ("migration", "migration"),
    ],
)
def test_map_prefix_to_type_palantir_changelog_prefixes(prefix: str, expected_type: str) -> None:
    assert map_prefix_to_type(prefix) == expected_type


def test_map_prefix_to_type_chore_returns_none() -> None:
    assert map_prefix_to_type("chore") is None


@pytest.mark.parametrize("prefix", ["feat", "perf", "revert", "docs", "ci", "build"])
def test_map_prefix_to_type_rejects_old_conventional_commits_prefixes(
    prefix: str,
) -> None:
    """Old Conventional Commits prefixes are rejected by #290's lint, so the
    bot only ever sees the Palantir set; an unknown prefix is a programmer
    error."""
    with pytest.raises(BotError):
        map_prefix_to_type(prefix)


def test_prefix_table_covers_six_release_types() -> None:
    assert set(PREFIX_TO_TYPE.keys()) == {
        "feature",
        "improvement",
        "fix",
        "break",
        "deprecation",
        "migration",
    }
    # Every value is a valid EntryType.
    for value in PREFIX_TO_TYPE.values():
        EntryType(value)


# --- markers -----------------------------------------------------------------


def test_has_no_changelog_marker_present() -> None:
    body = "intro\n==NO_CHANGELOG==\nfooter"
    assert has_no_changelog_marker(body)


def test_has_no_changelog_marker_absent() -> None:
    body = "intro without any markers"
    assert not has_no_changelog_marker(body)


def test_has_no_changelog_marker_inline_mention_is_not_a_marker() -> None:
    # An inline reference doesn't count: the marker must be a full line.
    body = "see ==NO_CHANGELOG== for details"
    assert not has_no_changelog_marker(body)


def test_has_no_changelog_marker_inside_html_comment_is_inert() -> None:
    """The PR template ships the marker inside an HTML comment so the
    contributor uncomments it deliberately. An inert (commented-out)
    marker MUST NOT trigger the bot."""
    body = "intro\n" "<!--\n" "Pick at most one:\n" "    ==NO_CHANGELOG==\n" "-->\n" "footer"
    assert not has_no_changelog_marker(body)


def test_extract_changelog_msg_inside_html_comment_is_inert() -> None:
    body = (
        "intro\n"
        "<!--\n"
        "Pick at most one:\n"
        "    ==CHANGELOG_MSG==\n"
        "    fake content\n"
        "    ==CHANGELOG_MSG==\n"
        "-->\n"
        "footer"
    )
    assert extract_changelog_msg(body) is None


def test_extract_changelog_msg_inside_fenced_code_is_inert() -> None:
    body = (
        "intro\n"
        "```markdown\n"
        "==CHANGELOG_MSG==\n"
        "doc example\n"
        "==CHANGELOG_MSG==\n"
        "```\n"
        "footer"
    )
    assert extract_changelog_msg(body) is None


def test_template_default_body_does_not_trigger_bot(tmp_path: Path) -> None:
    """The committed PR template, used as-is, must not trigger any
    side-effect from the bot (no NO_CHANGELOG label, no CHANGELOG_MSG
    extraction)."""
    template_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / ".github"
        / "PULL_REQUEST_TEMPLATE.md"
    )
    body = template_path.read_text(encoding="utf-8")
    assert not has_no_changelog_marker(body)
    assert extract_changelog_msg(body) is None


def test_extract_changelog_msg_present() -> None:
    body = (
        "intro\n"
        "==CHANGELOG_MSG==\n"
        "Add a new knob.\n"
        "More detail.\n"
        "==CHANGELOG_MSG==\n"
        "footer"
    )
    assert extract_changelog_msg(body) == "Add a new knob.\nMore detail."


def test_extract_changelog_msg_absent_returns_none() -> None:
    assert extract_changelog_msg("body without marker") is None


def test_extract_changelog_msg_unbalanced_raises() -> None:
    body = "==CHANGELOG_MSG==\nopen but never closed"
    with pytest.raises(BotError):
        extract_changelog_msg(body)


# --- slug generation ---------------------------------------------------------


def test_derive_slug_is_deterministic() -> None:
    assert derive_slug(123, "Add knob") == derive_slug(123, "Add knob")


def test_derive_slug_changes_with_content() -> None:
    assert derive_slug(123, "Add knob") != derive_slug(123, "Remove knob")


def test_derive_slug_changes_with_pr_number() -> None:
    assert derive_slug(123, "Add knob") != derive_slug(124, "Add knob")


def test_candidate_yaml_path_shape() -> None:
    path = candidate_yaml_path(298, "Some description")
    assert path.parent == Path("changelog/@unreleased")
    assert path.name.startswith("pr-298-")
    assert path.suffix == ".yml"


# --- YAML composition --------------------------------------------------------


def test_compose_yaml_structure() -> None:
    body = compose_yaml(
        entry_type="feature",
        description="Add a new knob.\nWith more detail.",
        pr_number=298,
    )
    assert "type: feature\n" in body
    assert "feature:\n" in body
    assert "  description: |\n" in body
    assert "    Add a new knob.\n" in body
    assert "    With more detail.\n" in body
    assert "https://github.com/aidanns/agent-auth/pull/298" in body
    # SPDX header up front so the file matches the project's convention.
    assert body.startswith("# SPDX-FileCopyrightText:")


def test_compose_yaml_rejects_empty_description() -> None:
    with pytest.raises(BotError):
        compose_yaml(entry_type="feature", description="   \n   ", pr_number=298)


def test_compose_yaml_passes_lint_schema(tmp_path: Path) -> None:
    """The bot's output MUST be parseable by `parse_entry_file` (the
    schema lint's gate)."""
    body = compose_yaml(
        entry_type="fix",
        description="Tighten the HMAC comparison so it is constant-time.",
        pr_number=298,
    )
    target = tmp_path / "pr-298-test.yml"
    target.write_text(body, encoding="utf-8")
    entry = parse_entry_file(target)
    assert entry.entry_type == EntryType.FIX
    assert "Tighten the HMAC" in entry.description


@pytest.mark.parametrize("entry_type", list(PREFIX_TO_TYPE.values()))
def test_compose_yaml_every_release_type_passes_lint(entry_type: str, tmp_path: Path) -> None:
    body = compose_yaml(
        entry_type=entry_type,
        description=f"A change of type {entry_type}.",
        pr_number=298,
    )
    target = tmp_path / f"pr-298-{entry_type}.yml"
    target.write_text(body, encoding="utf-8")
    entry = parse_entry_file(target)
    assert entry.entry_type.value == entry_type


# --- lockout -----------------------------------------------------------------


def test_is_locked_out_empty_history_is_not_a_lockout() -> None:
    """An empty `git log` (file never committed) means the bot can write
    its first version freely."""
    assert not is_locked_out([], BOT_IDENTITY)


def test_is_locked_out_only_bot_authors_is_not_a_lockout() -> None:
    assert not is_locked_out(
        [BOT_IDENTITY.name, BOT_IDENTITY.name],
        BOT_IDENTITY,
    )


def test_is_locked_out_any_human_author_locks_out() -> None:
    assert is_locked_out(
        [BOT_IDENTITY.name, "Alice Maintainer"],
        BOT_IDENTITY,
    )


# --- file_authors via a real git repo ----------------------------------------


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
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
def repo(tmp_path: Path) -> Iterator[Path]:
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "changelog" / "@unreleased").mkdir(parents=True)
    (tmp_path / "changelog" / "@unreleased" / ".gitkeep").write_text("", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    yield tmp_path


def test_file_authors_empty_for_uncommitted_path(repo: Path) -> None:
    relative = Path("changelog/@unreleased/pr-298-bot-deadbeef.yml")
    assert file_authors(repo, relative) == []


def test_file_authors_returns_each_commit(repo: Path) -> None:
    relative = Path("changelog/@unreleased/pr-298-bot-deadbeef.yml")
    target = repo / relative
    target.write_text("type: feature\n", encoding="utf-8")
    _git(
        repo,
        "add",
        str(relative),
        env={"GIT_AUTHOR_NAME": "agent-auth-changelog-bot[bot]"},
    )
    _git(
        repo,
        "commit",
        "-m",
        "bot v1",
        env={
            "GIT_AUTHOR_NAME": "agent-auth-changelog-bot[bot]",
            "GIT_AUTHOR_EMAIL": "bot@example.com",
            "GIT_COMMITTER_NAME": "agent-auth-changelog-bot[bot]",
            "GIT_COMMITTER_EMAIL": "bot@example.com",
        },
    )
    target.write_text("type: feature\n# edit\n", encoding="utf-8")
    _git(
        repo,
        "commit",
        "-am",
        "human edit",
        env={
            "GIT_AUTHOR_NAME": "Alice Maintainer",
            "GIT_AUTHOR_EMAIL": "alice@example.com",
            "GIT_COMMITTER_NAME": "Alice Maintainer",
            "GIT_COMMITTER_EMAIL": "alice@example.com",
        },
    )
    authors = file_authors(repo, relative)
    assert "agent-auth-changelog-bot[bot]" in authors
    assert "Alice Maintainer" in authors


# --- existing_pr_yaml_files --------------------------------------------------


def test_existing_pr_yaml_files_picks_correct_prefix(repo: Path) -> None:
    target_dir = repo / "changelog" / "@unreleased"
    (target_dir / "pr-298-foo.yml").write_text("type: feature\n", encoding="utf-8")
    (target_dir / "pr-300-bar.yml").write_text("type: feature\n", encoding="utf-8")
    matches = existing_pr_yaml_files(repo, 298)
    assert [p.name for p in matches] == ["pr-298-foo.yml"]


def test_existing_pr_yaml_files_empty_when_no_match(repo: Path) -> None:
    assert existing_pr_yaml_files(repo, 298) == []


# --- decision tree (dry-run) -------------------------------------------------


def _pr(
    *,
    title: str = "feature(ci): add knob",
    body: str = "",
    labels: tuple[str, ...] = (),
    head_ref: str = "feature-branch",
) -> PullRequest:
    return PullRequest(
        number=298,
        title=title,
        body=body,
        labels=labels,
        head_ref=head_ref,
    )


def _decide(
    *,
    pr: PullRequest,
    repo_root: Path,
) -> BotOutcome:
    return decide_and_act(
        pr=pr,
        repo="aidanns/agent-auth",
        repo_root=repo_root,
        bot_identity=BOT_IDENTITY,
        dry_run=True,
    )


def test_decide_no_changelog_marker_adds_label(repo: Path) -> None:
    pr = _pr(body="==NO_CHANGELOG==", labels=())
    outcome = _decide(pr=pr, repo_root=repo)
    assert outcome.action == "added-label"
    assert outcome.label == NO_CHANGELOG_LABEL


def test_decide_no_changelog_marker_with_label_already_set_skips(repo: Path) -> None:
    pr = _pr(body="==NO_CHANGELOG==", labels=(NO_CHANGELOG_LABEL,))
    outcome = _decide(pr=pr, repo_root=repo)
    assert outcome.action == "skipped"


def test_decide_existing_file_skips(repo: Path) -> None:
    target_dir = repo / "changelog" / "@unreleased"
    (target_dir / "pr-298-manual.yml").write_text(
        "type: feature\nfeature:\n  description: hi\n",
        encoding="utf-8",
    )
    pr = _pr(body="==CHANGELOG_MSG==\nshould-not-be-used\n==CHANGELOG_MSG==")
    outcome = _decide(pr=pr, repo_root=repo)
    assert outcome.action == "skipped"
    assert outcome.file is not None
    assert outcome.file.name == "pr-298-manual.yml"


def test_decide_no_markers_falls_through(repo: Path) -> None:
    pr = _pr(body="some prose without markers")
    outcome = _decide(pr=pr, repo_root=repo)
    assert outcome.action == "skipped"
    assert "changelog-lint will fail" in outcome.reason


def test_decide_chore_with_changelog_msg_posts_comment(repo: Path) -> None:
    pr = _pr(
        title="chore(deps): bump",
        body="==CHANGELOG_MSG==\nirrelevant\n==CHANGELOG_MSG==",
    )
    outcome = _decide(pr=pr, repo_root=repo)
    assert outcome.action == "posted-comment"


def test_decide_writes_yaml_when_marker_present(repo: Path) -> None:
    pr = _pr(
        title="feature(ci): add the bot",
        body=(
            "==CHANGELOG_MSG==\n"
            "Add the bot-mediated changelog authoring workflow.\n"
            "==CHANGELOG_MSG=="
        ),
    )
    outcome = _decide(pr=pr, repo_root=repo)
    assert outcome.action == "wrote-yaml"
    assert outcome.file is not None
    assert outcome.file.exists()
    parsed = parse_entry_file(outcome.file)
    assert parsed.entry_type == EntryType.FEATURE


def test_decide_idempotent_on_second_run(repo: Path) -> None:
    pr = _pr(
        title="fix(tokens): tighten hmac",
        body=(
            "==CHANGELOG_MSG==\n"
            "Tighten the HMAC comparison so it is constant-time.\n"
            "==CHANGELOG_MSG=="
        ),
    )
    first = _decide(pr=pr, repo_root=repo)
    assert first.action == "wrote-yaml"
    assert first.file is not None

    second = _decide(pr=pr, repo_root=repo)
    # Second arm: existing-file check fires (file is on-disk now), so
    # the action is "skipped" with reason mentioning the existing file.
    assert second.action == "skipped"


def test_decide_lockout_blocks_further_writes(repo: Path) -> None:
    """A human commit on the candidate file disables further bot writes."""
    pr = _pr(
        title="feature: add knob",
        body=("==CHANGELOG_MSG==\n" "Add the knob.\n" "==CHANGELOG_MSG=="),
    )
    candidate = repo / candidate_yaml_path(pr.number, "Add the knob.")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("type: feature\nfeature:\n  description: human\n", encoding="utf-8")
    _git(
        repo,
        "add",
        str(candidate.relative_to(repo)),
        env={"GIT_AUTHOR_NAME": "Alice Maintainer"},
    )
    _git(
        repo,
        "commit",
        "-m",
        "human authoring",
        env={
            "GIT_AUTHOR_NAME": "Alice Maintainer",
            "GIT_AUTHOR_EMAIL": "alice@example.com",
            "GIT_COMMITTER_NAME": "Alice Maintainer",
            "GIT_COMMITTER_EMAIL": "alice@example.com",
        },
    )
    # Remove the file (so the existing-file check doesn't shortcut us
    # before the lockout check).
    candidate.unlink()
    _git(
        repo,
        "commit",
        "-am",
        "remove for test",
        env={
            "GIT_AUTHOR_NAME": "Alice Maintainer",
            "GIT_AUTHOR_EMAIL": "alice@example.com",
            "GIT_COMMITTER_NAME": "Alice Maintainer",
            "GIT_COMMITTER_EMAIL": "alice@example.com",
        },
    )
    outcome = _decide(pr=pr, repo_root=repo)
    assert outcome.action == "skipped"
    assert "lockout" in outcome.reason
