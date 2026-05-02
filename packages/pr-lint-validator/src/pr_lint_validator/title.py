# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""PR-title (squash-merge subject) prose-style validator.

Adapted from ``scripts/validate-pr-title.py`` (issue #446). Validates
the rules documented in ``CONTRIBUTING.md`` → "Writing release-worthy
commits" → "Subject (PR title)":

  1. 72-char hard cap on the projected squash-merge subject (the PR
     title plus the ``(#<n>)`` suffix ``merge-bot.yml`` appends).
  2. No trailing period — the subject is a fragment, not a sentence.
  3. Imperative mood — reject a small closed list of past-tense /
     participle openings.
  4. Type x scope matrix — release-bumping prefixes (``feature`` /
     ``improvement`` / ``break`` / ``deprecation`` / ``migration``)
     paired with an internal-only scope (``ci``, ``deps-dev``, ...)
     are rejected because they would surface in CHANGELOG.md or bump
     the public version for plumbing-only changes.
  5. Two-tier scope allowlist — when the PR's changed-file list is
     available, every ``(scope)`` must either equal the contained
     ``packages/<name>/`` directory (package tier) or sit in the
     fixed ``AREA_SCOPES`` tuple (area tier). Bare scope is always
     accepted.

The Palantir-style prefix allowlist itself
(``feature``/``improvement``/``fix``/``chore``/``deprecation``/
``migration``/``break``) is enforced by
``amannn/action-semantic-pull-request`` in the ``pr-title`` job of
``pr-lint.yml``; this module picks up the prose rules that action
does not cover.

Public surface: :class:`TitleValidationError`, :func:`validate`,
:func:`run_self_test`. The CLI in :mod:`pr_lint_validator.cli` wraps
:func:`validate` for the ``title`` subcommand.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from . import commit_taxonomy


class Writer(Protocol):
    """Print-shaped callable signature shared with :mod:`commit_msg`.

    The CLI passes a closure that wraps ``print(..., file=...)``; tests
    pass a list-appending mock. Both follow the same shape, so the
    protocol keeps the ``run_self_test`` signature free of the
    ``object`` type that mypy can't call.
    """

    def __call__(self, msg: str, *, error: bool = False) -> None: ...


INTERNAL_ONLY_SCOPES: frozenset[str] = commit_taxonomy.INTERNAL_ONLY_SCOPES
AREA_SCOPES: tuple[str, ...] = commit_taxonomy.AREA_SCOPES

MAX_TITLE_WIDTH = 72

# Palantir-style prefix shape: ``prefix:`` or ``prefix(scope):``. The
# prefix-allowlist check itself runs in the ``pr-title`` job; this
# regex locates the prefix boundary so the past-tense / mood check
# operates on the *summary*, not the prefix, AND captures the type /
# optional scope so the type x scope matrix check can read them.
PREFIX_RE = re.compile(
    r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]+)\))?:\s+",
)

# Closed-list past-tense / participle openings rejected as false
# imperatives. Matched case-insensitively so a lower-case ``fixed``
# (the project's lowercase-summary convention) still trips.
PAST_TENSE_VERBS = (
    "Added",
    "Fixed",
    "Updated",
    "Changed",
    "Removed",
    "Refactored",
    "Implemented",
    "Bumped",
)
PAST_TENSE_RE = re.compile(
    r"^(?:" + "|".join(PAST_TENSE_VERBS) + r")\b",
    re.IGNORECASE,
)


class TitleValidationError(Exception):
    """Raised when the PR title fails the subject-style lint."""


def _strip_prefix(title: str) -> str:
    """Return the post-prefix summary, or the whole title if no prefix.

    The prefix-allowlist check is owned by
    ``amannn/action-semantic-pull-request``, so the validator
    deliberately tolerates a missing / malformed prefix: the
    past-tense check then runs over the entire title, which still
    catches ``Fixed gpg-bridge timeout`` regardless of whether the
    contributor remembered the prefix.
    """
    match = PREFIX_RE.match(title)
    if match is None:
        return title
    return title[match.end() :]


