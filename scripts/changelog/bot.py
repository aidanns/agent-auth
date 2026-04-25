# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Bot-mediated authoring for ``changelog/@unreleased/*.yml`` entries.

Invoked from ``.github/workflows/changelog-bot.yml`` on every
``pull_request: opened, edited, synchronize, unlabeled`` event. Reads
two optional markers from the PR description:

- ``==CHANGELOG_MSG==`` ... ``==CHANGELOG_MSG==`` — content becomes the
  ``description`` field of an auto-created changelog YAML if no entry
  exists for this PR.
- ``==NO_CHANGELOG==`` — adds the ``no changelog`` label to the PR;
  the changelog lint (``scripts/changelog/lint.py``) bypasses the
  changelog-file requirement when that label is present.

The decision tree is the four-arm table from the issue body:

01. ``==NO_CHANGELOG==`` present -> add the label, exit.
02. ``==NO_CHANGELOG==`` absent and the label was previously applied
    by the bot -> remove the label.
03. ``changelog/@unreleased/pr-<N>-*.yml`` already on the branch ->
    skip (manual or CLI-authored entry takes precedence).
04. ``==CHANGELOG_MSG==`` absent -> skip (the lint will fail; that's
    intentional fall-through).
05. ``==CHANGELOG_MSG==`` present -> compose a YAML, commit, push.

Reconciliation when a maintainer hand-edits the YAML is via a
**lockout**: if any commit touching the candidate file on the PR branch
has an author other than the bot identity, further bot edits are
suppressed for the lifetime of the PR. See ADR 0039.

The CLI surface is intentionally narrow:

    python scripts/changelog/bot.py --pr <N> [--repo OWNER/REPO]
                                             [--repo-root PATH]
                                             [--dry-run]

The workflow forwards ``--pr`` from the GitHub event payload. Local
dry-runs against a checked-out branch can pass ``--dry-run`` to skip
the ``git push``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

# Reuse the marker extractor from the #290 validator. The validator
# lives at repo-root ``scripts/`` (one level up from this module).
_REPO_ROOT_FROM_MODULE = Path(__file__).resolve().parent.parent.parent
_SCRIPTS_DIR = _REPO_ROOT_FROM_MODULE / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# The validator is named with a hyphen; load it via importlib so the
# dash doesn't confuse the import statement.
import importlib.util as _importlib_util  # noqa: E402

_VALIDATOR_PATH = _SCRIPTS_DIR / "validate-commit-msg-block.py"
_spec = _importlib_util.spec_from_file_location("validate_commit_msg_block", _VALIDATOR_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - import-time guard
    raise ImportError(f"cannot load validate-commit-msg-block.py from {_VALIDATOR_PATH}")
_validator = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_validator)
extract_block = _validator.extract_block
BlockMarkerError = _validator.BlockMarkerError


# --- Constants ---------------------------------------------------------------

#: Default GitHub App slug. The actor login GitHub assigns to App
#: commits is ``<slug>[bot]``. Override with ``--bot-login`` when a
#: maintainer renames the App.
DEFAULT_BOT_LOGIN = "agent-auth-changelog-bot[bot]"

#: PR-description markers (without surrounding ``==``).
CHANGELOG_MSG_MARKER = "CHANGELOG_MSG"
NO_CHANGELOG_MARKER = "NO_CHANGELOG"

#: Label applied/removed by the bot when ``==NO_CHANGELOG==`` toggles.
NO_CHANGELOG_LABEL = "no changelog"

#: Directory entries land in.
UNRELEASED_DIR = Path("changelog/@unreleased")

#: Mapping from PR-title prefix to YAML ``type:``. Mirrors ADR 0037
#: and the table in #298's issue body. ``chore`` is intentionally
#: omitted: a chore PR is expected to carry ``==NO_CHANGELOG==`` or
#: the label.
PREFIX_TO_TYPE: dict[str, str] = {
    # keep-sorted start
    "break": "break",
    "deprecation": "deprecation",
    "feature": "feature",
    "fix": "fix",
    "improvement": "improvement",
    "migration": "migration",
    # keep-sorted end
}

#: PR-title prefixes the lint accepts that the bot does not produce
#: a changelog for.
NON_CHANGELOG_PREFIXES = frozenset({"chore"})


