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
#   3. No markdown headings (`#`), task checkboxes (`- [ ]`, `- [x]`),
#      or image embeds (`![alt](url)`) inside the block. Plain bullet
#      and numbered lists are permitted (kernel/cbea.ms style for
#      enumerating several related changes); the three structural
#      bans above carry the audience-split signal that previously
#      justified a blanket no-markdown rule (see #345).
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
#   7. The first content line of the block (after stripping HTML
#      comments) is non-blank — git commits open with the subject,
#      not a leading blank line.
#   8. When a `Fixes:` trailer carries a SHA-style value (i.e. it is
#      not the `Fixes #N` GitHub-keyword form), it follows the
#      kernel-style `Fixes: <sha> ("subject")` shape: a hex SHA of
#      at least 7 characters followed by a parenthesised
#      double-quoted subject.
#   9. The trailer block at the tail of the body is contiguous: no
#      blank lines between two consecutive trailers. RFC 5322 / kernel
#      convention / cbea.ms all say trailers form one contiguous
#      block, and `git interpret-trailers --parse` treats a blank line
#      as the body/trailer boundary — a blank between `Closes #N` and
#      `Signed-off-by:` makes it see only the latter as a trailer, so
#      release-note generators and audit-trail extractors silently
#      lose the `Closes:` reference.
#  10. Exactly one blank line sits between the last body paragraph and
#      the first trailer line. The body ends, blank line, then the
#      contiguous trailer stack — that blank is where the visual
#      separation lives, not between trailers.
#
# The PR title (subject) has its own prose-style rules — length cap,
# trailing period, past-tense imperative — enforced by the sibling
# `scripts/validate-pr-title.py` script in the `pr-title-style` job
# of `.github/workflows/pr-lint.yml`. The two scripts split because
# the title and the body have different inputs (string vs. file) and
# different runtime audiences (the action consumes the title via env
# var; the body validator works against a file on disk).
#
# These rules sit alongside the prose conventions documented in
# CONTRIBUTING.md → "Writing release-worthy commits" (#337); the
# "Convention only / not CI-enforced" subset there (one-logical-change,
# why-not-how, ≤50-char summary soft target, capitalisation,
# imperative mood beyond the past-tense blacklist) is deliberately
# left to human review.
#
# Exits 0 on success, 1 with a human-readable error on failure. Reads
# the PR body from a file path given as argv[1].
#
# Library API: this module exposes a generic
# `extract_block(body: str, marker_name: str) -> str | None` plus a
# fixed `extract_commit_msg_block(body: str) -> str` wrapper for the
# `==COMMIT_MSG==` case, and `validate(body: str) -> None` for callers
# that want to run the full lint. `scripts/extract-commit-msg-block.py`
# (used by the merge bot) imports `extract_commit_msg_block`;
# `scripts/changelog/bot.py` (the changelog bot, #298) imports
# `extract_block` for the `==CHANGELOG_MSG==` marker.

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from pathlib import Path

COMMIT_MSG_MARKER_NAME = "COMMIT_MSG"
MARKER = f"=={COMMIT_MSG_MARKER_NAME}=="
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

# Patterns that must NOT appear inside the block (rule 3). Each
# pattern's presence reliably signals reviewer-surface content
# leaking into the commit body — task checkboxes are the strongest
# tell of a test plan / deploy checklist; markdown headings are
# section dividers that belong in `## Review notes`; image embeds
# are screenshots. Plain bullet / numbered lists used to live here
# too but the kernel/cbea.ms enumerated-changes form reads better
# in `git log` than the run-on prose paragraphs authors fell back
# to under the stricter rule (see #345).
#
# `pattern.search` (not `pattern.match`) is used in
# `check_no_markdown` so the `image embed` pattern catches a
# mid-line embed; the heading/checkbox patterns are anchored at
# start-of-line (`^`) inside their own regex regardless.
DISALLOWED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("markdown heading", re.compile(r"^#{1,6}\s")),
    ("task checkbox", re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s")),
    ("image embed", re.compile(r"!\[[^\]]*\]\([^)]*\)")),
]

# Comment / instruction lines the contributor may leave behind by
# accident from the PR template. These are stripped from the block
# before validation so the template's own scaffolding doesn't fail
# the lint, but a non-empty body must remain after stripping.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class ValidationError(Exception):
    """Raised when the PR body fails the commit-msg block lint."""


