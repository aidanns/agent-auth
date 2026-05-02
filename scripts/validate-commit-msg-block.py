#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT
#
# Validate the `==COMMIT_MSG==` block in a PR body against the conventions
# described in `CONTRIBUTING.md` § "Writing PRs" and ADR 0037.
#
# The block is "body and trailers only" — the squash commit's subject
# comes from the PR title via the merge API's `commit_title` field, and
# the block is what lands as `commit_message`. GitHub renders a squash
# commit by joining `commit_title + blank + commit_message`, so a
# leading subject line in the block would produce the subject twice in
# `git log` (once as the rendered subject, once as the first body
# line). See issue #478.
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
#      comments) is non-blank — without a non-blank opener the bot
#      pastes a body whose first line is empty, which renders without
#      a body at all in `git log`.
#   8. The first content line of the block does NOT look like a
#      Conventional-Commit subject — e.g. `improvement(ci): wire
#      the foo`. The block is body + trailers only (issue #478); the
#      PR title is the source of the squash-merge subject. A leading
#      subject line would render twice on `main`.
#   9. When a `Fixes:` trailer carries a SHA-style value (i.e. it is
#      not the `Fixes #N` GitHub-keyword form), it follows the
#      kernel-style `Fixes: <sha> ("subject")` shape: a hex SHA of
#      at least 7 characters followed by a parenthesised
#      double-quoted subject.
#  10. The trailer block at the tail of the body is contiguous: no
#      blank lines between two consecutive trailers. RFC 5322 / kernel
#      convention / cbea.ms all say trailers form one contiguous
#      block, and `git interpret-trailers --parse` treats a blank line
#      as the body/trailer boundary — a blank between `Closes #N` and
#      `Signed-off-by:` makes it see only the latter as a trailer, so
#      release-note generators and audit-trail extractors silently
#      lose the `Closes:` reference.
#  11. At least one blank line sits between the last body paragraph
#      and the first trailer line. The body ends, blank line(s),
#      then the contiguous trailer stack — that blank is where the
#      visual separation lives, not between trailers. This matches
#      `git interpret-trailers --parse` semantics, which treats any
#      run of one or more blanks as the body/trailer boundary.
#  12. (Soft, warning-only — issue #395.) The body region (block
#      content with the trailer block removed) is not unusually
#      long. A body that exceeds either of the soft thresholds in
#      `VERBOSE_BODY_MAX_LINES` / `VERBOSE_BODY_MAX_WORDS` prompts
#      a stderr `Warning:` line pointing at CONTRIBUTING.md →
#      "Writing release-worthy commits" → "Body" → "Lead with
#      why, not what". This rule does NOT fail CI — bodies whose
#      length is justified (ADR-grade decisions, non-obvious
#      failure modes, supply-chain or release-pipeline changes
#      with audit-trail value) are legitimately long and the
#      project would rather surface the warning than block the PR.
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

# Soft thresholds for the "why, not what" verbose-body warning (#395).
# Tuned against the historical commit log so the worst diff-restating
# offender (`7ab4c6a` — 34 non-blank body lines, 216 words) trips the
# warning while the legitimately-long bodies that the issue listed as
# must-not-trip (`b07fe58` — 14 lines / 122 words; `c3c7136` — 28 lines
# / 240 words; `166f55c` — 17 lines / 149 words) all stay under both
# thresholds. The line cap is the active separator here: `7ab4c6a`
# (216 words) sits beneath `c3c7136` (240 words) on word count, so a
# pure word threshold cannot tell them apart. Counting non-blank lines
# in the body region (trailer block excluded; the block is body-only
# post-#478, so there is no subject line to exclude) catches the
# offender's six diff-restating paragraphs while leaving the
# 4-paragraph ADR-grade bodies under cap. The word threshold is set
# above the worst offender so it only fires on bodies even more
# verbose than `7ab4c6a` — a defensive ceiling rather than a primary
# trigger. Either threshold being exceeded fires the warning (OR
# semantics), and the warning is informational; CI does not fail.
VERBOSE_BODY_MAX_LINES = 32
VERBOSE_BODY_MAX_WORDS = 250

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

