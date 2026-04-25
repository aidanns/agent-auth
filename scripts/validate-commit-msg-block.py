#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT
#
# Validate the `==COMMIT_MSG==` block in a PR body against the conventions
# described in `CONTRIBUTING.md` § "Writing PRs" and ADR 0037.
#
# Rules:
#   1. Exactly one `==COMMIT_MSG==` … `==COMMIT_MSG==` block.
#   2. Every non-empty line in the block wraps at <= 72 chars.
#   3. No markdown headings (`#`), bullet lists (`-`, `*`, `+`),
#      numbered lists (`<n>.`, `<n>)`), or task checkboxes
#      (`- [ ]`, `- [x]`) inside the block.
#   4. If a `BREAKING CHANGE:` footer appears, it sits on the last
#      non-`Signed-off-by:` line.
#   5. Every trailer line (`Closes`, `Co-authored-by`, `Signed-off-by`,
#      and any other `Token: value` shaped line in the trailer block)
#      parses per git-trailer format.
#   6. At least one `Signed-off-by:` trailer is present (DCO).
#      The merge bot (#291) authors no commits and pastes the block
#      verbatim as the squash-merge body, so the trailer must already
#      sit inside the block — otherwise the squash commit lands on
#      `main` without DCO and the post-merge `dco` workflow goes red.
#      The DCO workflow checks per-PR-commit trailers; this rule
#      covers the *body* the bot will paste.
#
# Exits 0 on success, 1 with a human-readable error on failure. Reads
# the PR body from a file path given as argv[1].
#
# Library API: this module exposes `extract_block(body: str) -> str` and
# `validate(body: str) -> None` for callers that want to reuse the
# parser without re-implementing the regex. `scripts/extract-commit-msg-
# block.py` (used by the merge bot) imports `extract_block`.

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from pathlib import Path

MARKER = "==COMMIT_MSG=="
MAX_LINE_WIDTH = 72

# A git-trailer line is `Token: value` where the token is RFC 5322-ish:
# letters, digits, hyphens (no whitespace).
TRAILER_RE = re.compile(r"^([A-Za-z0-9-]+):[ \t]+\S.*$")

# GitHub-keyword closes/fixes lines (e.g. `Closes #123`) are accepted in
# the trailer block in addition to true `Token: value` trailers, because
# project convention has historically used the no-colon form (see the
# `Closes #N` examples in CHANGELOG.md). Token must be one of the
# recognised closing keywords; the value is the issue/PR reference.
GITHUB_KEYWORD_RE = re.compile(
    r"^(Closes|Fixes|Resolves)\s+(#\d+|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+)\.?$"
)

# Recognised trailer tokens in this project. Other tokens parse as
# trailers structurally but warrant a stricter check (we want to fail
# closed on typos like `Cosed: #1` — see is_trailer_token).
KNOWN_TRAILER_TOKENS = frozenset(
    {
        "Closes",
        "Co-authored-by",
        "Signed-off-by",
        "Reported-by",
        "Reviewed-by",
        "Tested-by",
        "Acked-by",
        "Refs",
        "Fixes",
        "BREAKING-CHANGE",
    }
)

# Patterns that must NOT appear inside the block (rule 3).
DISALLOWED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("markdown heading", re.compile(r"^#{1,6}\s")),
    ("task checkbox", re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s")),
    ("bullet list item", re.compile(r"^\s*[-*+]\s+\S")),
    ("numbered list item", re.compile(r"^\s*\d+[.)]\s+\S")),
]

# Comment / instruction lines the contributor may leave behind by
# accident from the PR template. These are stripped from the block
# before validation so the template's own scaffolding doesn't fail
# the lint, but a non-empty body must remain after stripping.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class ValidationError(Exception):
    """Raised when the PR body fails the commit-msg block lint."""


