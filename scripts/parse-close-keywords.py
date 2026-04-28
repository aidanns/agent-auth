#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT
#
# Parse a commit body for GitHub auto-close keyword references and emit
# the same-repo issue numbers to stdout (one per line). Cross-repo
# references go to stderr as `::notice::` lines so they surface in the
# workflow log without polluting the stdout stream the merge-bot loops
# over.
#
# Used by `.github/workflows/merge-bot.yml` to close linked issues
# after the squash-merge lands. GitHub's auto-close-on-`Closes #N` does
# not fire for App-token-mediated `PUT /pulls/{n}/merge` calls (issue
# #429); the bot reads the body it pasted, parses it for auto-close
# references, and calls `PATCH /repos/.../issues/{N}` itself.
#
# Keyword set matches GitHub's UI auto-closer:
#   closes / closed / closing
#   fix    / fixed   / fixing  / fixes
#   resolve / resolved / resolving / resolves
# Case-insensitive. Same-repo (`#N`) and cross-repo
# (`owner/repo#N`) reference shapes are both recognised. A trailing
# colon (`Closes:` — git-trailer form) is accepted in addition to the
# bare keyword. Punctuation after the issue number (`Closes #N.`) is
# tolerated.
#
# Position-independence: matches anywhere in the body, not only in the
# trailer block, to mirror GitHub's UI behaviour. The validator's
# `GITHUB_KEYWORD_RE` is anchored at line start for *validation*; this
# script's concern is *auto-close matching* — a different question.
#
# GitHub-UI-parity nuances pinned by the test suite (intentional):
#   * Comma-separated `Closes #1, #2, and #3` matches `#1` only — the
#     matcher requires a keyword before each `#N`. Contributors who
#     want all of #1/#2/#3 closed must repeat the keyword
#     (`Closes #1\nCloses #2\nCloses #3`). GitHub's UI behaves the
#     same way.
#   * Any in-body `Closes #N` mention closes the issue, regardless of
#     leading context. `Will close #100 once we ship` does close #100;
#     `did not close #100` also closes #100. GitHub's UI behaves the
#     same way. Authors should therefore avoid placing future-work
#     `Closes #N` references inside the `==COMMIT_MSG==` block.
#
# CLI surface:
#   python3 scripts/parse-close-keywords.py <body-file>
#
# Exits 0 on success. Same-repo issue numbers go to stdout, one per
# line, deduplicated and in first-seen order. Cross-repo references
# go to stderr. Empty input or a body with no auto-close references
# is success with empty stdout.

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import NewType

# Newtype so the helper APIs read clearly: an `IssueNumber` is the
# integer portion of `#N` extracted from the body. Distinct from a PR
# number even though both are integers in GitHub's URL space.
IssueNumber = NewType("IssueNumber", int)

# GitHub's UI auto-closer recognises three keyword stems with three
# inflections each (the issue body lists them explicitly). `fix` is
# the four-form outlier: `fix` / `fixes` / `fixed` / `fixing`. Stored
# as a frozenset so membership tests are constant-time and the set
# can't be mutated at import time.
AUTO_CLOSE_KEYWORDS: frozenset[str] = frozenset(
    {
        "close",
        "closes",
        "closed",
        "closing",
        "fix",
        "fixes",
        "fixed",
        "fixing",
        "resolve",
        "resolves",
        "resolved",
        "resolving",
    }
)

# A reference is a keyword from `AUTO_CLOSE_KEYWORDS`, optionally
# followed by a `:` (git-trailer form), a run of whitespace, then either
# `#N` (same-repo) or `owner/repo#N` (cross-repo). The keyword must sit
# at a word boundary so prose like "the fixes are landing" doesn't
# match without a `#N`. Trailing punctuation on the reference (`#N.` —
# common in the validator's GITHUB_KEYWORD_RE shape) is consumed by the
# `[.,!?;:]?` non-capturing tail; the issue number itself is what we
# capture.
#
# Group `repo` captures `owner/repo` for cross-repo references; absent
# for same-repo. Group `n` captures the integer issue number.
_KEYWORD_GROUP = "|".join(re.escape(kw) for kw in sorted(AUTO_CLOSE_KEYWORDS))
REFERENCE_RE = re.compile(
    rf"\b(?:{_KEYWORD_GROUP}):?\s+"
    r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?"
    r"#(?P<n>\d+)"
    r"[.,!?;:]?",
    flags=re.IGNORECASE,
)