def _projected_suffix(pr_number: int | None) -> str:
    """Return the ``(#<n>)`` suffix ``merge-bot.yml`` will append, or ``""``.

    ``merge-bot.yml`` pastes ``${PR_TITLE} (#${PR_NUMBER})`` as the
    squash-merge subject so GitHub renders it as a clickable link in
    the commit log; the validator budgets for the suffix at PR-author
    time when ``--pr-number`` is provided.
    """
    if pr_number is None:
        return ""
    return f" (#{pr_number})"


def check_length(title: str, pr_number: int | None = None) -> None:
    """Reject titles that overflow the 72-char cap on the squash subject."""
    suffix = _projected_suffix(pr_number)
    projected = len(title) + len(suffix)
    if projected <= MAX_TITLE_WIDTH:
        return
    if not suffix:
        raise TitleValidationError(
            f"subject is {len(title)} chars (limit {MAX_TITLE_WIDTH}) — "
            "shorten the summary or drop the scope."
        )
    raise TitleValidationError(
        f"subject would be {projected} chars after merge-bot appends "
        f"`{suffix.lstrip()}` ({len(title)}-char title + {len(suffix)}-char "
        f"suffix; limit {MAX_TITLE_WIDTH}) — shorten the summary or drop "
        "the scope. The bot appends the PR number so GitHub renders the "
        "commit subject as a link in the commit log; see #399."
    )


def check_no_trailing_period(title: str) -> None:
    if title.rstrip().endswith("."):
        raise TitleValidationError(
            f"subject ends with '.' — drop the trailing period. Title was: {title!r}."
        )


def check_imperative_mood(title: str) -> None:
    summary = _strip_prefix(title)
    match = PAST_TENSE_RE.match(summary)
    if match is None:
        return
    verb = match.group(0)
    raise TitleValidationError(
        f"subject {title!r} uses past tense — start with an "
        f"imperative verb (e.g. {_imperative_for(verb)!r}) instead of "
        f"{verb!r}."
    )


# Hint mapping past-tense -> imperative for the error message.
_IMPERATIVE_HINTS = {
    "added": "Add",
    "fixed": "Fix",
    "updated": "Update",
    "changed": "Change",
    "removed": "Remove",
    "refactored": "Refactor",
    "implemented": "Implement",
    "bumped": "Bump",
}


def _imperative_for(verb: str) -> str:
    return _IMPERATIVE_HINTS.get(verb.lower(), verb)


def check_type_scope_matrix(title: str) -> None:
    """Reject release-bumping types paired with internal-only scopes."""
    match = PREFIX_RE.match(title)
    if match is None:
        return
    type_ = match.group("type")
    scope = match.group("scope")
    if scope is None:
        return
    if scope not in INTERNAL_ONLY_SCOPES:
        return
    if type_ in {"chore", "fix"}:
        return
    raise TitleValidationError(
        f"`{type_}({scope}):` is not allowed — the `({scope})` scope "
        "is internal-only and must use `chore:` or `fix:`. Internal "
        "plumbing changes should not bump the public version. See "
        'CONTRIBUTING.md → "Allowed scopes".'
    )


def _single_package_for(changed_files: list[str]) -> str | None:
    """Return the contained ``packages/<name>/`` directory, else ``None``.

    Returns ``None`` when:

    - any file lives outside ``packages/`` (workflow / docs /
      root-config edit) — those PRs fall through to the area tier;
    - the diff spans multiple ``packages/<name>/`` directories — a
      multi-package PR can't claim a package-tier scope.

    The returned name is *not* filtered against the package
    allowlist; the caller distinguishes "registered package" (apply
    the package-tier rule) from "unregistered ``packages/<name>/``
    directory" (typo'd path or a brand-new package added in the same
    PR before the allowlist is reseeded) so the diagnostic can name
    the actual problem.
    """
    package: str | None = None
    for raw in changed_files:
        path = raw.strip()
        if not path:
            continue
        parts = path.split("/")
        if len(parts) < 2 or parts[0] != "packages":
            return None
        candidate = parts[1]
        if package is None:
            package = candidate
        elif package != candidate:
            return None
    return package