class BlockMarkerError(ValueError):
    """Raised when ``extract_block`` finds a malformed marker pair.

    A separate exception type from ``ValidationError`` so callers other
    than the commit-msg validator (e.g. the changelog bot in #298) can
    re-raise without being tangled in the validator's exit-code
    behaviour. ``ValidationError`` subclasses ``Exception`` for
    historical reasons and the validator's main loop catches it
    specifically.
    """


def extract_block(body: str, marker_name: str) -> str | None:
    """Return the contents between the two ``==<marker_name>==`` markers.

    The marker is matched as a full line (after stripping) so an
    inline mention of ``==FOO==`` inside surrounding prose does not
    count as a marker.

    Returns ``None`` when the body contains no marker line — this is
    the "marker absent" signal callers use to fall through. Raises
    ``BlockMarkerError`` when exactly one marker line appears or more
    than two appear: those are mismatched / ambiguous and the caller
    should report the failure.
    """
    marker = f"=={marker_name}=="
    occurrences = [i for i, line in enumerate(body.splitlines()) if line.strip() == marker]
    if len(occurrences) == 0:
        return None
    if len(occurrences) == 1:
        raise BlockMarkerError(
            f"PR body has only one `{marker}` marker; the block must be opened and closed."
        )
    if len(occurrences) == 2:
        lines = body.splitlines()
        start, end = occurrences
        return "\n".join(lines[start + 1 : end])
    raise BlockMarkerError(
        f"PR body has {len(occurrences)} `{marker}` markers; "
        "exactly one block (two markers) is required."
    )