# --- Public types ------------------------------------------------------------


class BotIdentity(NamedTuple):
    """Git identity used when the bot commits a generated YAML.

    Wraps the ``(name, email)`` pair so callers can't accidentally swap
    the two strings. ``login`` is the GitHub actor login (e.g.
    ``agent-auth-changelog-bot[bot]``) used to filter label / commit
    history events.
    """

    login: str
    name: str
    email: str


@dataclass(frozen=True)
class PullRequest:
    """Subset of the GitHub PR object the bot reads."""

    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    head_ref: str


class BotError(RuntimeError):
    """Raised for unrecoverable bot failures (bad PR title, bad markers)."""


# --- Outcome reporting -------------------------------------------------------


@dataclass(frozen=True)
class BotOutcome:
    """Structured result of one bot run.

    The CLI prints a short human-readable line; tests assert against
    the structured fields.
    """

    action: str  # one of: skipped, added-label, removed-label, wrote-yaml, posted-comment
    reason: str
    file: Path | None = None
    label: str | None = None


# --- PR-title prefix parsing -------------------------------------------------


def parse_pr_title_prefix(title: str) -> str:
    """Return the lower-cased Palantir-style prefix from ``title``.

    Accepts ``feature: ...``, ``feature(scope): ...``, etc. The PR-title
    lint already enforces the allowlist, so an unknown prefix here means
    the lint hasn't run yet — raise ``BotError`` so the bot exits and
    the contributor fixes the title first.
    """
    head, sep, _rest = title.partition(":")
    if not sep:
        raise BotError(f"PR title {title!r} does not match `<type>(<scope>)?: <subject>`")
    # Strip an optional ``(scope)`` suffix.
    prefix = head.split("(", 1)[0] if "(" in head else head
    prefix = prefix.strip().lower()
    if not prefix:
        raise BotError(f"PR title {title!r} has an empty prefix")
    return prefix


def map_prefix_to_type(prefix: str) -> str | None:
    """Map a PR-title prefix to a YAML ``type:``.

    Returns ``None`` for prefixes the bot deliberately does not author
    a changelog for (currently ``chore:``). Raises ``BotError`` for
    unknown prefixes — the PR-title lint should have rejected those.
    """
    if prefix in PREFIX_TO_TYPE:
        return PREFIX_TO_TYPE[prefix]
    if prefix in NON_CHANGELOG_PREFIXES:
        return None
    allowed = sorted({*PREFIX_TO_TYPE.keys(), *NON_CHANGELOG_PREFIXES})
    raise BotError(f"unknown PR-title prefix {prefix!r}; expected one of {allowed}")


# --- Marker extraction -------------------------------------------------------

#: HTML comments span multiple lines and are stripped before marker
#: detection so the PR template's example markers (which sit inside a
#: `<!-- ... -->` block until the contributor uncomments one) don't
#: trigger the bot. The same rule applies to GitHub-rendered Markdown:
#: a comment is invisible on the rendered PR and shouldn't count as a
#: marker. Fenced code blocks are stripped for the same reason — a
#: documentation example referencing the marker should not fire it.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)


def _strip_inactive_regions(body: str) -> str:
    """Return ``body`` with HTML comments and fenced code blocks removed.

    Used by both marker detectors so a marker mention inside a comment
    or a code fence (e.g. CONTRIBUTING.md examples copied into the PR
    body) does not trigger the bot.
    """
    body = _HTML_COMMENT_RE.sub("", body)
    body = _FENCED_CODE_RE.sub("", body)
    return body


def has_no_changelog_marker(body: str) -> bool:
    """Return True if the ``==NO_CHANGELOG==`` marker line is active.

    The marker is treated as a flag, not a fenced block: a single line
    of ``==NO_CHANGELOG==`` anywhere in the active body (HTML comments
    and fenced code blocks stripped first) switches the bot into
    label-only mode.
    """
    marker = f"=={NO_CHANGELOG_MARKER}=="
    stripped = _strip_inactive_regions(body)
    return any(line.strip() == marker for line in stripped.splitlines())