def extract_block(body: str) -> str:
    """Return the contents between the two `==COMMIT_MSG==` markers.

    Raises ValidationError if the block is missing or appears more or
    fewer than twice.
    """
    occurrences = [i for i, line in enumerate(body.splitlines()) if line.strip() == MARKER]
    if len(occurrences) == 0:
        raise ValidationError(
            f"PR body is missing the `{MARKER}` block. " "See .github/PULL_REQUEST_TEMPLATE.md."
        )
    if len(occurrences) == 1:
        raise ValidationError(
            f"PR body has only one `{MARKER}` marker; " "the block must be opened and closed."
        )
    if len(occurrences) > 2:
        raise ValidationError(
            f"PR body has {len(occurrences)} `{MARKER}` markers; "
            "exactly one block (two markers) is required."
        )
    lines = body.splitlines()
    start, end = occurrences
    return "\n".join(lines[start + 1 : end])


def strip_html_comments(text: str) -> str:
    """Strip `<!-- … -->` comments so template scaffolding does not lint."""
    return HTML_COMMENT_RE.sub("", text)


def block_lines(block: str) -> list[str]:
    """Return the meaningful lines of the block (comments stripped)."""
    stripped = strip_html_comments(block)
    # Drop fully blank lines from the head and tail so a leading/trailing
    # empty line in the template doesn't count as content.
    lines = stripped.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def check_non_empty(lines: Iterable[str]) -> None:
    if not any(line.strip() for line in lines):
        raise ValidationError(
            f"`{MARKER}` block is empty after stripping HTML comments. "
            "Author the squash-merge commit body inside the block."
        )


def check_line_width(lines: Iterable[str]) -> None:
    over = [(idx, line) for idx, line in enumerate(lines, start=1) if len(line) > MAX_LINE_WIDTH]
    if over:
        details = "\n".join(f"  line {idx} ({len(line)} chars): {line!r}" for idx, line in over)
        raise ValidationError(
            f"`{MARKER}` block has lines wider than " f"{MAX_LINE_WIDTH} chars:\n{details}"
        )


def check_no_markdown(lines: Iterable[str]) -> None:
    findings: list[str] = []
    for idx, line in enumerate(lines, start=1):
        for label, pattern in DISALLOWED_PATTERNS:
            if pattern.match(line):
                findings.append(f"  line {idx} ({label}): {line!r}")
                break
    if findings:
        details = "\n".join(findings)
        raise ValidationError(
            f"`{MARKER}` block contains markdown formatting that does "
            f"not belong in a git commit body:\n{details}\n"
            "Use prose paragraphs only; trailers go at the end."
        )


def is_trailer_token(token: str) -> bool:
    """Return True if `token` is a recognised trailer token.

    Project convention is closed-set: a trailer is one of
    `KNOWN_TRAILER_TOKENS` (case-insensitive). An unknown token in
    the trailer block is almost always a typo (`Cosed:` for `Closes:`,
    `Singed-off-by:` for `Signed-off-by:`) — fail closed.

    To introduce a new trailer convention, add it to
    KNOWN_TRAILER_TOKENS in the same PR.
    """
    return token.lower() in {t.lower() for t in KNOWN_TRAILER_TOKENS}


def parse_trailer_block(lines: list[str]) -> list[tuple[int, str, str]]:
    """Identify the contiguous trailer block at the tail of `lines`.

    Returns a list of (1-based-line-index, token, value) tuples. A
    trailer block is the longest tail run of lines where every line
    matches either TRAILER_RE (true `Token: value` trailers) or
    GITHUB_KEYWORD_RE (`Closes #N`-style links — accepted because
    project convention uses the no-colon form).
    """
    trailers: list[tuple[int, str, str]] = []
    for idx in range(len(lines), 0, -1):
        line = lines[idx - 1]
        if not line.strip():
            # A blank line terminates the trailer block.
            break
        match = TRAILER_RE.match(line)
        if match:
            token = match.group(1)
            value = line.split(":", 1)[1].lstrip()
            trailers.append((idx, token, value))
            continue
        keyword_match = GITHUB_KEYWORD_RE.match(line)
        if keyword_match:
            token = keyword_match.group(1)
            value = keyword_match.group(2)
            trailers.append((idx, token, value))
            continue
        break
    trailers.reverse()
    return trailers