def extract_commit_msg_block(body: str) -> str:
    """Return the contents of the `==COMMIT_MSG==` block.

    Wraps :func:`extract_block` so the commit-msg validator and the
    merge-bot extractor keep their historical "block is required"
    semantics (raising ``ValidationError`` rather than returning
    ``None``). The shared extractor is reused by the changelog bot
    in #298 with different absent-block semantics (a missing block
    is a fall-through, not an error).
    """
    try:
        block = extract_block(body, COMMIT_MSG_MARKER_NAME)
    except BlockMarkerError as exc:
        raise ValidationError(str(exc)) from exc
    if block is None:
        raise ValidationError(
            f"PR body is missing the `{MARKER}` block. See .github/PULL_REQUEST_TEMPLATE.md."
        )
    return block


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
    """Reject the three reviewer-surface markdown shapes.

    Uses `pattern.search` rather than `pattern.match` so the
    `image embed` predicate catches a mid-line embed (a screenshot
    placed inline in prose). The other two predicates anchor on
    `^` inside their own regex, so search-vs-match is moot for them.
    """
    findings: list[str] = []
    for idx, line in enumerate(lines, start=1):
        for label, pattern in DISALLOWED_PATTERNS:
            if pattern.search(line):
                findings.append(f"  line {idx} ({label}): {line!r}")
                break
    if findings:
        details = "\n".join(findings)
        raise ValidationError(
            f"`{MARKER}` block contains markdown formatting that does "
            f"not belong in a git commit body:\n{details}\n"
            "Headings, task checkboxes, and image embeds are "
            "reviewer-surface and belong in `## Review notes`. "
            "Plain `-` / `*` bullets and `1.` numbered lists are "
            "fine in the commit body."
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


def _is_trailer_shape_line(line: str) -> bool:
    """Return True when ``line`` looks like a trailer-block line.

    Three shapes count as trailer-shape:

    * A ``Token: value`` line whose token is in
      ``KNOWN_TRAILER_TOKENS`` — kernel/RFC-5322 form
      (``Signed-off-by:``, ``Closes:``, ``Fixes:``, etc.). Restricting
      to known tokens (rather than any ``[A-Za-z0-9-]+:`` shape)
      keeps a stray body line like ``Bug-123: see ticket`` from
      extending the trailer-block region across a body/trailer
      blank, which would otherwise produce a misleading
      "blank between trailers" error.
    * ``GITHUB_KEYWORD_RE`` — the no-colon form (``Closes #N``,
      ``Fixes owner/repo#N``) project convention has historically
      accepted alongside true trailers.
    * ``BREAKING CHANGE:`` (with a space, not a hyphen). The footer is
      conventionally a trailer-block resident even though it doesn't
      match ``TRAILER_RE``'s no-whitespace token; see
      ``check_breaking_change_position`` which already treats it as a
      trailer-area line.

    Used by ``check_trailer_block_contiguity`` and
    ``check_blank_line_before_trailers`` to identify the trailer-block
    region without re-implementing the shape check at each call site.
    """
    trailer_match = TRAILER_RE.match(line)
    if trailer_match is not None and is_trailer_token(trailer_match.group(1)):
        return True
    if GITHUB_KEYWORD_RE.match(line) is not None:
        return True
    return line.startswith("BREAKING CHANGE:")


def _trailer_block_start_index(lines: list[str]) -> int | None:
    """Return the 0-based index of the first line of the trailer block.

    Walks from the end of ``lines`` backward, allowing blank lines
    between trailer-shape lines so the broken
    ``Closes #N`` / blank / ``Signed-off-by:`` pattern is still
    detected as a single (broken) trailer block. Stops at the first
    non-blank line that is not trailer-shape — that line is the body
    terminus, and everything after it is the trailer-block region.

    Returns ``None`` when the block has no trailer-shape lines at all
    (e.g. an all-prose body); the caller then has nothing to validate
    for contiguity / blank-line-before. Returns the 0-based index of
    the first trailer-shape line otherwise.
    """
    first_trailer_idx: int | None = None
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if not line.strip():
            # Blank line — keep walking; we want to extend the trailer
            # block region across the blank so the contiguity check
            # can see it.
            continue
        if _is_trailer_shape_line(line):
            first_trailer_idx = idx
            continue
        # First non-blank, non-trailer line walking back: that's the
        # body terminus. Everything after it is the trailer-block
        # region.
        break
    return first_trailer_idx


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


def check_trailer_block_contiguity(lines: list[str]) -> None:
    """Reject blank lines between two consecutive trailers.

    `git interpret-trailers --parse` treats the first blank line above
    a candidate trailer as the body/trailer boundary — anything before
    that blank is body. A `Closes #N` separated from `Signed-off-by:`
    by a blank line therefore drops out of the trailer set, and the
    release-note generator / audit-trail extractor / GitHub's "linked
    issues" inference silently lose the `Closes:` reference.

    The fix is to require the trailer block to be one contiguous run
    of trailer-shape lines (RFC 5322 / kernel / cbea.ms convention).
    The check walks from the end backward identifying the trailer
    block region (any tail run of trailer-shape lines, *including*
    blank lines between them so the broken pattern stays in scope),
    then fails if any blank line sits inside that region.
    """
    first_trailer_idx = _trailer_block_start_index(lines)
    if first_trailer_idx is None:
        # No trailer-shape lines at all; nothing to validate. Other
        # checks (e.g. ``check_signoff_present``) own the "block has
        # no Signed-off-by:" failure path.
        return
    region = lines[first_trailer_idx:]
    blank_offsets = [
        first_trailer_idx + offset for offset, line in enumerate(region) if not line.strip()
    ]
    if not blank_offsets:
        return
    # 1-based line numbers for the error message, consistent with the
    # rest of the validator's diagnostics.
    blank_line_numbers = [idx + 1 for idx in blank_offsets]
    raise ValidationError(
        f"`{MARKER}` block has blank line(s) between trailers "
        f"(line(s) {blank_line_numbers}). The trailer block must be "
        "contiguous — `git interpret-trailers --parse` treats a blank "
        "line as the body/trailer boundary, so a `Closes #N` "
        "separated from `Signed-off-by:` by a blank drops out of the "
        "trailer set and downstream tooling silently loses the "
        "reference. Stack the trailers with no blanks between them."
    )


def check_blank_line_before_trailers(lines: list[str]) -> None:
    """Require exactly one blank line between body and the trailer block.

    The body ends, then a blank, then the contiguous trailer stack.
    Without the blank, the last body paragraph and the first trailer
    visually run together in `git log` and `git interpret-trailers
    --parse` is forced to fall back on the heuristic that 25%+ of the
    last paragraph's lines must be trailer-shape — a fragile signal
    we'd rather not rely on.

    This is the visual-separation rule the issue (#400) carved out as
    the *correct* place to put a blank line; the contiguity rule above
    is what stops contributors putting it between trailers.
    """
    first_trailer_idx = _trailer_block_start_index(lines)
    if first_trailer_idx is None or first_trailer_idx == 0:
        # No trailer block, or trailer block starts at the very top of
        # the body (a body-less commit — e.g. a one-line subject and
        # nothing but trailers). Nothing to separate.
        return
    preceding_line = lines[first_trailer_idx - 1]
    if preceding_line.strip():
        raise ValidationError(
            f"`{MARKER}` block has no blank line between the body "
            f"and the trailer block (line {first_trailer_idx + 1} is "
            "the first trailer; the line above it is non-blank). "
            "Insert one blank line so the body and the trailer stack "
            "are visually separated and `git interpret-trailers "
            "--parse` sees the trailer block boundary."
        )


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


# Kernel-style `Fixes: <sha> ("subject")` shape. The SHA must be at
# least 7 hex chars (git's default short-SHA width) and the subject
# must be parenthesised double-quoted text. The trailing-only `\.?`
# accommodates the historical `Fixes: ... .` shape some contributors
# use; otherwise the structure is rigid by design.
FIXES_SHA_TRAILER_RE = re.compile(r'^[0-9a-fA-F]{7,}\s+\("[^"]+"\)\.?$')

# Issue-ref shapes accepted as alternatives to the kernel-style SHA
# form: `#123` and `owner/repo#123`.
GITHUB_ISSUE_REF_RE = re.compile(r"^(?:#\d+|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+)\.?$")


def _is_github_issue_ref(value: str) -> bool:
    return GITHUB_ISSUE_REF_RE.match(value) is not None


def check_first_line_non_blank(block: str) -> None:
    """Reject a leading blank line at the top of the block.

    The git-commit shape is "subject on the first line, blank line,
    body" — a leading blank line in the *authored* block means the
    bot pastes a body whose first line is empty, which renders
    without a subject in `git log`.

    Template scaffolding is the recognised exception: when the first
    non-blank line is an HTML comment (`<!-- ... -->`) the contributor
    is using the PR template's instructional comments and the leading
    blanks are just visual padding around them. In that case we
    delegate to ``check_non_empty`` to confirm there is *some* content
    once the comments are stripped.
    """
    raw_lines = block.splitlines()
    if not raw_lines:
        return
    # Find the first non-blank line in the raw (un-stripped) block.
    first_idx = next(
        (i for i, line in enumerate(raw_lines) if line.strip()),
        None,
    )
    if first_idx is None:
        # All-blank block — ``check_non_empty`` owns that error path.
        return
    # An HTML comment opener at the first non-blank position means the
    # contributor is using the PR template's scaffolding; preceding
    # blank lines are intentional padding around it.
    if raw_lines[first_idx].lstrip().startswith("<!--"):
        return
    if first_idx > 0:
        raise ValidationError(
            f"`{MARKER}` block opens with {first_idx} blank line(s) "
            "before the subject. The first content line must be the "
            "commit subject so the bot's pasted body renders correctly "
            "in `git log` — drop the leading blank line(s)."
        )


def check_first_line_not_subject_dup(lines: list[str], title: str | None) -> None:
    """Reject a body whose first line duplicates the PR title.

    The merge bot pastes the PR title as the squash-merge subject and
    pastes the block as the body. If the contributor copies the title
    into the first line of the block, the resulting commit has the
    subject repeated as the first body line — visually noisy in
    `git log`, and a sign the contributor didn't realise the title
    *is* the subject.

    `title` is the PR title (passed via `--title` / env var); a
    ``None`` value means the validator was not given a title (e.g.
    when invoked from the `validator-self-test` fixture loop), in
    which case the check is a no-op.
    """
    if title is None or not lines:
        return
    title_summary = _strip_title_prefix(title).strip().rstrip(".")
    first_line = lines[0].strip().rstrip(".")
    if not title_summary or not first_line:
        return
    if first_line.lower() == title_summary.lower():
        raise ValidationError(
            f"`{MARKER}` block's first line duplicates the PR title "
            f"({first_line!r}). The PR title becomes the squash-merge "
            "subject; drop the duplicate from the body and lead with "
            "the rationale."
        )


PR_TITLE_PREFIX_RE = re.compile(r"^[A-Za-z]+(?:\([^)]+\))?:\s+")


def _strip_title_prefix(title: str) -> str:
    """Return the post-prefix summary of a PR title for comparison."""
    match = PR_TITLE_PREFIX_RE.match(title)
    if match is None:
        return title
    return title[match.end() :]


def check_fixes_trailer_shape(lines: list[str]) -> None:
    """Validate `Fixes: <sha> ("subject")` shape when SHA-style is used.

    `Fixes #N` and `Fixes owner/repo#N` (the GitHub-keyword form) are
    accepted as-is — they're handled by the closing-keyword path in
    ``parse_trailer_block`` and have nothing to validate beyond the
    issue ref. The kernel-style `Fixes: <sha> ("subject")` form is
    structurally distinct and easy to get wrong; the regex insists on
    a ≥ 7-char hex SHA and a parenthesised double-quoted subject so
    typos like `Fixes: 9c4f1` (too short) or `Fixes: 9c4f1a2 broken`
    (no quoted subject) fail loudly.
    """
    trailers = parse_trailer_block(lines)
    for idx, token, value in trailers:
        if token.lower() != "fixes":
            continue
        # Skip the GitHub-keyword form (`Fixes #N` /
        # `Fixes owner/repo#N`); both the no-colon form (matched by
        # GITHUB_KEYWORD_RE in parse_trailer_block) and the
        # `Fixes: #N` colon variant produce a value starting with `#`
        # or containing `<owner>/<repo>#`. parse_trailer_block already
        # validated those shapes.
        if _is_github_issue_ref(value):
            continue
        if FIXES_SHA_TRAILER_RE.match(value) is None:
            raise ValidationError(
                f"Trailer on line {idx} (`Fixes: {value}`) does not "
                'match the kernel-style `Fixes: <sha> ("subject")` '
                "shape. Use a 7+ hex-char SHA followed by a "
                "parenthesised double-quoted subject, e.g. "
                '`Fixes: 9c4f1a2b3d5e ("subject of the broken commit")`.'
            )


def validate(body: str, title: str | None = None) -> None:
    block = extract_commit_msg_block(body)
    check_first_line_non_blank(block)
    lines = block_lines(block)
    check_non_empty(lines)
    check_line_width(lines)
    check_no_markdown(lines)
    check_breaking_change_position(lines)
    # `check_trailers` runs before the contiguity / blank-line-before
    # checks so an unknown-token typo (`Cosed: #1` for `Closes: #1`)
    # surfaces as the more actionable "unknown trailer token" error,
    # rather than the misleading "no blank line before trailer block"
    # the layout checks would emit if the typo line failed
    # ``_is_trailer_shape_line``'s known-token gate.
    check_trailers(lines)
    check_trailer_block_contiguity(lines)
    check_blank_line_before_trailers(lines)
    check_signoff_present(lines)
    check_first_line_not_subject_dup(lines, title)
    check_fixes_trailer_shape(lines)


# Inline self-test cases for title-aware checks (currently only
# subject-dup). Each tuple is (body, title, expect_pass, label).
# A separate self-test entry point — rather than fixture files — is
# used because these checks need both a body and a title and the
# fixture-loop runs title-less.
_TITLE_AWARE_SELF_TEST_CASES: tuple[tuple[str, str, bool, str], ...] = (
    (
        # Failing case: body's first line duplicates the PR title's
        # post-prefix summary. Bot would paste a commit whose subject
        # is followed by the same line as the first body line.
        "==COMMIT_MSG==\n"
        "Wire the foo into the bar.\n\n"
        "More rationale.\n\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n",
        "feature(foo): wire the foo into the bar",
        False,
        "failing-first-line-dup",
    ),
    (
        # Passing case: same body, but the title's summary is genuinely
        # different from the first body line.
        "==COMMIT_MSG==\n"
        "Wire the foo into the bar.\n\n"
        "More rationale.\n\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n",
        "chore(foo): refactor the foo helper",
        True,
        "passing-no-dup",
    ),
)


def _run_title_aware_self_test() -> int:
    fail = 0
    for body, title, expect_pass, label in _TITLE_AWARE_SELF_TEST_CASES:
        try:
            validate(body, title=title)
        except ValidationError as err:
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
    print(f"all {len(_TITLE_AWARE_SELF_TEST_CASES)} self-test cases passed")
    return 0


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
        nargs="?",
        default=None,
        help="Path to a file containing the PR body markdown.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help=(
            "PR title (the squash-merge subject). When provided, the "
            "first body line is also checked for duplication of the "
            "title. Omit to skip that check (used by the fixture "
            "self-test loop, which has no PR title to compare against)."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the inline title-aware self-test cases instead of "
            "validating a body file. Covers the rules whose input "
            "needs both a body and a title (subject-dup) so the "
            "fixture-loop's title-less invocation does not have to."
        ),
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return _run_title_aware_self_test()
    if args.body_path is None:
        parser.error("body_path is required unless --self-test is given")
    body = args.body_path.read_text(encoding="utf-8")
    try:
        validate(body, title=args.title)
    except ValidationError as err:
        print(f"pr-lint: {err}", file=sys.stderr)
        return 1
    print("pr-lint: ==COMMIT_MSG== block OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