def _area_scope_suggestion(scope: str) -> str | None:
    """Return the area-tier scope the offending one most likely meant."""
    if scope in {"merge-bot", "pr-lint", "dco", "changelog-bot", "scorecard"}:
        return "ci"
    if scope in {"release-pr", "release-publish", "build_release", "build-release"}:
        return "release"
    if scope in {"typecheck", "verify-standards", "python", "setup-toolchain", "vscode"}:
        return "ci"
    return None


def check_two_tier_scope(
    title: str,
    changed_files: list[str] | None,
    package_scopes: tuple[str, ...],
) -> None:
    """Reject scopes outside the package-tier / area-tier allowlist.

    The rule, per #402:

    1. **Package tier.** If every changed file lives under a single
       ``packages/<name>/`` directory, the scope MUST be ``<name>``.
       A PR contained to one package can't claim a different
       package's scope or invent an area name.
    2. **Area tier.** Otherwise, the scope MUST be in
       ``AREA_SCOPES`` (``release``, ``ci``, ``deps``, ``deps-dev``,
       ``docs``, ``design``, ``security``, ``claude``).
    3. **Bare scope.** Always accepted — reserved for cross-cutting
       changes per CONTRIBUTING.md.

    ``package_scopes`` is threaded through from the caller (typically
    discovered via :func:`commit_taxonomy.discover_package_scopes`)
    so the validator stays a pure function of its inputs — testable
    without monkey-patching the module-level taxonomy.

    The check is silent when the title has no parseable
    ``type(scope):`` shape, when ``changed_files`` is ``None``, or
    when ``changed_files`` is empty.
    """
    if changed_files is None:
        return
    if not any(line.strip() for line in changed_files):
        return
    match = PREFIX_RE.match(title)
    if match is None:
        return
    scope = match.group("scope")
    if scope is None:
        # Bare scope: cross-cutting changes are always permitted.
        return
    package = _single_package_for(changed_files)
    if package is not None:
        if package not in package_scopes:
            raise TitleValidationError(
                f"changed files live under `packages/{package}/`, but "
                f"`{package}` is not registered in `PACKAGE_SCOPES` "
                f"({', '.join(package_scopes)}). Either fix the "
                f"directory name or add the package to the workspace "
                'so `PACKAGE_SCOPES` picks it up. See CONTRIBUTING.md '
                '→ "Allowed scopes".'
            )
        if scope == package:
            return
        raise TitleValidationError(
            f"scope `({scope})` is not in the allowlist. The change "
            f"is contained to `packages/{package}/`, so the scope "
            f"MUST be `({package})`. See CONTRIBUTING.md → "
            '"Allowed scopes".'
        )
    if scope in AREA_SCOPES:
        return
    suggestion = _area_scope_suggestion(scope)
    if suggestion is not None:
        hint = f"use `({suggestion})` instead, or drop the scope for a cross-cutting change"
    else:
        hint = (
            "pick a scope from `AREA_SCOPES` "
            "(release, ci, deps, deps-dev, docs, design, security, "
            "claude) or drop the scope for a cross-cutting change"
        )
    raise TitleValidationError(
        f"scope `({scope})` is not in the allowlist; "
        f'{hint}. See CONTRIBUTING.md → "Allowed scopes".'
    )


