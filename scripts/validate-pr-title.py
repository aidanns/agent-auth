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
import re
import sys

MAX_TITLE_WIDTH = 72

# Palantir-style prefix shape: `prefix:` or `prefix(scope):`. The
# prefix-allowlist check itself runs in the `pr-title` job
# (`amannn/action-semantic-pull-request`); this regex only locates the
# prefix boundary so the past-tense / mood check operates on the
# *summary*, not the prefix.
PREFIX_RE = re.compile(r"^[A-Za-z]+(?:\([^)]+\))?:\s+")

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


def validate(title: str) -> None:
    if not title.strip():
        raise TitleValidationError(
            "subject is empty — author a PR title with the "
            "Palantir-style `prefix: summary` shape."
        )
    check_length(title)
    check_no_trailing_period(title)
    check_imperative_mood(title)


# Inline self-test cases. The PR-title input is a single string from
# `${{ github.event.pull_request.title }}`, so file-based fixtures
# (the body validator's pattern) buy nothing here. Each tuple is
# (title, expect_pass, label) — `label` shows up in the self-test
# log so a regression points at the failing case immediately.
_SELF_TEST_CASES: tuple[tuple[str, bool, str], ...] = (
    # Passing cases: representative titles drawn from recent merged
    # PRs and the worked examples in CONTRIBUTING.md.
    (
        "chore(ci): enforce subject-style rules in pr-lint validator",
        True,
        "passing-chore",
    ),
    (
        "feature(ci): add release-build dry-run and post-publish asset smoke",
        True,
        "passing-feature",
    ),
    (
        "fix(tokens): use constant-time HMAC comparison",
        True,
        "passing-fix",
    ),
    (
        "improvement: tighten numbered-list regex",
        True,
        "passing-no-scope",
    ),
    # Failing cases: one per rule.
    (
        "fix: drop the trailing period.",
        False,
        "failing-trailing-period",
    ),
    (
        "improvement: Fixed gpg-bridge timeout",
        False,
        "failing-past-tense-fixed",
    ),
    (
        "feature: Added a thing",
        False,
        "failing-past-tense-added",
    ),
    (
        # 84 chars — the example from the issue body.
        "fix(very-long-scope): a summary that runs on and on past the seventy two char cap easy",
        False,
        "failing-too-long",
    ),
    (
        "",
        False,
        "failing-empty",
    ),
)


def _run_self_test() -> int:
    fail = 0
    for title, expect_pass, label in _SELF_TEST_CASES:
        try:
            validate(title)
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
    args = parser.parse_args(argv)
    if args.self_test:
        return _run_self_test()
    if args.title is None:
        parser.error("title is required unless --self-test is given")
    try:
        validate(args.title)
    except TitleValidationError as err:
        print(f"pr-title: {err}", file=sys.stderr)
        return 1
    print("pr-title: subject OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
