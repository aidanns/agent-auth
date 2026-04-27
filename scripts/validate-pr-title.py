#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT
#
# Validate the PR title (and therefore the squash-merge commit subject)
# against the prose-style rules documented in `CONTRIBUTING.md` →
# "Writing release-worthy commits" → "Subject (PR title)".
#
# The Palantir-style prefix allowlist (`feature` / `improvement` /
# `fix` / `chore` / `deprecation` / `migration` / `break`) is enforced
# separately by `amannn/action-semantic-pull-request` in the `pr-title`
# job of `.github/workflows/pr-lint.yml`. This validator picks up the
# *prose* rules that action does not cover:
#
#   1. Length: 72-char hard cap on the full subject (prefix + summary).
#      The 50-char soft target on the post-prefix summary documented in
#      CONTRIBUTING.md is *not* enforced (false-positive risk on long
#      scopes); only the hard cap is mechanical.
#   2. No trailing period: the subject is a fragment, not a sentence.
#   3. Imperative mood: reject subjects whose summary opens with a
#      narrow, closed list of past-tense / participle / gerund verbs
#      that are unambiguous false-imperatives in this project's style.
#      The list is intentionally tiny (`Added`, `Fixed`, `Updated`,
#      `Changed`, `Removed`, `Refactored`, `Implemented`, `Bumped`)
#      to avoid false positives. Other mood violations (`Wires`,
#      `Wiring`) are left to human review — there is no clean regex
#      that catches them without flagging legitimate present-tense
#      imperatives ending in `s` (`Address`, `Express`).
#   4. Type x scope matrix: reject release-bumping prefixes
#      (`feature` / `improvement` / `break` / `deprecation` /
#      `migration`) paired with a scope from
#      `commit_taxonomy.INTERNAL_ONLY_SCOPES` (e.g. `feature(ci):`,
#      `improvement(deps-dev):`). Internal plumbing changes must not
#      surface in CHANGELOG.md or bump the public version. See #401.
#   5. Two-tier scope allowlist: when the PR's changed-files list is
#      available, every `(scope)` must be either the *package* the
#      PR is contained to (single `packages/<name>/` directory in the
#      diff -> scope MUST equal `<name>`), or one of the fixed
#      `commit_taxonomy.AREA_SCOPES` for cross-cutting changes (CI,
#      release, deps, docs, etc.). This rejects long-tail invented
#      scopes like `(merge-bot)`, `(pr-lint)`, `(release-pr)`,
#      `(release-publish)`, `(build_release)` that drift past the
#      CONTRIBUTING.md allowlist. See #402.
#
# The validator runs in the `pr-title-style` job of
# `.github/workflows/pr-lint.yml`; the title is read via the env var
# `TITLE` to keep `${{ github.event.pull_request.title }}` out of the
# shell-expansion path (same injection-safety pattern as
# `pr-body-commit-msg`).
#
# Exits 0 on success, 1 with a one-line error and remediation hint on
# failure.

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

# Load the canonical PR-title taxonomy from
# ``scripts/lint/commit_taxonomy.py`` so the matrix check below shares
# one set of constants with the changelog tooling and CONTRIBUTING.md.
# Goes through ``importlib.util.spec_from_file_location`` rather than a
# bare ``import`` because this script lives at ``scripts/`` (not on the
# default ``sys.path``) and we don't want to mutate ``sys.path`` from a
# CI-invoked validator. The cached entry under
# ``sys.modules["commit_taxonomy"]`` is reused on second import so we
# share one module instance with ``version_logic`` / ``bot.py``,
# preserving identity contracts the changelog tests assert. Same
# pattern those modules use; see #405.
_TAXONOMY_PATH = Path(__file__).resolve().parent / "lint" / "commit_taxonomy.py"
_taxonomy = sys.modules.get("commit_taxonomy")
if _taxonomy is None:
    _spec = importlib.util.spec_from_file_location("commit_taxonomy", _TAXONOMY_PATH)
    if _spec is None or _spec.loader is None:  # pragma: no cover - import-time guard
        raise ImportError(f"cannot load commit_taxonomy from {_TAXONOMY_PATH}")
    _taxonomy = importlib.util.module_from_spec(_spec)
    sys.modules["commit_taxonomy"] = _taxonomy
    _spec.loader.exec_module(_taxonomy)