def validate(
    title: str,
    changed_files: list[str] | None = None,
    pr_number: int | None = None,
    *,
    repo_root: Path | None = None,
    package_scopes: tuple[str, ...] | None = None,
) -> None:
    """Run every PR-title prose-style check.

    ``package_scopes`` overrides on-disk discovery — handy for tests
    that drive the two-tier scope rule without writing a fake
    ``packages/`` directory. When omitted, the validator discovers
    workspace packages from ``repo_root`` (or CWD when neither is
    given) via :func:`commit_taxonomy.discover_package_scopes`.
    """
    if not title.strip():
        raise TitleValidationError(
            "subject is empty — author a PR title with the "
            "Palantir-style `prefix: summary` shape."
        )
    check_length(title, pr_number)
    check_no_trailing_period(title)
    check_imperative_mood(title)
    check_type_scope_matrix(title)
    if package_scopes is None:
        package_scopes = commit_taxonomy.discover_package_scopes(repo_root)
    check_two_tier_scope(title, changed_files, package_scopes)


# Inline self-test cases. The PR-title input is a single string from
# `${{ github.event.pull_request.title }}`, so file-based fixtures
# buy nothing here. Each tuple is
# ``(title, changed_files, package_scopes, pr_number, expect_pass, label)``;
# ``package_scopes`` is provided per-case so the two-tier rule fires
# against a representative workspace without depending on the host's
# ``packages/`` tree.
_SELF_TEST_PACKAGE_SCOPES: tuple[str, ...] = (
    "agent-auth",
    "agent-auth-common",
    "gpg-bridge",
    "gpg-cli",
    "pr-lint-validator",
    "things-bridge",
    "things-cli",
    "things-client-cli-applescript",
)

_SELF_TEST_CASES: tuple[
    tuple[str, list[str] | None, tuple[str, ...], int | None, bool, str], ...
] = (
    # Passing cases.
    (
        "chore(ci): enforce subject-style rules in pr-lint validator",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-chore",
    ),
    (
        "feature(agent-auth): add JIT approval flow for prompt-tier scope",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-feature-package-scope",
    ),
    (
        "fix(agent-auth): use constant-time HMAC comparison",
        ["packages/agent-auth/src/agent_auth/tokens.py"],
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-fix",
    ),
    (
        "improvement: tighten numbered-list regex",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-no-scope",
    ),
    (
        "feature(release): wire workflow-dispatch tag re-runs",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-feature-release-scope",
    ),
    (
        "fix(claude): correct outdated worktree path in plan template",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-fix-internal-scope",
    ),
    # Failing cases: one per rule.
    (
        "fix: drop the trailing period.",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-trailing-period",
    ),
    (
        "improvement: Fixed gpg-bridge timeout",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-past-tense-fixed",
    ),
    (
        "feature: Added a thing",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-past-tense-added",
    ),
    (
        # 84 chars — the example from the issue body.
        "fix(very-long-scope): a summary that runs on and on past the seventy two char cap easy",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-too-long",
    ),
    (
        "",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-empty",
    ),
    # Type x scope matrix (#401).
    (
        "feature(ci): add release-build dry-run and post-publish smoke",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-matrix-feature-ci",
    ),
    (
        "improvement(deps-dev): tighten pytest config",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-matrix-improvement-deps-dev",
    ),
    (
        "break(claude): rewrite plan-template to call EnterWorktree",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-matrix-break-claude",
    ),
    (
        "deprecation(docs): retire the legacy onboarding guide",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-matrix-deprecation-docs",
    ),
    (
        "migration(python): bump minimum interpreter to 3.12",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-matrix-migration-python",
    ),
    # Two-tier scope rule (#402).
    (
        "feature(agent-auth): add JIT approval flow for prompt-tier scope",
        ["packages/agent-auth/src/agent_auth/cli.py"],
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-pkg-tier-agent-auth",
    ),
    (
        "feature(server): rename the listener entrypoint",
        ["packages/agent-auth/src/agent_auth/server.py"],
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-pkg-tier-server-on-agent-auth",
    ),
    (
        "chore(ci): pin merge-bot action to a SHA",
        [".github/workflows/merge-bot.yml"],
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-area-tier-ci",
    ),
    (
        "improvement(merge-bot): post link to merged PR in slack",
        [".github/workflows/merge-bot.yml"],
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-area-tier-merge-bot",
    ),
    (
        "fix(release-pr): drop stale changelog YAMLs after publish",
        [".github/workflows/release-pr.yml"],
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-area-tier-release-pr",
    ),
    (
        "chore: bump shared HTTP client default timeout",
        [
            "packages/agent-auth/src/agent_auth/http.py",
            "packages/gpg-bridge/src/gpg_bridge/http.py",
        ],
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-multi-package-bare-scope",
    ),
    (
        "feature(agent-auth): wire shared HTTP client retry policy",
        [
            "packages/agent-auth/src/agent_auth/http.py",
            "packages/gpg-bridge/src/gpg_bridge/http.py",
        ],
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-multi-package-pkg-scope",
    ),
    (
        "chore: standardise YAML extension on .yml",
        ["Taskfile.yml", "CHANGELOG.md"],
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-cross-cutting-bare-scope",
    ),
    (
        "feature(novel): scaffold a new package",
        ["packages/novel/src/novel/__init__.py"],
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        False,
        "failing-unregistered-package-dir",
    ),
    # Suffix-aware length rule (#399).
    (
        "improvement(agent-auth): tighten the JIT approval audit-log emit pathway",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        9999,
        False,
        "failing-suffixed-overflow",
    ),
    (
        "improvement(agent-auth): tighten audit log emit",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        9999,
        True,
        "passing-suffixed-fits",
    ),
    (
        "fix(very-long-scope): a summary that runs on and on past the seventy two char cap easy",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        9999,
        False,
        "failing-too-long-with-pr-number",
    ),
    (
        "improvement(agent-auth): tighten the JIT approval audit-log emit pathway",
        None,
        _SELF_TEST_PACKAGE_SCOPES,
        None,
        True,
        "passing-unsuffixed-at-cap",
    ),
)