# HTML comments (`<!-- ... -->`) inside the ==COMMIT_MSG== block
# round-trip into the squash commit body as-is — the extractor
# preserves them deliberately (see test_extract_block_preserves_html_comments_inside_block).
# That means template scaffolding comments containing the word
# `Closes` (e.g. the example bullet "`Closes #N` (no colon) is also
# accepted") would otherwise produce false-positive auto-close
# matches if a contributor failed to delete them. Strip comments
# before scanning — same defensive shape the validator uses for
# linting (`strip_html_comments`), but applied here for the
# auto-close-matching concern. Non-greedy `.*?` with `re.DOTALL` so
# multi-line comments are handled, and so a malformed `<!--` with
# no closing `-->` doesn't eat the rest of the body.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", flags=re.DOTALL)


def _strip_html_comments(body: str) -> str:
    """Return `body` with `<!-- ... -->` comments removed."""
    return HTML_COMMENT_RE.sub("", body)


def find_same_repo_issue_numbers(body: str) -> list[IssueNumber]:
    """Return same-repo issue numbers referenced via auto-close keywords.

    Order is first-seen; duplicates are collapsed (a body with
    `Closes #1\\nCloses #1` returns `[1]`). Cross-repo references are
    *not* returned — caller can enumerate them via
    `find_cross_repo_references` when surfacing skip notices.
    """
    body = _strip_html_comments(body)
    seen: set[int] = set()
    ordered: list[IssueNumber] = []
    for match in REFERENCE_RE.finditer(body):
        if match.group("repo"):
            # Cross-repo — skipped by this helper. The dedicated
            # cross-repo enumerator returns these.
            continue
        n = int(match.group("n"))
        if n in seen:
            continue
        seen.add(n)
        ordered.append(IssueNumber(n))
    return ordered


def find_cross_repo_references(body: str) -> list[str]:
    """Return cross-repo references in `owner/repo#N` form, first-seen order."""
    body = _strip_html_comments(body)
    seen: set[str] = set()
    ordered: list[str] = []
    for match in REFERENCE_RE.finditer(body):
        repo = match.group("repo")
        if not repo:
            continue
        ref = f"{repo}#{match.group('n')}"
        if ref in seen:
            continue
        seen.add(ref)
        ordered.append(ref)
    return ordered


def emit(
    same_repo: Iterable[IssueNumber],
    cross_repo: Iterable[str],
    stdout: object,
    stderr: object,
) -> None:
    """Write the parsed references to the given streams.

    Same-repo numbers go one-per-line to `stdout`; the merge-bot
    workflow consumes that stream via `mapfile`. Cross-repo refs go
    to `stderr` as GitHub Actions `::notice::` lines so they surface
    in the run output and a maintainer can close them by hand.
    """
    for n in same_repo:
        print(int(n), file=stdout)  # type: ignore[call-overload]
    for ref in cross_repo:
        print(
            f"::notice::Skipping cross-repo issue reference {ref}; "
            "merge-bot's installation token is not scoped to other repos.",
            file=stderr,  # type: ignore[call-overload]
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Parse a commit body for GitHub auto-close keyword "
            "references. Emits same-repo issue numbers to stdout "
            "(one per line); cross-repo references go to stderr."
        )
    )
    parser.add_argument(
        "body_path",
        type=Path,
        help="Path to a file containing the commit body text.",
    )
    args = parser.parse_args(argv)
    body = args.body_path.read_text(encoding="utf-8")
    same_repo = find_same_repo_issue_numbers(body)
    cross_repo = find_cross_repo_references(body)
    emit(same_repo, cross_repo, sys.stdout, sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