INTERNAL_ONLY_SCOPES: frozenset[str] = _taxonomy.INTERNAL_ONLY_SCOPES
PACKAGE_SCOPES: tuple[str, ...] = _taxonomy.PACKAGE_SCOPES
AREA_SCOPES: tuple[str, ...] = _taxonomy.AREA_SCOPES

MAX_TITLE_WIDTH = 72

# Palantir-style prefix shape: `prefix:` or `prefix(scope):`. The
# prefix-allowlist check itself runs in the `pr-title` job
# (`amannn/action-semantic-pull-request`); this regex locates the
# prefix boundary so the past-tense / mood check operates on the
# *summary*, not the prefix, AND captures the type / optional scope
# so the type x scope matrix check can read them. The `type` and
# `scope` groups stay tolerant of unknown values: prefix-allowlist
# enforcement lives in the upstream action, and this validator should
# not double-reject a malformed prefix that the prefix job has already
# flagged.
PREFIX_RE = re.compile(
    r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]+)\))?:\s+",
)

# Closed-list past-tense / participle openings rejected as false
# imperatives. Anchored to the start of the summary (after the prefix)
# and matched case-sensitively at the canonical capitalised form, since
# the project convention lowercases the post-prefix summary anyway —
# `Fixed` at the start of a summary is already two style violations
# (capitalised + past-tense). A lowercase `fixed` is matched too: the
# past-tense rule still applies even when the contributor obeys the
# capitalisation convention.
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
    `amannn/action-semantic-pull-request`, so this validator
    deliberately tolerates a missing / malformed prefix: the
    past-tense check then runs over the entire title, which still
    catches `Fixed gpg-bridge timeout` regardless of whether the
    contributor remembered the prefix.
    """
    match = PREFIX_RE.match(title)
    if match is None:
        return title
    return title[match.end() :]


def check_length(title: str) -> None:
    if len(title) > MAX_TITLE_WIDTH:
        raise TitleValidationError(
            f"subject is {len(title)} chars (limit {MAX_TITLE_WIDTH}) — "
            "shorten the summary or drop the scope."
        )


def check_no_trailing_period(title: str) -> None:
    if title.rstrip().endswith("."):
        raise TitleValidationError(
            f"subject ends with '.' — drop the trailing period. " f"Title was: {title!r}."
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


# Hint mapping past-tense -> imperative for the error message. Kept
# small and explicit — the validator's job is to point a contributor
# at the obvious fix, not to be a thesaurus.
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
    """Reject release-bumping types paired with internal-only scopes.

    Internal-only scopes (CI, dev-dep bumps, type-checker config,
    editor settings, agent prompts, design notes, in-tree docs) name
    plumbing surfaces that must not surface in CHANGELOG.md or bump
    the public version. ``commit_taxonomy.INTERNAL_ONLY_SCOPES`` is
    the canonical set; the matrix is documented in CONTRIBUTING.md
    § "Allowed scopes".

    The check is silent for titles that don't carry a parseable
    ``type(scope):`` shape — prefix-allowlist enforcement lives in
    the upstream ``amannn/action-semantic-pull-request`` step, and
    this validator should not double-fire on a malformed prefix.
    """
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
    # Quoting the bad combination back to the contributor first makes
    # the remediation obvious. The wording mirrors the worked example
    # in #401's issue body so a contributor who searched the issue
    # tracker for the error message lands on the matrix description.
    raise TitleValidationError(
        f"`{type_}({scope}):` is not allowed — the `({scope})` scope "
        "is internal-only and must use `chore:` or `fix:`. Internal "
        "plumbing changes should not bump the public version. See "
        'CONTRIBUTING.md → "Allowed scopes".'
    )


def _single_package_for(changed_files: list[str]) -> str | None:
    """Return the contained ``packages/<name>/`` directory, else ``None``.

    Path normalisation: ``gh pr view --json files --jq '.files[].path'``
    yields forward-slash POSIX paths regardless of runner OS, so we
    split on ``/`` rather than ``os.sep``. Empty / whitespace-only
    lines are skipped so a trailing newline in the file written by
    ``gh pr view`` does not collapse the check.

    The function returns ``None`` if any file lives outside
    ``packages/`` (a workflow tweak, a docs change, a root-level
    config edit) — those PRs fall through to the area-tier rule.
    Returns ``None`` if the diff spans multiple packages too: a
    multi-package PR can't claim a package-tier scope, and
    CONTRIBUTING.md's bare-scope-for-cross-cutting rule applies.

    The returned name is *not* filtered against ``PACKAGE_SCOPES``:
    the caller distinguishes "registered package" (apply the
    package-tier rule) from "unregistered ``packages/<name>/``
    directory" (typo'd path or a brand-new package added in the same
    PR before ``PACKAGE_SCOPES`` is reseeded) so the diagnostic can
    name the actual problem instead of falling through to the
    area-tier "pick from AREA_SCOPES" hint.
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
    """Return the area-tier scope the offending one most likely meant.

    The mapping covers the historical scope drift named in #402:
    ``(merge-bot)`` / ``(pr-lint)`` / ``(dco)`` and friends are
    GitHub Actions tweaks (``ci``); ``(release-pr)`` /
    ``(release-publish)`` / ``(build_release)`` belong under
    ``release``. The internal-only names that the type x scope
    matrix still recognises but the two-tier rule no longer treats
    as area scopes (``typecheck``, ``verify-standards``, ``python``,
    ``setup-toolchain``, ``vscode``) all map to ``ci`` — they name
    tooling / config surfaces wired into CI, so the closest
    first-class area is ``ci`` (a contributor adjusting a dev-dep
    pin underneath one of those names should pick ``deps-dev`` by
    hand). Returns ``None`` when no obvious mapping exists — the
    caller falls back to a generic remediation hint.
    """
    if scope in {"merge-bot", "pr-lint", "dco", "changelog-bot", "scorecard"}:
        return "ci"
    if scope in {"release-pr", "release-publish", "build_release", "build-release"}:
        return "release"
    if scope in {"typecheck", "verify-standards", "python", "setup-toolchain", "vscode"}:
        return "ci"
    return None