def extract_changelog_msg(body: str) -> str | None:
    """Return the contents of the ``==CHANGELOG_MSG==`` block, or None.

    Re-raises ``BotError`` when the markers are malformed (one open
    without a close, three or more markers). HTML comments and fenced
    code blocks are stripped before parsing, so the PR template's
    inert example markers (or a CONTRIBUTING.md example pasted into
    the body) do not count.
    """
    try:
        return extract_block(_strip_inactive_regions(body), CHANGELOG_MSG_MARKER)
    except BlockMarkerError as exc:
        raise BotError(str(exc)) from exc


# --- Slug + YAML composition -------------------------------------------------


def derive_slug(pr_number: int, description: str) -> str:
    """Derive a deterministic ``<slug>`` for the YAML filename.

    The slug only has to be unique within a single PR's filename and
    stable across re-runs on the same content (so the bot's
    idempotency check sees the same path). A short hash satisfies both
    properties and avoids the wordlist/license overhead of a friendlier
    scheme.
    """
    digest = hashlib.sha1(
        f"{pr_number}:{description}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    return f"bot-{digest[:8]}"


def candidate_yaml_path(pr_number: int, description: str) -> Path:
    """Return the path the bot would write for ``(pr_number, description)``."""
    slug = derive_slug(pr_number, description)
    return UNRELEASED_DIR / f"pr-{pr_number}-{slug}.yml"


def compose_yaml(*, entry_type: str, description: str, pr_number: int) -> str:
    """Render the YAML body the bot writes.

    Hand-rendered (rather than ``yaml.safe_dump``) so the file matches
    the project's existing layout: SPDX header, ``description: |``
    block scalar, and a single ``links:`` list entry pointing at the
    PR. PyYAML's default emitter would double-quote the description on
    every newline, which the project's ``mdformat``-styled fixtures do
    not.

    The description is normalised to:
    - end with a trailing newline (so the block scalar terminates
      cleanly),
    - have leading/trailing whitespace stripped from each line so a
      copy-paste from the PR editor doesn't carry trailing spaces.

    We do NOT escape ``description`` against YAML injection: a
    contributor with PR-edit access can already write any YAML they
    want. The bot's job is to render their content faithfully. The
    schema lint downstream rejects malformed YAML.
    """
    cleaned = "\n".join(line.rstrip() for line in description.strip().splitlines())
    if not cleaned:
        raise BotError("==CHANGELOG_MSG== block is empty after stripping whitespace")

    indented = "\n".join(f"    {line}" if line else "" for line in cleaned.splitlines())
    pr_link = f"https://github.com/aidanns/agent-auth/pull/{pr_number}"
    # REUSE-IgnoreStart -- the SPDX header strings below are written
    # to the generated YAML (not a declaration about this source
    # file). Without the ignore markers, REUSE reads the multi-line
    # Python string literal as a malformed
    # `SPDX-License-Identifier: MIT\n` declaration on this source.
    rendered = (
        "# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith\n"
        "#\n"
        "# SPDX-License-Identifier: MIT\n"
        "\n"
        f"type: {entry_type}\n"
        f"{entry_type}:\n"
        "  description: |\n"
        f"{indented}\n"
        "  links:\n"
        f"    - {pr_link}\n"
    )
    # REUSE-IgnoreEnd
    return rendered


# --- Lockout detection -------------------------------------------------------


def file_authors(repo_root: Path, relative_path: Path) -> list[str]:
    """Return the author names of every commit touching ``relative_path``.

    Empty list when the file has no history yet (never been committed
    on this branch). Order is youngest-first per ``git log``.
    """
    cmd = ["git", "log", "--format=%an", "--", str(relative_path)]
    try:
        completed = subprocess.run(
            cmd,
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BotError(f"`git log` failed for {relative_path}: {exc.stderr.strip()}") from exc
    return [line for line in completed.stdout.splitlines() if line.strip()]


def is_locked_out(authors: Sequence[str], bot_identity: BotIdentity) -> bool:
    """Return True if any author is not the bot identity.

    Empty ``authors`` (no commits on this file yet) is NOT a lockout —
    the file has never been written, so no human has had a chance to
    claim authorship. This handles the first-run case correctly.
    """
    if not authors:
        return False
    return any(author != bot_identity.name for author in authors)


# --- GitHub API helpers (via gh CLI) -----------------------------------------


def _gh_json(args: Sequence[str]) -> object:
    """Run ``gh api`` and parse stdout as JSON."""
    completed = subprocess.run(
        ["gh", "api", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def fetch_pull_request(repo: str, pr_number: int) -> PullRequest:
    """Fetch the PR object via ``gh api``."""
    payload = _gh_json([f"repos/{repo}/pulls/{pr_number}"])
    if not isinstance(payload, dict):
        raise BotError(f"unexpected /pulls/{pr_number} payload: {type(payload).__name__}")
    labels_raw = payload.get("labels", [])
    labels: tuple[str, ...] = tuple(
        label["name"] for label in labels_raw if isinstance(label, dict) and "name" in label
    )
    head = payload.get("head", {})
    head_ref = head.get("ref", "") if isinstance(head, dict) else ""
    return PullRequest(
        number=int(payload.get("number", pr_number)),
        title=str(payload.get("title", "")),
        body=str(payload.get("body") or ""),
        labels=labels,
        head_ref=head_ref,
    )


def label_was_applied_by_bot(
    repo: str,
    pr_number: int,
    label: str,
    bot_identity: BotIdentity,
) -> bool:
    """Return True if the most recent ``labeled`` event for ``label`` was the bot.

    A human can apply / remove the label themselves. The bot only
    removes the label when it sees a ``==NO_CHANGELOG==`` -> absent
    transition AND the previous application was its own. This avoids
    fighting a maintainer who applied the label manually.
    """
    events = _gh_json([f"repos/{repo}/issues/{pr_number}/events?per_page=100", "--paginate"])
    if not isinstance(events, list):
        return False
    last_actor: str | None = None
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("event") != "labeled":
            continue
        event_label = event.get("label", {})
        if not isinstance(event_label, dict) or event_label.get("name") != label:
            continue
        actor = event.get("actor", {})
        if isinstance(actor, dict):
            last_actor = actor.get("login")
    return last_actor == bot_identity.login


def add_label(repo: str, pr_number: int, label: str) -> None:
    """Add ``label`` to the PR if missing. Idempotent."""
    subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repo}/issues/{pr_number}/labels",
            "-f",
            f"labels[]={label}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def remove_label(repo: str, pr_number: int, label: str) -> None:
    """Remove ``label`` from the PR if present. Idempotent."""
    completed = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "DELETE",
            f"repos/{repo}/issues/{pr_number}/labels/{label}",
        ],
        capture_output=True,
        text=True,
    )
    # 404 is the "label was not present" case — idempotent success.
    # gh prints both 404 and other errors to stderr; only swallow the
    # not-present case (label-name 404 vs. some other failure).
    if (
        completed.returncode != 0
        and "Label does not exist" not in completed.stderr
        and '"status":"404"' not in completed.stderr
    ):
        raise BotError(f"failed to remove label {label!r}: {completed.stderr.strip()}")


def post_comment(repo: str, pr_number: int, body: str) -> None:
    """Post ``body`` as a PR comment. Idempotent against the bot's own history."""
    existing = _gh_json([f"repos/{repo}/issues/{pr_number}/comments?per_page=100", "--paginate"])
    if isinstance(existing, list):
        for comment in existing:
            if not isinstance(comment, dict):
                continue
            if comment.get("body", "").strip() == body.strip():
                return
    subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repo}/issues/{pr_number}/comments",
            "-f",
            f"body={body}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