# Kernel-style `Fixes: <sha> ...` trailer line — the FULL line including
# the `Fixes:` prefix and a 7-40 char hex SHA value (CONTRIBUTING.md →
# "Trailers" documents this shape). This tighter check distinguishes a
# real `Fixes:` trailer pointing at an introducing commit from a body
# paragraph whose heading happens to be `Fixes:` — e.g. the release-PR
# body's `Fixes: <prose description>.` section heading rendered by
# `scripts/changelog/build_release.py:render_commit_msg_block`. Without
# the value-shape distinction, `_is_trailer_shape_line` would absorb
# the section heading into the trailer-block region and
# `check_trailer_block_contiguity` / `check_blank_line_before_trailers`
# would fire on an otherwise well-formed body. (Distinct from
# ``FIXES_SHA_TRAILER_RE`` defined further below, which matches only
# the value portion as part of `check_fixes_trailer_shape`'s shape
# check on already-parsed trailer values.)
FIXES_SHA_TRAILER_LINE_RE = re.compile(r"^Fixes:[ \t]+[0-9a-fA-F]{7,40}\b")

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
    # Body prose wraps at 72; trailer lines are exempt. Trailer values
    # are routinely longer than the body wrap (a numeric-id-prefixed
    # GitHub no-reply email like
    # `<123456+agent-auth-release-bot[bot]@users.noreply.github.com>`
    # alone is 60 chars, before the trailer token + value separator),
    # and the kernel/git convention treats trailers as
    # one-line-per-trailer regardless of width — wrapping a
    # ``Signed-off-by:`` line breaks ``git interpret-trailers --parse``.
    # The PR-rendered release-bot signoff (#398) is the concrete case.
    line_list = list(lines)
    trailer_start = _trailer_block_start_index(line_list)
    over = [
        (idx, line)
        for idx, line in enumerate(line_list, start=1)
        if len(line) > MAX_LINE_WIDTH and (trailer_start is None or idx - 1 < trailer_start)
    ]
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
        # `Fixes:` only counts as a trailer when its value is a SHA
        # (kernel `Fixes: <sha> ("subject")` form). When the value is
        # prose, the line is a body paragraph whose heading happens to
        # be `Fixes:` (e.g. release-PR body sections rendered by
        # `build_release.render_commit_msg_block`); treating it as a
        # trailer would absorb the body paragraph into the trailer-block
        # region and trigger false-positive contiguity / blank-before
        # failures. The `Fixes #N` GitHub-keyword form is unaffected —
        # it falls through to the `GITHUB_KEYWORD_RE` branch below.
        if trailer_match.group(1).lower() == "fixes":
            return FIXES_SHA_TRAILER_LINE_RE.match(line) is not None
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
    # rest of the validator's diagnostics. Name the trailer lines
    # straddling each blank so the diagnostic is unambiguous regardless
    # of which trailer tokens are involved (`Closes` /
    # `Signed-off-by:`, `BREAKING CHANGE:` / `Signed-off-by:`, or any
    # other pair).
    split_descriptions: list[str] = []
    for blank_idx in blank_offsets:
        before = next(
            (lines[i] for i in range(blank_idx - 1, first_trailer_idx - 1, -1) if lines[i].strip()),
            None,
        )
        after = next(
            (lines[i] for i in range(blank_idx + 1, len(lines)) if lines[i].strip()),
            None,
        )
        if before is not None and after is not None:
            split_descriptions.append(
                f"line {blank_idx + 1} (between `{before.strip()}` " f"and `{after.strip()}`)"
            )
        else:
            split_descriptions.append(f"line {blank_idx + 1}")
    splits_summary = "; ".join(split_descriptions)
    raise ValidationError(
        f"`{MARKER}` block has blank line(s) between trailers "
        f"({splits_summary}). The trailer block must be contiguous — "
        "`git interpret-trailers --parse` treats a blank line as the "
        "body/trailer boundary, so any two consecutive trailers (e.g. "
        "`Closes #N` and `Signed-off-by:`, or `BREAKING CHANGE:` and "
        "`Signed-off-by:`) separated by a blank cause the leading "
        "trailer to drop out of the trailer set and downstream tooling "
        "silently loses the reference. Stack the trailers with no "
        "blanks between them."
    )


