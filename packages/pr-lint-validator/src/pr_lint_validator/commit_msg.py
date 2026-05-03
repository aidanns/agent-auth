# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""``==COMMIT_MSG==`` block validator.

Adapted from ``scripts/validate-commit-msg-block.py`` (issue #446).
Validates the conventions described in ``CONTRIBUTING.md`` § "Writing
PRs" and ADR 0037:

  1. Exactly one ``==COMMIT_MSG==`` … ``==COMMIT_MSG==`` block.
  2. Every non-empty line in the block wraps at <= 72 chars.
  3. No markdown headings, task checkboxes, or image embeds inside
     the block.
  4. ``BREAKING CHANGE:`` (when present) sits on the last
     non-``Signed-off-by:`` line.
  5. Every trailer line parses per git-trailer format.
  6. At least one ``Signed-off-by:`` trailer is present (DCO).
  7. The first content line of the block is non-blank.
  8. ``Fixes:`` SHA-style trailers follow the kernel
     ``Fixes: <sha> ("subject")`` shape.
  9. The trailer block is contiguous — no blanks between trailers.
 10. At least one blank line separates the body from the trailer
     block.
 11. (Soft, warning-only.) The body region is not unusually long.

Public surface: :class:`ValidationError`, :class:`BlockMarkerError`,
:func:`validate`, :func:`extract_block`,
:func:`extract_commit_msg_block`, :func:`run_self_test`.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable

from .title import Writer

COMMIT_MSG_MARKER_NAME = "COMMIT_MSG"
MARKER = f"=={COMMIT_MSG_MARKER_NAME}=="
MAX_LINE_WIDTH = 72

# Soft thresholds for the verbose-body warning (#395). Tuned against
# the historical commit log so the worst diff-restating offender
# trips the warning while legitimately-long bodies stay under both
# thresholds. Either threshold being exceeded fires the warning.
VERBOSE_BODY_MAX_LINES = 32
VERBOSE_BODY_MAX_WORDS = 250

TRAILER_RE = re.compile(r"^([A-Za-z0-9-]+):[ \t]+\S.*$")

# The bare `Closes #N` form (no colon) was historically accepted by a
# dedicated `GITHUB_KEYWORD_RE` here, but issue #566 dropped it from
# the trailer-detection paths so the canonical `Closes: #N` (with
# colon) is mechanically enforced on every PR. The bare form now
# falls out of the trailer set; `check_no_bare_close_keyword` below
# raises a targeted diagnostic naming the bare form as the cause so
# a contributor hitting this for the first time isn't left guessing
# why their `Closes #N` line was reclassified as body. The
# merge-bot's own auto-close parser (`scripts/parse-close-keywords.py`)
# keeps reading the bare form from already-merged commit bodies
# because GitHub's UI auto-closer accepts it — distinct contract,
# distinct file. See #565 for the paired documentation half.

# Matches a *whole line* of the bare GitHub auto-close-keyword form
# (`Closes #N`, `Fixes #N`, `Resolves #N`, with optional cross-repo
# `owner/repo#N` and an optional trailing period). Anchored start-to-end
# so a prose mention like `this closes #123 because foo` does NOT match
# — the check is for lines clearly *intended* as a `Closes:` trailer
# whose author forgot the colon. Case-sensitive on the keyword to match
# the project's trailer-token convention; the `Closes`/`Fixes`/`Resolves`
# capitalisation is what KNOWN_TRAILER_TOKENS already accepts.
BARE_CLOSE_KEYWORD_LINE_RE = re.compile(
    r"^(?P<keyword>Closes|Fixes|Resolves)\s+"
    r"(?P<ref>(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#\d+)"
    r"\.?\s*$"
)

FIXES_SHA_TRAILER_LINE_RE = re.compile(r"^Fixes:[ \t]+[0-9a-fA-F]{7,40}\b")

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

DISALLOWED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("markdown heading", re.compile(r"^#{1,6}\s")),
    ("task checkbox", re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s")),
    ("image embed", re.compile(r"!\[[^\]]*\]\([^)]*\)")),
]

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class ValidationError(Exception):
    """Raised when the PR body fails the commit-msg block lint."""


class BlockMarkerError(ValueError):
    """Raised when :func:`extract_block` finds a malformed marker pair."""


def extract_block(body: str, marker_name: str) -> str | None:
    """Return the contents between the two ``==<marker_name>==`` markers.

    Returns ``None`` when the body contains no marker line. Raises
    :class:`BlockMarkerError` when exactly one marker line appears or
    more than two appear.
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
    """Return the contents of the ``==COMMIT_MSG==`` block."""
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
    return HTML_COMMENT_RE.sub("", text)


def block_lines(block: str) -> list[str]:
    """Return the meaningful lines of the block (comments stripped)."""
    stripped = strip_html_comments(block)
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
    """Reject body lines wider than the 72-char cap.

    Trailer lines are exempt — trailer values are routinely longer
    than the body wrap (a numeric-id-prefixed GitHub no-reply email
    alone is 60 chars). The kernel/git convention treats trailers as
    one-line-per-trailer regardless of width; wrapping a
    ``Signed-off-by:`` line breaks ``git interpret-trailers --parse``.
    """
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
            f"`{MARKER}` block has lines wider than {MAX_LINE_WIDTH} chars:\n{details}"
        )


def check_no_markdown(lines: Iterable[str]) -> None:
    """Reject the three reviewer-surface markdown shapes."""
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
    """Return True if ``token`` is a recognised trailer token."""
    return token.lower() in {t.lower() for t in KNOWN_TRAILER_TOKENS}


def _is_trailer_shape_line(line: str) -> bool:
    """Return True when ``line`` looks like a trailer-block line.

    Only matches colon-form trailers (``Token: value``); the bare
    ``Closes #N`` form was dropped in #566 so the canonical colon
    form is mechanically enforced on every PR.
    """
    trailer_match = TRAILER_RE.match(line)
    if trailer_match is not None and is_trailer_token(trailer_match.group(1)):
        if trailer_match.group(1).lower() == "fixes":
            return FIXES_SHA_TRAILER_LINE_RE.match(line) is not None
        return True
    return line.startswith("BREAKING CHANGE:")


def _trailer_block_start_index(lines: list[str]) -> int | None:
    """Return the 0-based index of the first line of the trailer block."""
    first_trailer_idx: int | None = None
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if not line.strip():
            continue
        if _is_trailer_shape_line(line):
            first_trailer_idx = idx
            continue
        break
    return first_trailer_idx


def parse_trailer_block(lines: list[str]) -> list[tuple[int, str, str]]:
    """Identify the contiguous trailer block at the tail of ``lines``.

    Only matches colon-form trailers (``Token: value``); the bare
    ``Closes #N`` form was dropped in #566 so the canonical colon
    form is mechanically enforced. A bare ``Closes #N`` therefore
    falls out of the trailer set, the body extends down to that line,
    and the layout / signoff checks fail with a clear message.
    """
    trailers: list[tuple[int, str, str]] = []
    for idx in range(len(lines), 0, -1):
        line = lines[idx - 1]
        if not line.strip():
            break
        match = TRAILER_RE.match(line)
        if match:
            token = match.group(1)
            value = line.split(":", 1)[1].lstrip()
            trailers.append((idx, token, value))
            continue
        break
    trailers.reverse()
    return trailers


def check_trailer_block_contiguity(lines: list[str]) -> None:
    """Reject blank lines between two consecutive trailers.

    ``git interpret-trailers --parse`` treats the first blank line
    above a candidate trailer as the body/trailer boundary — anything
    before that blank is body. A ``Closes #N`` separated from
    ``Signed-off-by:`` by a blank line therefore drops out of the
    trailer set.
    """
    first_trailer_idx = _trailer_block_start_index(lines)
    if first_trailer_idx is None:
        return
    region = lines[first_trailer_idx:]
    blank_offsets = [
        first_trailer_idx + offset for offset, line in enumerate(region) if not line.strip()
    ]
    if not blank_offsets:
        return
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
                f"line {blank_idx + 1} (between `{before.strip()}` and `{after.strip()}`)"
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


def check_no_bare_close_keyword(lines: list[str]) -> None:
    """Reject the bare ``Closes #N`` (no colon) form with a diagnostic.

    Issue #566 dropped the bare GitHub-auto-close-keyword form from the
    trailer-detection paths so the canonical ``Closes: #N`` (with colon)
    is mechanically enforced on every PR. Without this targeted check,
    a bare ``Closes #N`` would just fall out of the trailer set and the
    downstream layout / signoff checks would fire with a generic "no
    blank line between body and trailer block" message that doesn't
    name the actual cause — confusing for a contributor hitting the
    rule for the first time.

    The check fires on a whole-line match against
    :data:`BARE_CLOSE_KEYWORD_LINE_RE` so prose mentions like
    ``this closes #123 because foo`` don't false-positive — only lines
    clearly *intended* as a ``Closes:`` trailer whose author forgot
    the colon are flagged. Pairs with the colon-form positive coverage
    in the trailer-block tests.
    """
    for idx, line in enumerate(lines, start=1):
        match = BARE_CLOSE_KEYWORD_LINE_RE.match(line.rstrip())
        if match is None:
            continue
        keyword = match.group("keyword")
        ref = match.group("ref")
        raise ValidationError(
            f"`{MARKER}` block has a bare `{keyword} {ref}` "
            f"(no colon) trailer on line {idx}: `{line.strip()}`. "
            f"The bare form was dropped in #566 — use the canonical "
            f"`{keyword}: {ref}` (with colon) so the trailer matches "
            "the shape of every other git-trailer in the block."
        )


def check_blank_line_before_trailers(lines: list[str]) -> None:
    """Require at least one blank line between body and the trailer block."""
    first_trailer_idx = _trailer_block_start_index(lines)
    if first_trailer_idx is None or first_trailer_idx == 0:
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
    """If ``BREAKING CHANGE:`` appears, it must be the last non-sign-off line."""
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
                "pr_lint_validator.commit_msg."
            )
        if not value.strip():
            raise ValidationError(f"Trailer on line {idx} (`{token}:`) has an empty value.")


SIGNOFF_RE = re.compile(r"^Signed-off-by: .+ <.+@.+>\s*$")


def check_signoff_present(lines: list[str]) -> None:
    """Require at least one valid ``Signed-off-by:`` trailer in the block."""
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


FIXES_SHA_TRAILER_RE = re.compile(r'^[0-9a-fA-F]{7,}\s+\("[^"]+"\)\.?$')

GITHUB_ISSUE_REF_RE = re.compile(r"^(?:#\d+|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+)\.?$")


def _is_github_issue_ref(value: str) -> bool:
    return GITHUB_ISSUE_REF_RE.match(value) is not None


def check_first_line_non_blank(block: str) -> None:
    """Reject a leading blank line at the top of the block."""
    raw_lines = block.splitlines()
    if not raw_lines:
        return
    first_idx = next(
        (i for i, line in enumerate(raw_lines) if line.strip()),
        None,
    )
    if first_idx is None:
        return
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
    ``commit_title`` field, so a leading subject line in the block
    would render twice on ``main`` — once as the subject, once as the
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
    """Validate ``Fixes: <sha> ("subject")`` shape when SHA-style is used."""
    trailers = parse_trailer_block(lines)
    for idx, token, value in trailers:
        if token.lower() != "fixes":
            continue
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
    :func:`_trailer_block_start_index`) removed. Trailing blank lines
    inside the resulting region are stripped so a body whose last
    paragraph is followed by the canonical blank-then-trailers tail
    contributes only its content lines to the region.

    Used by :func:`check_verbose_body` to size the body alone,
    separately from the trailer block (which is structurally bounded
    — every trailer is one line).
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

    Returns the number of warnings emitted (0 or 1). Prints the
    warning to stderr; does not raise. The caller's exit code is
    unchanged — this is informational, surfaced in the workflow log
    so a reviewer can push back on the PR description before merge.
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
    # ``check_trailers`` runs before the contiguity / blank-line-before
    # checks so an unknown-token typo (``Cosed: #1`` for ``Closes: #1``)
    # surfaces as the more actionable "unknown trailer token" error,
    # rather than the misleading "no blank line before trailer block"
    # the layout checks would emit if the typo line failed
    # ``_is_trailer_shape_line``'s known-token gate.
    check_trailers(lines)
    # ``check_no_bare_close_keyword`` runs before the contiguity /
    # blank-line-before checks so a bare ``Closes #N`` surfaces the
    # targeted "use `Closes: #N` instead" diagnostic (issue #566)
    # rather than the generic "no blank line between body and trailer
    # block" message the layout checks would emit downstream — the
    # bare line falls out of the trailer set, the body extends down
    # to it, and `check_blank_line_before_trailers` would otherwise
    # fire without naming the actual cause.
    check_no_bare_close_keyword(lines)
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


# Inline self-test cases for the leading-subject-line check. Each tuple
# is ``(body, expect_pass, label)``. Post-#478 the block is body +
# trailers only, so any first line matching the Conventional-Commit
# subject shape is rejected — the PR title is the source for the
# squash commit subject.
_LEADING_SUBJECT_SELF_TEST_CASES: tuple[tuple[str, bool, str], ...] = (
    (
        "==COMMIT_MSG==\n"
        "Wire the foo into the bar.\n\n"
        "More rationale.\n\n"
        "Closes: #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n",
        True,
        "passing-plain-prose-first-line",
    ),
    (
        "==COMMIT_MSG==\n"
        "feature: wire the foo into the bar\n\n"
        "More rationale.\n\n"
        "Closes: #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n",
        False,
        "failing-feature-prefix-first-line",
    ),
    (
        "==COMMIT_MSG==\n"
        "improvement(ci): tighten the validator\n\n"
        "More rationale.\n\n"
        "Closes: #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n",
        False,
        "failing-improvement-scope-first-line",
    ),
    (
        "==COMMIT_MSG==\n"
        "The wheel was extracted before rule 8 landed in the script.\n\n"
        "More rationale.\n\n"
        "Closes: #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n",
        True,
        "passing-no-cc-shape-first-line",
    ),
)


def _build_verbose_body(word_count: int, words_per_line: int = 20) -> str:
    """Synthesise a ``==COMMIT_MSG==`` block whose body has ``word_count`` words.

    Each body line carries ``words_per_line`` 1-char placeholder words
    so the body stays under the 72-char line cap as long as
    ``words_per_line`` ≤ 36. The synthesized block is body + trailers
    only (no leading subject line) per #478 — the body region is the
    placeholder-word block alone, so the line / word counts the
    boundary cases assert match the sizing exactly. ``w`` is not a
    CC-shaped prefix, so :func:`check_no_leading_subject_line` doesn't
    match.
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
        "Closes: #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )


# Inline self-test cases for the verbose-body warning. Each tuple is
# ``(body, expect_warning, label)``.
_VERBOSE_BODY_SELF_TEST_CASES: tuple[tuple[str, bool, str], ...] = (
    (
        _build_verbose_body(300, words_per_line=5),
        True,
        "verbose-body-trips",
    ),
    (
        "==COMMIT_MSG==\n"
        "One paragraph of why this change exists. Two short lines is\n"
        "all the body needs because the diff is self-evident.\n\n"
        "Closes: #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n",
        False,
        "short-body-passes",
    ),
    (
        _build_verbose_body(VERBOSE_BODY_MAX_WORDS),
        False,
        "boundary-exact-max-words",
    ),
    (
        _build_verbose_body(VERBOSE_BODY_MAX_WORDS + 1),
        True,
        "boundary-one-over-max-words",
    ),
    (
        _build_verbose_body(VERBOSE_BODY_MAX_LINES, words_per_line=1),
        False,
        "boundary-exact-max-lines",
    ),
    (
        _build_verbose_body(VERBOSE_BODY_MAX_LINES + 1, words_per_line=1),
        True,
        "boundary-one-over-max-lines",
    ),
)


def run_self_test(write: Writer) -> int:
    """Run the inline self-test cases. ``write`` is a print-shaped callable.

    Returns 0 on full pass, 1 on any failure.
    """
    fail = 0
    for body, expect_pass, label in _LEADING_SUBJECT_SELF_TEST_CASES:
        try:
            validate(body)
        except ValidationError as err:
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
    for body, expect_warning, label in _VERBOSE_BODY_SELF_TEST_CASES:
        block = extract_commit_msg_block(body)
        lines = block_lines(block)
        warning_count = check_verbose_body(lines)
        actually_warned = warning_count > 0
        if actually_warned == expect_warning:
            write(f"ok: {label} (warning={'yes' if actually_warned else 'no'})")
        else:
            expected = "warning" if expect_warning else "no warning"
            actual = "warning" if actually_warned else "no warning"
            write(f"FAIL: {label}: expected {expected}, got {actual}", error=True)
            fail += 1
    total = len(_LEADING_SUBJECT_SELF_TEST_CASES) + len(_VERBOSE_BODY_SELF_TEST_CASES)
    if fail:
        write(f"{fail} self-test case(s) failed", error=True)
        return 1
    write(f"all {total} self-test cases passed")
    return 0


__all__ = [
    "BlockMarkerError",
    "MARKER",
    "MAX_LINE_WIDTH",
    "ValidationError",
    "VERBOSE_BODY_MAX_LINES",
    "VERBOSE_BODY_MAX_WORDS",
    "block_lines",
    "check_verbose_body",
    "extract_block",
    "extract_commit_msg_block",
    "run_self_test",
    "validate",
]