# --- Git commit / push -------------------------------------------------------


def configure_git_identity(repo_root: Path, identity: BotIdentity) -> None:
    """Set ``user.name`` / ``user.email`` for the upcoming commit."""
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", identity.name],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", identity.email],
        check=True,
    )


def commit_and_push(
    repo_root: Path,
    relative_path: Path,
    head_ref: str,
    *,
    dry_run: bool,
    sign_off: bool = True,
) -> None:
    """Stage, commit (signed-off-by), and push the changelog YAML."""
    add = ["git", "-C", str(repo_root), "add", str(relative_path)]
    subprocess.run(add, check=True)

    commit = ["git", "-C", str(repo_root), "commit"]
    if sign_off:
        commit.append("-s")
    commit += ["-m", "chore(changelog): regenerate entry from PR body"]
    subprocess.run(commit, check=True)

    if dry_run:
        return
    subprocess.run(
        ["git", "-C", str(repo_root), "push", "origin", f"HEAD:{head_ref}"],
        check=True,
    )


# --- Existing-file detection -------------------------------------------------


def existing_pr_yaml_files(repo_root: Path, pr_number: int) -> list[Path]:
    """Return YAML files matching ``pr-<N>-*.yml`` for ``pr_number``."""
    target_dir = repo_root / UNRELEASED_DIR
    if not target_dir.is_dir():
        return []
    prefix = f"pr-{pr_number}-"
    return sorted(
        path
        for path in target_dir.iterdir()
        if path.is_file() and path.name.startswith(prefix) and path.suffix == ".yml"
    )