def check_two_tier_scope(title: str, changed_files: list[str] | None) -> None:
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

    The check is silent when:

    - the title has no parseable ``type(scope):`` shape (the upstream
      ``amannn/action-semantic-pull-request`` step owns prefix-shape
      enforcement);
    - ``changed_files`` is ``None`` (the validator was invoked locally
      without a PR's diff context — see CLI ``--changed-files-from``);
    - ``changed_files`` is an empty list (no files changed: nothing
      to anchor the package-tier check against, and area-tier would
      misfire on what is presumably a metadata-only edit).

    Multi-package PRs (the diff spans ``packages/X/`` AND
    ``packages/Y/``) fall through to the area-tier branch — and
    therefore must use a scope from ``AREA_SCOPES`` or go bare.
    Bare scope is the conservative answer per the issue body's
    "define behaviour explicitly" prompt: it matches CONTRIBUTING.md's
    existing "Bare scope is reserved for cross-cutting changes"
    convention without forcing a contributor to invent an area name.
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
        if package not in PACKAGE_SCOPES:
            # Single ``packages/<name>/`` directory found but not
            # registered: a typo in the path, or a new package added
            # in the same PR before ``PACKAGE_SCOPES`` is reseeded.
            # Surface the actual problem instead of falling through
            # to the area-tier "pick from AREA_SCOPES" hint, which is
            # wrong here.
            raise TitleValidationError(
                f"changed files live under `packages/{package}/`, but "
                f"`{package}` is not registered in `PACKAGE_SCOPES` "
                f"({', '.join(PACKAGE_SCOPES)}). Either fix the "
                f"directory name or add the package to the workspace "
                'so `PACKAGE_SCOPES` picks it up. See CONTRIBUTING.md '
                '→ "Allowed scopes".'
            )
        # Package-tier: scope MUST match the contained package.
        if scope == package:
            return
        raise TitleValidationError(
            f"scope `({scope})` is not in the allowlist. The change "
            f"is contained to `packages/{package}/`, so the scope "
            f"MUST be `({package})`. See CONTRIBUTING.md → "
            '"Allowed scopes".'
        )
    # Area-tier: scope MUST be one of the fixed area names.
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


def validate(title: str, changed_files: list[str] | None = None) -> None:
    if not title.strip():
        raise TitleValidationError(
            "subject is empty — author a PR title with the "
            "Palantir-style `prefix: summary` shape."
        )
    check_length(title)
    check_no_trailing_period(title)
    check_imperative_mood(title)
    check_type_scope_matrix(title)
    check_two_tier_scope(title, changed_files)


# Inline self-test cases. The PR-title input is a single string from
# `${{ github.event.pull_request.title }}`, so file-based fixtures
# (the body validator's pattern) buy nothing here. Each tuple is
# (title, changed_files, expect_pass, label):
#
# - ``changed_files`` is ``None`` when the case doesn't exercise the
#   two-tier scope rule (rule 5). Pre-#402 cases keep ``None`` and
#   stay focused on the rules they were written for; the #402 cases
#   each provide a representative diff.
# - ``label`` shows up in the self-test log so a regression points at
#   the failing case immediately.
_SELF_TEST_CASES: tuple[tuple[str, list[str] | None, bool, str], ...] = (
    # Passing cases: representative titles drawn from recent merged
    # PRs and the worked examples in CONTRIBUTING.md.
    (
        "chore(ci): enforce subject-style rules in pr-lint validator",
        None,
        True,
        "passing-chore",
    ),
    (
        # Package scope — release-bumping types are fine here; only
        # the internal-only scopes are restricted.
        "feature(agent-auth): add JIT approval flow for prompt-tier scope",
        None,
        True,
        "passing-feature-package-scope",
    ),
    (
        # Package-tier accept on `fix:` — exercises the `fix` prefix
        # alongside a realistic `packages/<name>/` diff. The original
        # fixture used `fix(tokens):` with no diff context, which the
        # two-tier rule would reject in real CI (``tokens`` is neither
        # a package nor in ``AREA_SCOPES``); pairing the title with a
        # representative ``packages/agent-auth/`` path keeps the
        # passing case honest.
        "fix(agent-auth): use constant-time HMAC comparison",
        ["packages/agent-auth/src/agent_auth/tokens.py"],
        True,
        "passing-fix",
    ),
    (
        "improvement: tighten numbered-list regex",
        None,
        True,
        "passing-no-scope",
    ),
    (
        # `release` is its own row in the matrix — release automation
        # changes can be user-visible and bump the version.
        "feature(release): wire workflow-dispatch tag re-runs",
        None,
        True,
        "passing-feature-release-scope",
    ),
    (
        # `fix` is allowed on internal-only scopes — this is the
        # escape hatch for a real bug in CI / dev-dep / docs surface.
        "fix(claude): correct outdated worktree path in plan template",
        None,
        True,
        "passing-fix-internal-scope",
    ),
    # Failing cases: one per rule.
    (
        "fix: drop the trailing period.",
        None,
        False,
        "failing-trailing-period",
    ),
    (
        "improvement: Fixed gpg-bridge timeout",
        None,
        False,
        "failing-past-tense-fixed",
    ),
    (
        "feature: Added a thing",
        None,
        False,
        "failing-past-tense-added",
    ),
    (
        # 84 chars — the example from the issue body.
        "fix(very-long-scope): a summary that runs on and on past the seventy two char cap easy",
        None,
        False,
        "failing-too-long",
    ),
    (
        "",
        None,
        False,
        "failing-empty",
    ),
    # Failing cases: type x scope matrix (#401). One fixture per
    # release-bumping type the matrix forbids on an internal-only
    # scope (`feature`, `improvement`, `break`, `deprecation`,
    # `migration`), each paired with a different internal-only scope
    # so a regression that special-cases one scope still trips a
    # neighbour. The full 5 release-bumping types x 10 internal-only
    # scopes = 50 combinations all share one code path (membership
    # lookups on two frozensets), so exhaustive enumeration would be
    # churn rather than coverage.
    (
        "feature(ci): add release-build dry-run and post-publish smoke",
        None,
        False,
        "failing-matrix-feature-ci",
    ),
    (
        "improvement(deps-dev): tighten pytest config",
        None,
        False,
        "failing-matrix-improvement-deps-dev",
    ),
    (
        "break(claude): rewrite plan-template to call EnterWorktree",
        None,
        False,
        "failing-matrix-break-claude",
    ),
    (
        "deprecation(docs): retire the legacy onboarding guide",
        None,
        False,
        "failing-matrix-deprecation-docs",
    ),
    (
        "migration(python): bump minimum interpreter to 3.12",
        None,
        False,
        "failing-matrix-migration-python",
    ),
    # Two-tier scope rule (#402). The package-tier branch fires when
    # every changed file lives under a single ``packages/<name>/``
    # directory; the area-tier branch is the fallback for everything
    # else; bare scope is always accepted (cross-cutting).
    (
        # Package-tier accept: scope matches the contained package.
        "feature(agent-auth): add JIT approval flow for prompt-tier scope",
        ["packages/agent-auth/src/agent_auth/cli.py"],
        True,
        "passing-pkg-tier-agent-auth",
    ),
    (
        # Package-tier reject: PR is contained to packages/agent-auth/
        # but claims a fictional `(server)` scope.
        "feature(server): rename the listener entrypoint",
        ["packages/agent-auth/src/agent_auth/server.py"],
        False,
        "failing-pkg-tier-server-on-agent-auth",
    ),
    (
        # Area-tier accept: workflow tweak under (ci).
        "chore(ci): pin merge-bot action to a SHA",
        [".github/workflows/merge-bot.yml"],
        True,
        "passing-area-tier-ci",
    ),
    (
        # Area-tier reject: `(merge-bot)` is the historical drift the
        # issue body calls out — the validator must point at `(ci)`.
        "improvement(merge-bot): post link to merged PR in slack",
        [".github/workflows/merge-bot.yml"],
        False,
        "failing-area-tier-merge-bot",
    ),
    (
        # Area-tier reject: `(release-pr)` is another historical drift
        # — the validator points at `(release)`.
        "fix(release-pr): drop stale changelog YAMLs after publish",
        [".github/workflows/release-pr.yml"],
        False,
        "failing-area-tier-release-pr",
    ),
    (
        # Multi-package fallback: PR spans two packages -> falls
        # through to area-tier; bare scope is accepted.
        "chore: bump shared HTTP client default timeout",
        [
            "packages/agent-auth/src/agent_auth/http.py",
            "packages/gpg-bridge/src/gpg_bridge/http.py",
        ],
        True,
        "passing-multi-package-bare-scope",
    ),
    (
        # Multi-package reject: a PR touching two packages cannot
        # claim either package's name as its scope — once the diff
        # spans both, the package-tier rule no longer applies and
        # the scope must come from ``AREA_SCOPES`` (or be dropped).
        # Symmetric with ``passing-multi-package-bare-scope``: that
        # fixture proves bare scope is accepted, this one proves a
        # package-named scope is not.
        "feature(agent-auth): wire shared HTTP client retry policy",
        [
            "packages/agent-auth/src/agent_auth/http.py",
            "packages/gpg-bridge/src/gpg_bridge/http.py",
        ],
        False,
        "failing-multi-package-pkg-scope",
    ),
    (
        # Cross-cutting changes (root config, docs) accept bare scope.
        "chore: standardise YAML extension on .yml",
        ["Taskfile.yml", "CHANGELOG.md"],
        True,
        "passing-cross-cutting-bare-scope",
    ),
    (
        # Unregistered ``packages/<name>/`` directory: the diff is
        # contained to one package directory but the name is not in
        # ``PACKAGE_SCOPES`` (a typo'd path, or a brand-new package
        # added in the same PR before discovery is reseeded). The
        # validator names the actual problem instead of falling
        # through to the area-tier "pick from AREA_SCOPES" hint.
        "feature(novel): scaffold a new package",
        ["packages/novel/src/novel/__init__.py"],
        False,
        "failing-unregistered-package-dir",
    ),
)


def _run_self_test() -> int:
    fail = 0
    for title, changed_files, expect_pass, label in _SELF_TEST_CASES:
        try:
            validate(title, changed_files)
        except TitleValidationError as err:
            if expect_pass:
                print(f"FAIL: {label}: expected pass, got {err}", file=sys.stderr)
                fail += 1
            else:
                print(f"ok: {label}: {err}")
        else:
            if expect_pass:
                print(f"ok: {label}")
            else:
                print(f"FAIL: {label}: expected fail, got pass", file=sys.stderr)
                fail += 1
    if fail:
        print(f"{fail} self-test case(s) failed", file=sys.stderr)
        return 1
    print(f"all {len(_SELF_TEST_CASES)} self-test cases passed")
    return 0


def _read_changed_files(path: str) -> list[str]:
    """Read a newline-separated path list, dropping blank lines.

    Used by the ``--changed-files-from`` flag so the
    ``pr-title-style`` job in ``pr-lint.yml`` can pipe a
    ``gh pr view --json files --jq`` listing in without inlining the
    paths into the run-block (and dragging shell expansion into the
    file-name path). The reader tolerates trailing newlines and
    BOM-prefixed UTF-8 since both happen on GitHub Actions runners.
    """
    text = Path(path).read_text(encoding="utf-8")
    return text.splitlines()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the PR title (squash-merge commit subject) against "
            "CONTRIBUTING.md → 'Writing release-worthy commits' → "
            "'Subject (PR title)' prose rules."
        )
    )
    parser.add_argument(
        "title",
        nargs="?",
        default=None,
        help="The PR title to validate (the full subject including prefix).",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the inline self-test cases instead of validating a title. "
            "Used by the `pr-title-self-test` job in pr-lint.yml so a "
            "regression in the validator surfaces immediately."
        ),
    )
    parser.add_argument(
        "--changed-files-from",
        default=None,
        metavar="PATH",
        help=(
            "Path to a newline-separated list of files changed in the PR. "
            "When provided, the two-tier scope rule (#402) runs against the "
            "diff: a PR contained to a single `packages/<name>/` directory "
            "must use `(<name>)` as the scope; otherwise the scope must be "
            "in `commit_taxonomy.AREA_SCOPES` or be omitted. The "
            "`pr-title-style` job in pr-lint.yml writes the list via "
            "`gh pr view --json files --jq '.files[].path'`."
        ),
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return _run_self_test()
    if args.title is None:
        parser.error("title is required unless --self-test is given")
    changed_files: list[str] | None = None
    if args.changed_files_from is not None:
        changed_files = _read_changed_files(args.changed_files_from)
    try:
        validate(args.title, changed_files)
    except TitleValidationError as err:
        print(f"pr-title: {err}", file=sys.stderr)
        return 1
    print("pr-title: subject OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