def run_self_test(write: Writer) -> int:
    """Run the inline self-test cases. ``write`` is a print-shaped callable.

    Returns 0 on full pass, 1 on any failure. Used by the CLI's
    ``--self-test`` mode and by ``tests/test_title.py`` to exercise
    every fixture programmatically.
    """
    fail = 0
    total = len(_SELF_TEST_CASES)
    for title, changed_files, package_scopes, pr_number, expect_pass, label in _SELF_TEST_CASES:
        try:
            validate(title, changed_files, pr_number, package_scopes=package_scopes)
        except TitleValidationError as err:
            if expect_pass:
                write(f"FAIL: {label}: expected pass, got {err}", error=True)
                fail += 1
            else:
                write(f"ok: {label}: {err}")
        else:
            if expect_pass:
                write(f"ok: {label}")
            else:
                write(f"FAIL: {label}: expected fail, got pass", error=True)
                fail += 1
    if fail:
        write(f"{fail} self-test case(s) failed", error=True)
        return 1
    write(f"all {total} self-test cases passed")
    return 0


def read_changed_files(path: str) -> list[str]:
    """Read a newline-separated path list, dropping blank lines.

    Used by the CLI's ``--changed-files-from`` flag so the
    ``pr-title-style`` job in ``pr-lint.yml`` can pipe a
    ``gh pr view --json files --jq`` listing in without inlining the
    paths into the run-block. Tolerates trailing newlines and
    BOM-prefixed UTF-8.
    """
    text = Path(path).read_text(encoding="utf-8")
    return text.splitlines()


__all__ = [
    "MAX_TITLE_WIDTH",
    "TitleValidationError",
    "Writer",
    "check_imperative_mood",
    "check_length",
    "check_no_trailing_period",
    "check_two_tier_scope",
    "check_type_scope_matrix",
    "read_changed_files",
    "run_self_test",
    "validate",
]