# --- Decision tree -----------------------------------------------------------


def decide_and_act(
    *,
    pr: PullRequest,
    repo: str,
    repo_root: Path,
    bot_identity: BotIdentity,
    dry_run: bool,
) -> BotOutcome:
    """Run the four-arm decision tree from the issue body.

    Returns a ``BotOutcome`` describing what was done. Side-effects
    (label changes, commits, comments) happen as part of the relevant
    branch.
    """
    # Arm 1: ==NO_CHANGELOG== present -> add label, exit.
    if has_no_changelog_marker(pr.body):
        if NO_CHANGELOG_LABEL not in pr.labels:
            if not dry_run:
                add_label(repo, pr.number, NO_CHANGELOG_LABEL)
            return BotOutcome(
                action="added-label",
                reason="==NO_CHANGELOG== present",
                label=NO_CHANGELOG_LABEL,
            )
        return BotOutcome(
            action="skipped",
            reason="==NO_CHANGELOG== present and label already set",
            label=NO_CHANGELOG_LABEL,
        )

    # Arm 2: marker absent + label present + bot applied it -> remove.
    # A human-applied label is preserved (the conjunction below is
    # deliberate — both predicates must hold for the bot to act).
    if NO_CHANGELOG_LABEL in pr.labels and label_was_applied_by_bot(
        repo, pr.number, NO_CHANGELOG_LABEL, bot_identity
    ):
        if not dry_run:
            remove_label(repo, pr.number, NO_CHANGELOG_LABEL)
        return BotOutcome(
            action="removed-label",
            reason="==NO_CHANGELOG== absent and bot previously applied label",
            label=NO_CHANGELOG_LABEL,
        )

    # Arm 3: file already exists -> skip.
    existing = existing_pr_yaml_files(repo_root, pr.number)
    if existing:
        return BotOutcome(
            action="skipped",
            reason=f"existing entry {existing[0].name} on branch",
            file=existing[0],
        )

    # Arm 4: ==CHANGELOG_MSG== absent -> skip (lint will fail later).
    description = extract_changelog_msg(pr.body)
    if description is None:
        return BotOutcome(
            action="skipped",
            reason="no markers and no entry; changelog-lint will fail",
        )

    # Arm 5: prefix mapping + chore comment.
    prefix = parse_pr_title_prefix(pr.title)
    entry_type = map_prefix_to_type(prefix)
    if entry_type is None:
        comment = (
            "Claude: `chore:` PRs don't generate a changelog entry. Add "
            "`==NO_CHANGELOG==` to the PR description (or apply the "
            f"`{NO_CHANGELOG_LABEL}` label) to silence the changelog "
            "lint."
        )
        if not dry_run:
            post_comment(repo, pr.number, comment)
        return BotOutcome(
            action="posted-comment",
            reason="chore: PR with ==CHANGELOG_MSG== but no opt-out marker",
        )

    # Compose the file. Lockout uses the candidate path so a re-run
    # finds the same history regardless of past content drift.
    candidate = candidate_yaml_path(pr.number, description)

    # Arm 6: lockout — any non-bot author on the file's history blocks.
    authors = file_authors(repo_root, candidate)
    if is_locked_out(authors, bot_identity):
        return BotOutcome(
            action="skipped",
            reason=(
                f"lockout: {candidate.name} has been edited by a human "
                f"({sorted(set(authors) - {bot_identity.name})!r})"
            ),
            file=repo_root / candidate,
        )

    body = compose_yaml(
        entry_type=entry_type,
        description=description,
        pr_number=pr.number,
    )

    target = repo_root / candidate
    target.parent.mkdir(parents=True, exist_ok=True)

    # Idempotency: if the on-disk file matches what we'd write, skip
    # the commit so the workflow re-fires don't churn the branch.
    if target.exists() and target.read_text(encoding="utf-8") == body:
        return BotOutcome(
            action="skipped",
            reason="file content already matches; nothing to commit",
            file=target,
        )

    target.write_text(body, encoding="utf-8")
    if not dry_run:
        configure_git_identity(repo_root, bot_identity)
        commit_and_push(
            repo_root,
            candidate,
            pr.head_ref,
            dry_run=False,
        )
    return BotOutcome(
        action="wrote-yaml",
        reason="composed entry from ==CHANGELOG_MSG==",
        file=target,
    )