def check_blank_line_before_trailers(lines: list[str]) -> None:
    """Require at least one blank line between body and the trailer block.

    The body ends, then one or more blanks, then the contiguous
    trailer stack. Without the blank, the last body paragraph and the
    first trailer visually run together in `git log` and
    `git interpret-trailers --parse` is forced to fall back on the
    heuristic that 25%+ of the last paragraph's lines must be
    trailer-shape — a fragile signal we'd rather not rely on.

    `git interpret-trailers --parse` treats any run of one or more
    blanks as the body/trailer boundary, so the rule deliberately
    accepts ``>= 1`` blank rather than insisting on exactly one. This
    is the visual-separation rule the issue (#400) carved out as the
    *correct* place to put a blank line; the contiguity rule above
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

    The block becomes the squash commit's body verbatim, and the body
    must have a non-blank first line — otherwise the bot pastes a body
    whose first line is empty, which renders as a body-less commit in
    `git log` (the rendered subject would still display because GitHub
    sets `commit_title` from the PR title independently).

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
            "before the body. The first content line must be the "
            "first line of the commit body so the bot's pasted body "
            "renders correctly in `git log` — drop the leading "
            "blank line(s)."
        )


# Conventional-Commit subject shape — the project's PR-title prefix
# allowlist (ADR 0037) followed by `: <text>`. Used by
# ``check_no_leading_subject_line`` to detect a leading subject line in
# the block, which post-#478 belongs in the PR title (rendered as the
# squash commit's `commit_title`), not the body. Matched on the first
# non-blank content line of the block.
LEADING_SUBJECT_RE = re.compile(
    r"^(feature|improvement|fix|deprecation|migration|break|chore)(\([^)]+\))?: .+$"
)


def check_no_leading_subject_line(lines: list[str]) -> None:
    """Reject a body whose first line looks like a Conventional-Commit subject.

    The block is body + trailers only (issue #478): the squash
    commit's subject comes from the PR title via the merge API's
    `commit_title` field, so a leading subject line in the block
    would render twice on `main` — once as the subject, once as the
    first body line. The check fires on the first non-blank content
    line.
    """
    first_line = next((line for line in lines if line.strip()), None)
    if first_line is None:
        return
    if LEADING_SUBJECT_RE.match(first_line.strip()):
        raise ValidationError(
            f"`{MARKER}` block is now the body only — remove the "
            "leading subject line; the PR title is the source for "
            "the squash commit subject."
        )


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


def _body_region(lines: list[str]) -> list[str]:
    """Return the body region of a commit-msg block.

    Post-#478 the block is body + trailers only, so the body region
    is the block content with the trailer block (identified by
    ``_trailer_block_start_index``) removed. Trailing blank lines
    inside the resulting region are stripped so a body whose last
    paragraph is followed by the canonical blank-then-trailers tail
    contributes only its content lines to the region.

    Used by ``check_verbose_body`` to size the body alone, separately
    from the trailer block (which is structurally bounded — every
    trailer is one line).
    """
    if not lines:
        return []
    body = list(lines)
    first_trailer_idx = _trailer_block_start_index(body)
    if first_trailer_idx is not None:
        body = body[:first_trailer_idx]
    while body and not body[-1].strip():
        body.pop()
    return body


def check_verbose_body(lines: list[str]) -> int:
    """Warn (don't error) when the body region is unusually long.

    The ``==COMMIT_MSG==`` rules in CONTRIBUTING.md → "Writing
    release-worthy commits" → "Body" say to lead with *why*, not
    *how* — the diff already shows how. Bodies that re-narrate the
    diff in prose tend to be both long and structurally wide (many
    paragraphs across many non-blank lines). The two soft thresholds
    catch that shape without false-positiving the bodies whose length
    is justified (ADR-grade decisions, non-obvious failure modes,
    supply-chain or release-pipeline changes whose audit trail
    benefits from the extra paragraphs).

    Returns the number of warnings emitted (0 or 1). Prints the
    warning to stderr; does not raise. The caller's exit code is
    unchanged — this is informational, surfaced in the workflow log
    so a reviewer can push back on the PR description before merge,
    and explicitly NOT a CI failure: the cost of a false positive on
    a legitimate-but-long body is forcing the contributor to
    relitigate after merge.
    """
    body = _body_region(lines)
    non_blank_count = sum(1 for line in body if line.strip())
    word_count = sum(len(line.split()) for line in body if line.strip())
    over_words = word_count > VERBOSE_BODY_MAX_WORDS
    over_lines = non_blank_count > VERBOSE_BODY_MAX_LINES
    if not (over_words or over_lines):
        return 0
    print(
        f"Warning: `{MARKER}` block body is verbose "
        f"({word_count} words, {non_blank_count} non-blank lines; "
        f"soft thresholds {VERBOSE_BODY_MAX_WORDS}/{VERBOSE_BODY_MAX_LINES}). "
        'Re-read CONTRIBUTING.md → "Writing release-worthy commits" '
        '→ "Body" → "Lead with why, not what". If this commit '
        "legitimately needs the length (ADR-grade decision, "
        "non-obvious failure mode, supply-chain or release-pipeline "
        "change with audit-trail value), this warning is "
        "informational; the CI job does not fail.",
        file=sys.stderr,
    )
    return 1


def validate(body: str) -> None:
    block = extract_commit_msg_block(body)
    check_first_line_non_blank(block)
    lines = block_lines(block)
    check_non_empty(lines)
    check_no_leading_subject_line(lines)
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
    check_fixes_trailer_shape(lines)
    # Soft warning — runs last so a body that fails any structural
    # rule above surfaces the actionable error first; the verbose-body
    # warning is advisory and only useful once the block is otherwise
    # well-formed. Does NOT raise; returns a count, which the caller's
    # exit code ignores by design (see CONTRIBUTING.md → "Writing
    # release-worthy commits" → "Body" → "Lead with why, not what" for
    # the warning-not-failure rationale).
    check_verbose_body(lines)


def _build_verbose_body(word_count: int, words_per_line: int = 20) -> str:
    """Synthesize a ``==COMMIT_MSG==`` block whose body has ``word_count`` words.

    Each body line carries ``words_per_line`` 1-char placeholder words
    (``w w w …``) so the body stays under the 72-char line cap as long
    as ``words_per_line`` ≤ 36 (a 36-word `w` line is 71 chars). The
    default of 20 words/line keeps the line count well below
    ``VERBOSE_BODY_MAX_LINES`` for word counts at and around the word
    threshold, so the word-boundary self-test cases below can exercise
    the word check in isolation from the line check. The
    ``verbose-body-trips`` case overrides ``words_per_line`` to a
    smaller value to also exceed the line cap, mirroring the real
    diff-restating shape that motivated the warning.

    The synthesized block is body + trailers only (no leading subject
    line) per #478 — the body region is the ``w w w …`` block alone,
    so the line / word counts the boundary cases assert match the
    sizing exactly. ``w`` is not a CC-shaped prefix, so the
    ``check_no_leading_subject_line`` regex doesn't match.
    """
    full_lines = word_count // words_per_line
    leftover = word_count % words_per_line
    body_lines = [" ".join(["w"] * words_per_line) for _ in range(full_lines)]
    if leftover:
        body_lines.append(" ".join(["w"] * leftover))
    body_block = "\n".join(body_lines)
    return (
        "==COMMIT_MSG==\n"
        f"{body_block}\n\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )


# Inline self-test cases for the verbose-body warning. Each tuple is
# (body, expect_warning, label). Lives inside the validator (rather
# than a fixture file) because ``check_verbose_body`` returns a
# warning count — not a raise/no-raise outcome — so the
# validate-raises-vs-passes fixture loop in ``pr-lint.yml`` cannot
# exercise it.
_VERBOSE_BODY_SELF_TEST_CASES: tuple[tuple[str, bool, str], ...] = (
    (
        # Verbose body — well over both thresholds. Mirrors the worst
        # offender from the issue body (#395, commit 7ab4c6a) which
        # had ~216 words / 34 non-blank body lines. 5 words per line
        # so the line count (60) also clears VERBOSE_BODY_MAX_LINES.
        _build_verbose_body(300, words_per_line=5),
        True,
        "verbose-body-trips",
    ),
    (
        # Short, focused body — the canonical "lead with why" shape.
        # Should not trip the warning under any threshold.
        "==COMMIT_MSG==\n"
        "One paragraph of why this change exists. Two short lines is\n"
        "all the body needs because the diff is self-evident.\n\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n",
        False,
        "short-body-passes",
    ),
    (
        # Boundary: word count exactly at VERBOSE_BODY_MAX_WORDS, line
        # count under the line cap. The check uses strict `>` so
        # "exactly at the threshold" must NOT fire — the threshold is
        # the ceiling of acceptable verbosity, not the first verbose
        # value.
        _build_verbose_body(VERBOSE_BODY_MAX_WORDS),
        False,
        "boundary-exact-max-words",
    ),
    (
        # Boundary: one word over VERBOSE_BODY_MAX_WORDS — must fire.
        # Pairs with the case above to lock the strict-greater-than
        # contract: anything past the threshold trips the warning.
        _build_verbose_body(VERBOSE_BODY_MAX_WORDS + 1),
        True,
        "boundary-one-over-max-words",
    ),
    (
        # Boundary: non-blank body line count exactly at
        # VERBOSE_BODY_MAX_LINES, word count well under the word cap.
        # ``words_per_line=1`` makes line count == word count, so the
        # body has 32 non-blank lines / 32 words — at the line
        # threshold, well under the word threshold. The line check
        # uses strict `>` so "exactly at the threshold" must NOT fire.
        # Pairs with ``boundary-one-over-max-lines`` to lock the
        # strict-greater-than contract on the line cap (the line cap
        # is the active separator for the worst offender flagged in
        # #395, so it deserves its own boundary coverage parallel to
        # the word-cap pair above).
        _build_verbose_body(VERBOSE_BODY_MAX_LINES, words_per_line=1),
        False,
        "boundary-exact-max-lines",
    ),
    (
        # Boundary: one non-blank body line over VERBOSE_BODY_MAX_LINES,
        # word count well under the word cap. 33 lines / 33 words
        # isolates the line check from the word check, so a regression
        # in the line check (off-by-one on the strict `>`, miscounting
        # blank lines, slicing the body region wrong) would surface
        # here even if the word check still works.
        _build_verbose_body(VERBOSE_BODY_MAX_LINES + 1, words_per_line=1),
        True,
        "boundary-one-over-max-lines",
    ),
)


def _run_self_test() -> int:
    fail = 0
    for body, expect_warning, label in _VERBOSE_BODY_SELF_TEST_CASES:
        block = extract_commit_msg_block(body)
        lines = block_lines(block)
        warning_count = check_verbose_body(lines)
        actually_warned = warning_count > 0
        if actually_warned == expect_warning:
            print(f"ok: {label} (warning={'yes' if actually_warned else 'no'})")
        else:
            expected = "warning" if expect_warning else "no warning"
            actual = "warning" if actually_warned else "no warning"
            print(f"FAIL: {label}: expected {expected}, got {actual}", file=sys.stderr)
            fail += 1
    total = len(_VERBOSE_BODY_SELF_TEST_CASES)
    if fail:
        print(f"{fail} self-test case(s) failed", file=sys.stderr)
        return 1
    print(f"all {total} self-test cases passed")
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
        "--self-test",
        action="store_true",
        help=(
            "Run the inline self-test cases instead of validating a "
            "body file. Covers the verbose-body warning rule, whose "
            "outcome is a warning count rather than raise/no-raise "
            "and so cannot be exercised by the fixture self-test loop."
        ),
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return _run_self_test()
    if args.body_path is None:
        parser.error("body_path is required unless --self-test is given")
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