def check_breaking_change_position(lines: list[str]) -> None:
    """If `BREAKING CHANGE:` appears, it must be the last non-sign-off line."""
    breaking_indices = [
        idx
        for idx, line in enumerate(lines, start=1)
        if line.startswith("BREAKING CHANGE:") or line.startswith("BREAKING-CHANGE:")
    ]
    if not breaking_indices:
        return
    if len(breaking_indices) > 1:
        raise ValidationError(
            "`BREAKING CHANGE:` appears more than once in the "
            f"`{MARKER}` block; one footer is enough."
        )
    breaking_idx = breaking_indices[0]
    # Every line after the breaking-change line must be a `Signed-off-by:`.
    tail = lines[breaking_idx:]
    for offset, line in enumerate(tail, start=breaking_idx + 1):
        if not line.strip():
            continue
        if not line.startswith("Signed-off-by:"):
            raise ValidationError(
                "`BREAKING CHANGE:` must be the last non-`Signed-off-by:` "
                f"line in the `{MARKER}` block; "
                f"found `{line.strip()}` on line {offset}."
            )


def check_trailers(lines: list[str]) -> None:
    """Validate every trailer in the tail block parses as a real trailer."""
    trailers = parse_trailer_block(lines)
    for idx, token, value in trailers:
        if not is_trailer_token(token):
            raise ValidationError(
                f"Trailer on line {idx} uses an unknown token "
                f"`{token}:`. Recognised trailers: "
                f"{sorted(KNOWN_TRAILER_TOKENS)}. If this is intentional, "
                "add the new trailer to KNOWN_TRAILER_TOKENS in "
                "scripts/validate-commit-msg-block.py."
            )
        if not value.strip():
            raise ValidationError(f"Trailer on line {idx} (`{token}:`) has an empty value.")


SIGNOFF_RE = re.compile(r"^Signed-off-by: .+ <.+@.+>\s*$")


def check_signoff_present(lines: list[str]) -> None:
    """Require at least one valid `Signed-off-by:` trailer in the block.

    The merge bot (#291) pastes the block verbatim as the squash-merge
    commit body, authoring no commits of its own. Without a sign-off
    inside the block, the merged squash commit lands on `main` without
    DCO and the post-merge `dco` workflow goes red. Failing closed at
    PR-author time is cheaper than discovering it post-merge.
    """
    trailers = parse_trailer_block(lines)
    for _, token, value in trailers:
        if token.lower() != "signed-off-by":
            continue
        if SIGNOFF_RE.match(f"Signed-off-by: {value}"):
            return
    raise ValidationError(
        f"`{MARKER}` block has no `Signed-off-by:` trailer. "
        "The merge bot (#291) pastes the block as the squash-merge "
        "commit body, so the trailer must sit inside the block. "
        "Format: `Signed-off-by: Name <email>`. The bot will refuse "
        "to merge a PR whose block lacks this trailer."
    )


def validate(body: str) -> None:
    block = extract_block(body)
    lines = block_lines(block)
    check_non_empty(lines)
    check_line_width(lines)
    check_no_markdown(lines)
    check_breaking_change_position(lines)
    check_trailers(lines)
    check_signoff_present(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the ==COMMIT_MSG== block in a PR body against "
            "ADR 0037 and CONTRIBUTING.md."
        )
    )
    parser.add_argument(
        "body_path",
        type=Path,
        help="Path to a file containing the PR body markdown.",
    )
    args = parser.parse_args(argv)
    body = args.body_path.read_text(encoding="utf-8")
    try:
        validate(body)
    except ValidationError as err:
        print(f"pr-lint: {err}", file=sys.stderr)
        return 1
    print("pr-lint: ==COMMIT_MSG== block OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