# --- CLI ---------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Bot-mediated authoring for changelog/@unreleased/*.yml entries."),
    )
    parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="GitHub PR number.",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="GitHub repo in OWNER/REPO form (default: $GITHUB_REPOSITORY).",
    )
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("GITHUB_WORKSPACE", "."),
        help="Local path to the working tree (default: $GITHUB_WORKSPACE or `.`).",
    )
    parser.add_argument(
        "--bot-login",
        default=os.environ.get("CHANGELOG_BOT_LOGIN", DEFAULT_BOT_LOGIN),
        help=(
            "GitHub actor login for the App identity "
            f"(default: $CHANGELOG_BOT_LOGIN or {DEFAULT_BOT_LOGIN!r})."
        ),
    )
    parser.add_argument(
        "--bot-name",
        default=os.environ.get("CHANGELOG_BOT_NAME", DEFAULT_BOT_LOGIN),
        help=(
            "Git commit author name for the App identity "
            "(default: $CHANGELOG_BOT_NAME or the bot login)."
        ),
    )
    parser.add_argument(
        "--bot-email",
        default=os.environ.get(
            "CHANGELOG_BOT_EMAIL",
            f"{DEFAULT_BOT_LOGIN}@users.noreply.github.com",
        ),
        help=(
            "Git commit author email for the App identity (default: "
            "$CHANGELOG_BOT_EMAIL or `<login>@users.noreply.github.com`). "
            "GitHub-Apps style: `<numeric-id>+<login>@users.noreply.github.com`."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compose the YAML / decide actions but do not push or call "
            "GitHub APIs that mutate state."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if not args.repo:
        print(
            "changelog-bot: --repo (or $GITHUB_REPOSITORY) is required",
            file=sys.stderr,
        )
        return 2

    repo_root = Path(args.repo_root).resolve()
    bot_identity = BotIdentity(
        login=args.bot_login,
        name=args.bot_name,
        email=args.bot_email,
    )

    try:
        pr = fetch_pull_request(args.repo, args.pr)
        outcome = decide_and_act(
            pr=pr,
            repo=args.repo,
            repo_root=repo_root,
            bot_identity=bot_identity,
            dry_run=args.dry_run,
        )
    except BotError as exc:
        print(f"changelog-bot: {exc}", file=sys.stderr)
        return 1

    file_part = f" file={outcome.file}" if outcome.file else ""
    label_part = f" label={outcome.label}" if outcome.label else ""
    print(
        f"changelog-bot: action={outcome.action} reason={outcome.reason!r}"
        f"{file_part}{label_part}"
    )
    return 0


__all__ = [
    "BotError",
    "BotIdentity",
    "BotOutcome",
    "CHANGELOG_MSG_MARKER",
    "DEFAULT_BOT_LOGIN",
    "NON_CHANGELOG_PREFIXES",
    "NO_CHANGELOG_LABEL",
    "NO_CHANGELOG_MARKER",
    "PREFIX_TO_TYPE",
    "PullRequest",
    "UNRELEASED_DIR",
    "candidate_yaml_path",
    "compose_yaml",
    "decide_and_act",
    "derive_slug",
    "existing_pr_yaml_files",
    "extract_changelog_msg",
    "file_authors",
    "has_no_changelog_marker",
    "is_locked_out",
    "main",
    "map_prefix_to_type",
    "parse_pr_title_prefix",
]


if __name__ == "__main__":
    sys.exit(main())
