# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Compute and apply a release plan from `changelog/@unreleased/*.yml`.

The :mod:`version_logic` module from #295 owns the bump table and the
``release-as`` invariant. This module wraps that library with the I/O
plumbing the release workflow (#296) needs:

- Read every ``changelog/@unreleased/pr-*.yml``.
- Compute the next version (``infer_next_version`` +
  ``apply_release_as`` after a ``validate_release_as`` gate).
- Plan the file moves under ``changelog/<X.Y.Z>/``.
- Render the new ``CHANGELOG.md`` section grouped by entry type.
- Render the prose used for both the release-PR's ``==COMMIT_MSG==``
  block and the GitHub Release body — *the two surfaces share the
  same byte-exact output* so the maintainer reviewing the PR sees
  exactly what consumers will see on the published release.

The CLI surface is intentionally thin: ``compute`` emits a JSON plan
on stdout (consumed by the release-pr workflow); ``apply`` performs
the moves + CHANGELOG rewrite on disk; ``render-notes`` re-renders
the body for the release-tag workflow against the *moved* YAMLs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Keep ``version_logic`` importable both when this file runs as a
# script and when imported as ``scripts.changelog.build_release``.
# Same idiom as ``lint.py``.
_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from version_logic import (  # noqa: E402  -- after sys.path setup
    ENTRY_FILENAME_PATTERN,
    ChangelogEntry,
    EntryType,
    apply_release_as,
    infer_next_version,
    parse_entry_file,
    validate_release_as,
)

UNRELEASED_DIR = Path("changelog/@unreleased")
CHANGELOG_FILE = Path("CHANGELOG.md")

# Order in which entry types render inside a release section. Matches
# the Palantir changelog convention: most-impactful first. Encoded as a
# constant so callers (tests, the release-tag workflow) can reuse the
# canonical ordering without re-deriving it.
SECTION_ORDER: tuple[EntryType, ...] = (
    EntryType.BREAK,
    EntryType.FEATURE,
    EntryType.IMPROVEMENT,
    EntryType.FIX,
    EntryType.DEPRECATION,
    EntryType.MIGRATION,
)

# Human-readable headings rendered inside CHANGELOG.md per group. The
# `### ` prefix matches the existing CHANGELOG.md style; the heading
# text itself is intentionally plural.
SECTION_HEADINGS: dict[EntryType, str] = {
    EntryType.BREAK: "Breaking changes",
    EntryType.FEATURE: "Features",
    EntryType.IMPROVEMENT: "Improvements",
    EntryType.FIX: "Fixes",
    EntryType.DEPRECATION: "Deprecations",
    EntryType.MIGRATION: "Migrations",
}

# Wrap width for prose paragraphs in the release-PR ==COMMIT_MSG== block.
# Matches `validate-commit-msg-block.py`'s `MAX_LINE_WIDTH`.
COMMIT_MSG_WRAP = 72

# Tokens shaped like `<digits>.` or `<digits>)` look like ordered-list
# items at a glance when they land at the start of a wrapped line.
# This recurs in changelog prose because numbered references such as
# `ADR 0011.`, `issue 1234)`, `RFC 2119`, or `PR 357.` are common —
# the noun and the digits sit on either side of a soft wrap point.
# `_wrap_paragraph` glues such a token to the previous one rather than
# letting it open a fresh line, even at the cost of a soft overflow.
#
# Pre-#345 this was a hard validator requirement (the
# `numbered list item` rule rejected any wrapped line opening with
# `<digits>[.)]`). The validator's list bans relaxed in #345, so the
# wrap behaviour is now a readability invariant rather than a CI
# gate; the regression test in
# ``tests/test_build_release.py::_assert_block_satisfies_validator``
# keeps the invariant honest.
NUMERIC_PERIOD_RE = re.compile(r"^\d+[.)]")

# `(#NNN)` PR-link suffix appended to every rendered release-note entry
# (#411). The PR number is derived from the YAML filename via
# ``ENTRY_FILENAME_PATTERN``; the suffix is auto-rendered by GitHub as
# a clickable PR link in commit bodies, CHANGELOG.md viewed on
# github.com, and release pages.
#
# `_wrap_paragraph` treats this token shape the same way it treats
# ``<digits>[.)]``: never let it open a wrapped line. A line break
# immediately before `(#383)` would visually divorce the link from
# the entry it points at, defeating the audience-link-back motive.
# The optional trailing-punctuation class covers the three places the
# suffix actually lands in rendered prose:
#   - bare `(#411)` — end of a CHANGELOG bullet line.
#   - `(#411).` — end of a sentence-terminated paragraph in the
#     ==COMMIT_MSG== block.
#   - `(#411);` — joining adjacent entries inside a single
#     semicolon-joined paragraph.
PR_SUFFIX_RE = re.compile(r"^\(#\d+\)[.;,:]?$")


@dataclass(frozen=True)
class FileMove:
    """One YAML file move planned by the release workflow.

    Captured as a structured pair (rather than a raw `(src, dst)`
    tuple) so callers thread the move through type checks. The paths
    are repo-root-relative.
    """

    src: Path
    dst: Path


@dataclass(frozen=True)
class ReleasePlan:
    """The full release-PR plan — version, moves, rendered surfaces.

    Pure data: building a plan does no disk writes. ``apply_release``
    consumes the plan to mutate the working tree.
    """

    current_version: str
    next_version: str
    entries: tuple[ChangelogEntry, ...]
    moves: tuple[FileMove, ...]
    changelog_section: str
    release_notes: str


# --- I/O helpers --------------------------------------------------------------


def list_unreleased_entries(repo_root: Path) -> list[ChangelogEntry]:
    """Parse every ``changelog/@unreleased/pr-*.yml`` under ``repo_root``.

    Files that don't match the schema raise ``ChangelogValidationError``
    from :mod:`version_logic` — propagated unchanged so the workflow
    fails closed (a malformed unreleased entry shouldn't silently drop
    out of the release).
    """
    target = repo_root / UNRELEASED_DIR
    if not target.is_dir():
        return []
    yamls = sorted(p for p in target.iterdir() if p.suffix == ".yml" and p.is_file())
    return [parse_entry_file(path) for path in yamls]


def list_versioned_entries(repo_root: Path, version: str) -> list[ChangelogEntry]:
    """Parse every ``changelog/<version>/pr-*.yml`` under ``repo_root``.

    Used by ``release-tag.yml`` to re-render the release body from the
    *moved* YAMLs after the release PR merges.
    """
    target = repo_root / "changelog" / version
    if not target.is_dir():
        return []
    yamls = sorted(p for p in target.iterdir() if p.suffix == ".yml" and p.is_file())
    return [parse_entry_file(path) for path in yamls]


# --- Pure planning ------------------------------------------------------------


def compute_release(
    repo_root: Path,
    current_version: str,
    *,
    today: _dt.date | None = None,
) -> ReleasePlan | None:
    """Compute a release plan from the entries currently under ``@unreleased/``.

    Returns ``None`` when there are no unreleased entries — the
    workflow short-circuits in that case rather than opening an empty
    release PR.

    Raises ``ChangelogValidationError`` (from ``version_logic``) when
    the entries don't satisfy the schema or the ``release-as``
    invariant. The release workflow MUST surface this — a malformed
    YAML on main is a maintainer-attention-required state.
    """
    entries = list_unreleased_entries(repo_root)
    if not entries:
        return None
    validate_release_as(entries, current_version)
    inferred = infer_next_version(current_version, entries)
    next_version = apply_release_as(inferred, entries)
    moves = tuple(_plan_moves(entries, next_version))
    section = render_changelog_section(entries, next_version, today or _dt.date.today())
    notes = render_release_notes(entries, next_version)
    return ReleasePlan(
        current_version=current_version,
        next_version=next_version,
        entries=tuple(entries),
        moves=moves,
        changelog_section=section,
        release_notes=notes,
    )


def _plan_moves(entries: Sequence[ChangelogEntry], next_version: str) -> list[FileMove]:
    target_dir = Path("changelog") / next_version
    out: list[FileMove] = []
    for entry in entries:
        # source_path may be absolute (from list_unreleased_entries) or
        # relative (from tests). Normalise to UNRELEASED_DIR + filename
        # so the planned destination is stable across both call sites.
        # Trim everything above the changelog/ root for absolute paths
        # so the move lives entirely under the workspace.
        src = entry.source_path
        src_repo_relative = src if not src.is_absolute() else _relative_to_changelog(src)
        out.append(FileMove(src=src_repo_relative, dst=target_dir / entry.source_path.name))
    return out


def _relative_to_changelog(path: Path) -> Path:
    """Return the ``changelog/...`` portion of an absolute YAML path.

    The workflow always works with repo-root-relative paths in plans.
    Splitting here (vs. `Path.relative_to(repo_root)`) avoids needing
    the repo root threaded through the planner.
    """
    parts = path.parts
    try:
        anchor = parts.index("changelog")
    except ValueError as exc:  # pragma: no cover -- defensive
        raise ValueError(
            f"expected source path under `changelog/`; got {path}",
        ) from exc
    return Path(*parts[anchor:])


# --- Rendering ----------------------------------------------------------------


def _grouped(entries: Sequence[ChangelogEntry]) -> dict[EntryType, list[ChangelogEntry]]:
    """Bucket entries by ``entry_type`` while preserving filename order."""
    buckets: dict[EntryType, list[ChangelogEntry]] = {t: [] for t in SECTION_ORDER}
    for entry in entries:
        buckets[entry.entry_type].append(entry)
    return buckets


def _pr_link_suffix(entry: ChangelogEntry) -> str:
    """Return ``" (#N)"`` for an entry, derived from its filename.

    Single-point append for the audience-link-back convention (#411):
    every rendered entry across CHANGELOG.md, the GitHub release body,
    and the release-PR ``==COMMIT_MSG==`` block carries the suffix so a
    reader can click straight through to the originating PR for the
    verbose context that the terse ``description:`` field omits.

    Sources the PR number from the YAML filename via
    :data:`ENTRY_FILENAME_PATTERN` rather than the human-authored
    ``links:`` array — the filename convention is single-PR and
    machine-readable; ``links:`` may carry multiple URLs (or none).
    Returns ``""`` when the filename doesn't match (fail-soft for
    legacy entries; ``check_present_file_naming`` in
    ``scripts/changelog/lint.py`` blocks new offenders at PR-time).
    """
    match = ENTRY_FILENAME_PATTERN.match(entry.source_path.name)
    if match is None:
        return ""
    return f" (#{match['pr_number']})"


def render_changelog_section(
    entries: Sequence[ChangelogEntry],
    next_version: str,
    today: _dt.date,
) -> str:
    """Render the new ``## [X.Y.Z] - YYYY-MM-DD`` section for CHANGELOG.md.

    Output format mirrors the historical Keep-a-Changelog-ish layout
    used in this repo (see existing ``CHANGELOG.md``): an H2 heading,
    one H3 per group, one bullet per entry, bullet text taken from
    the YAML's ``description`` field with the first non-empty line
    used as the bullet body and any extra text indented underneath.
    """
    grouped = _grouped(entries)
    lines: list[str] = [f"## [{next_version}] - {today.isoformat()}"]
    for entry_type in SECTION_ORDER:
        bucket = grouped[entry_type]
        if not bucket:
            continue
        lines.append("")
        lines.append(f"### {SECTION_HEADINGS[entry_type]}")
        lines.append("")
        for entry in bucket:
            lines.extend(_render_changelog_bullet(entry))
    lines.append("")
    return "\n".join(lines)


def _render_changelog_bullet(entry: ChangelogEntry) -> list[str]:
    """Return the lines of one CHANGELOG bullet for an entry.

    The first non-empty description line becomes the bullet text
    (`- ...`). Subsequent lines are emitted indented under it so a
    multi-paragraph YAML description renders as a single coherent
    bullet rather than fragmenting into separate ones. The PR-link
    suffix (#411) attaches to the *last* non-empty body line so it
    sits at the visible end of the entry — the eye finds the link
    where the entry finishes, not awkwardly mid-paragraph.
    """
    description_lines = [line.rstrip() for line in entry.description.splitlines()]
    # Drop leading blank lines so the first bullet line is text.
    while description_lines and not description_lines[0]:
        description_lines.pop(0)
    if not description_lines:
        return []
    out = [f"- {description_lines[0]}"]
    for line in description_lines[1:]:
        if line:
            out.append(f"  {line}")
        else:
            out.append("")
    _append_pr_link_suffix(out, _pr_link_suffix(entry))
    return out


def _append_pr_link_suffix(lines: list[str], suffix: str) -> None:
    """Mutate ``lines`` so ``suffix`` lands at the end of the last text line.

    The renderers may have padded `lines` with trailing blank entries
    (preserving paragraph spacing inside a multi-line description).
    Appending to ``lines[-1]`` blindly would push the suffix onto a
    blank padding row; walk backwards to the last non-empty line
    instead.
    """
    if not suffix:
        return
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx]:
            lines[idx] = f"{lines[idx]}{suffix}"
            return


def render_release_notes(entries: Sequence[ChangelogEntry], next_version: str) -> str:
    """Render the prose body shared by the release-PR and the GitHub Release.

    Output structure: one paragraph per group, prefixed with the
    group label, followed by the wrapped descriptions, with a
    leading ``- `` bullet per entry. Lines wrap at
    :data:`COMMIT_MSG_WRAP` characters.

    The release-PR ``==COMMIT_MSG==`` block has its own renderer
    (``render_commit_msg_block``) that emits the same
    heading-plus-bullets shape (#397). The GitHub Release body
    accepts arbitrary markdown either way; this renderer keeps
    its leading ``Release vX.Y.Z.`` header where the version is
    load-bearing, while the commit-msg renderer omits it because
    the ``chore(release): X.Y.Z`` subject already carries the
    version.

    The shape:

        Release vX.Y.Z.

        Breaking changes:

        - <description line 1>
          <continuation>
        - <description line 2>

        Features:
        ...

    The leading bullets here are emitted with a single ``- `` prefix.
    """
    grouped = _grouped(entries)
    parts: list[str] = [f"Release v{next_version}.", ""]
    for entry_type in SECTION_ORDER:
        bucket = grouped[entry_type]
        if not bucket:
            continue
        parts.append(f"{SECTION_HEADINGS[entry_type]}:")
        parts.append("")
        for entry in bucket:
            parts.extend(_render_notes_bullet(entry))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _render_notes_bullet(entry: ChangelogEntry) -> list[str]:
    description_lines = [line.rstrip() for line in entry.description.splitlines()]
    while description_lines and not description_lines[0]:
        description_lines.pop(0)
    if not description_lines:
        return []
    out: list[str] = [f"- {description_lines[0]}"]
    for line in description_lines[1:]:
        if line:
            out.append(f"  {line}")
        else:
            out.append("")
    _append_pr_link_suffix(out, _pr_link_suffix(entry))
    return out


def render_commit_msg_block(entries: Sequence[ChangelogEntry], next_version: str) -> str:
    """Render the body that goes inside the release-PR's ==COMMIT_MSG== block.

    Differs from ``render_release_notes`` in that:

    - No ``Release vX.Y.Z.`` header — the
      ``chore(release): X.Y.Z`` subject already conveys the
      version (#396).
    - Lines wrap at :data:`COMMIT_MSG_WRAP` chars.

    The shape per section is a heading line followed by one
    bullet per entry, regardless of how many entries land in the
    section. Single-entry sections render the same way as
    multi-entry ones so the body is uniformly scannable in
    ``git log`` and on the GitHub release page (#397):

        Improvements:
        - <description 1>
        - <description 2>

    Pre-#345 the validator's ``DISALLOWED_PATTERNS`` rejected
    bullets in the block, so this renderer originally emitted
    semicolon-joined prose. Post-#345 plain bullets are valid in
    the block; #397 switched to bullets because they scan more
    cleanly than a giant prose paragraph per heading. The
    validator's remaining ``DISALLOWED_PATTERNS`` (markdown
    headings, task checkboxes, image embeds) still pass trivially
    — the renderer emits none of those.
    """
    grouped = _grouped(entries)
    sections: list[str] = []
    for entry_type in SECTION_ORDER:
        bucket = grouped[entry_type]
        if not bucket:
            continue
        # One section per group: a heading line followed by one
        # bullet per entry. Each bullet is wrapped to
        # COMMIT_MSG_WRAP with continuation lines indented two
        # spaces so wrapped prose visually nests under its bullet.
        # Per-entry `(#N)` PR-link suffix (#411) is appended to the
        # bullet text before wrapping so ``_wrap_paragraph`` 's
        # ``PR_SUFFIX_RE`` binding rule keeps the suffix glued to the
        # preceding token across the wrap boundary.
        section_lines: list[str] = [f"{SECTION_HEADINGS[entry_type]}:"]
        for entry in bucket:
            sentence = _flatten_description(entry.description)
            if not sentence.endswith("."):
                sentence += "."
            suffix = _pr_link_suffix(entry)
            if suffix:
                # Suffix already carries a leading space (" (#N)") and
                # no trailing punctuation. Drop the sentence-ending
                # period before appending so the final bullet reads
                # ``…tail (#NNN)``, matching the changelog and release-
                # notes renderers (``_render_changelog_bullet``,
                # ``_render_notes_bullet`` — both delegate to
                # ``_append_pr_link_suffix``).
                sentence = f"{sentence.rstrip('.')}{suffix}"
            section_lines.append(_wrap_bullet(sentence, COMMIT_MSG_WRAP))
        sections.append("\n".join(section_lines))
    return "\n\n".join(sections)


def _wrap_bullet(text: str, width: int) -> str:
    """Render ``text`` as a ``- ``-prefixed bullet wrapped at ``width``.

    Continuation lines are indented two spaces so the wrapped
    prose visually nests under the bullet marker. Reuses
    :func:`_wrap_paragraph` for the underlying width / numeric-
    token handling, then prepends the marker / continuation
    indent line by line.
    """
    wrapped = _wrap_paragraph(text, width - 2)
    lines = wrapped.splitlines() or [""]
    out = [f"- {lines[0]}"]
    for line in lines[1:]:
        out.append(f"  {line}")
    return "\n".join(out)


def _flatten_description(text: str) -> str:
    """Collapse a multi-line YAML description into a single sentence.

    YAML `description: |` block scalars routinely span multiple lines
    (the schema encourages prose). The ==COMMIT_MSG== block renders
    one bullet per entry (#397), and a bullet body wraps cleaner if
    the source prose is one logical sentence rather than a sequence
    of hard-wrapped fragments — so the renderer collapses internal
    newlines to spaces here. Trailing periods are trimmed so the
    final period (re-added by the caller) doesn't double up.
    """
    flat = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return flat.rstrip(".")


def _wrap_paragraph(text: str, width: int) -> str:
    """Greedy word-wrap; preserves URL tokens whole.

    `textwrap.fill` breaks long URLs at boundary chars; this trivial
    greedy wrapper instead keeps each whitespace-separated token
    intact so the rendered notes never split a link.

    Also refuses to leave certain tokens alone at the start of a
    wrapped line, treating them as bound to the previous token:

    - **Numbered references** (``<digits>.`` / ``<digits>)``) — would
      look like an ordered list item even though they're actually a
      wrapped reference like ``ADR 0011.`` or ``issue 1234)``.
      Pre-#345 this was a hard validator requirement; post-#345 it's
      a readability invariant the renderer keeps because numbered-
      reference openers read as list bullets and confuse the eye.
    - **PR-link suffix** (``(#NNN)``) — the per-entry suffix appended
      by ``_pr_link_suffix`` (#411). Letting the wrap break before
      this token visually divorces the link from the entry it points
      at, defeating the audience-link-back motive.

    For both cases, when the bound token would otherwise overflow the
    current line, the previous token is moved down with it — preserving
    both the 72-char width rule and the bind-to-previous invariant.
    The fallback (the previous-token-plus-bound pair still overflows on
    its own line, or the line has no spare token to move) is to
    soft-overflow the current line rather than emit a line that opens
    with the bound token.
    """
    out_lines: list[str] = []
    current_tokens: list[str] = []

    def current_width() -> int:
        # Joined width = sum of token lengths + one space between each.
        return sum(len(t) for t in current_tokens) + max(len(current_tokens) - 1, 0)

    def flush() -> None:
        if current_tokens:
            out_lines.append(" ".join(current_tokens))
            current_tokens.clear()

    def is_bound_to_previous(token: str) -> bool:
        return bool(NUMERIC_PERIOD_RE.match(token)) or bool(PR_SUFFIX_RE.match(token))

    for token in text.split():
        if not current_tokens:
            current_tokens.append(token)
            continue
        bound = is_bound_to_previous(token)
        fits = current_width() + 1 + len(token) <= width
        if fits:
            current_tokens.append(token)
            continue
        if bound and len(current_tokens) >= 2:
            # Move the last token of the current line down with the
            # bound token so the wrap point sits between two ordinary
            # tokens. Preserves both the width rule and the
            # bind-to-previous invariant when the moved pair fits on
            # its own line; the rare case where it still overflows is
            # accepted as a soft overflow rather than re-introducing a
            # bound-token-shaped line start.
            last = current_tokens.pop()
            flush()
            current_tokens.extend([last, token])
            continue
        if bound:
            # Only one token on the line — moving it down would just
            # restart the same situation. Soft-overflow instead so the
            # bound token does not land at line start.
            current_tokens.append(token)
            continue
        flush()
        current_tokens.append(token)
    flush()
    return "\n".join(out_lines)


def _build_signoff(app_slug: str, user_id: str | int) -> str:
    """Render the DCO ``Signed-off-by:`` trailer for the release commit.

    The release-PR workflow runs as the ``agent-auth-release-bot``
    GitHub App (#398). The squash-merge commit body comes verbatim
    from the ==COMMIT_MSG== block this renderer emits, so the
    trailer must already match the App's bot identity — otherwise
    the released commit shows an author/committer of the App but a
    sign-off of ``github-actions[bot]``, which both reads wrong in
    ``git log`` and undermines the audit trail wiring done in
    ``b07fe58`` and ``d9225a4``.

    Shape: ``Signed-off-by: <slug>[bot] <<id>+<slug>[bot]@users.noreply.github.com>``.
    The numeric-id-prefixed no-reply form is the canonical
    ``[bot]`` email DCO auto-bypasses on
    (``.github/workflows/dco.yml``).
    """
    if not app_slug:
        raise ValueError("app_slug is required to render the release-bot signoff trailer")
    user_id_str = str(user_id).strip()
    if not user_id_str:
        raise ValueError("user_id is required to render the release-bot signoff trailer")
    return (
        f"Signed-off-by: {app_slug}[bot] "
        f"<{user_id_str}+{app_slug}[bot]@users.noreply.github.com>"
    )


def render_pr_body(plan: ReleasePlan, *, bot_app_slug: str, bot_user_id: str | int) -> str:
    """Render the full release-PR description (==COMMIT_MSG== + Review notes).

    The body MUST satisfy `pr-lint.yml`:
    - One ``==COMMIT_MSG==`` block; well-wrapped prose; no markdown
      formatting inside the block.
    - The standard ``## Review notes`` section sits outside the block
      (it is dropped at squash-merge time).

    ``bot_app_slug`` / ``bot_user_id`` identify the GitHub App
    whose token authors the release commit; they're threaded into
    the embedded ``Signed-off-by:`` trailer via :func:`_build_signoff`.
    Required (no fallback) so a missing-secret state surfaces as a
    loud error rather than silently signing off as
    ``github-actions[bot]`` (#398).
    """
    commit_msg_body = render_commit_msg_block(plan.entries, plan.next_version)
    signoff = _build_signoff(bot_app_slug, bot_user_id)
    block = f"==COMMIT_MSG==\n{commit_msg_body}\n\n{signoff}\n==COMMIT_MSG=="
    review = (
        "## Review notes\n\n"
        f"Auto-generated release PR for `v{plan.next_version}`.\n\n"
        f"Bumps from `v{plan.current_version}` based on "
        f"{len(plan.entries)} unreleased changelog entr"
        f"{'y' if len(plan.entries) == 1 else 'ies'}.\n\n"
        "### Files moved\n\n"
        + "\n".join(f"- `{move.src}` -> `{move.dst}`" for move in plan.moves)
        + "\n\n### Release notes preview\n\n"
        + plan.release_notes
    )
    return f"{block}\n\n{review}"


# --- Disk mutation ------------------------------------------------------------


def apply_release(plan: ReleasePlan, repo_root: Path) -> None:
    """Execute the planned moves and rewrite ``CHANGELOG.md`` in place.

    Idempotent within a clean checkout: running twice yields the same
    end state (the second run's moves no-op because the sources are
    already gone, and the CHANGELOG section is matched on the
    `## [X.Y.Z]` heading rather than blindly prepended).
    """
    target_dir = repo_root / "changelog" / plan.next_version
    target_dir.mkdir(parents=True, exist_ok=True)
    for move in plan.moves:
        src = repo_root / move.src
        dst = repo_root / move.dst
        if not src.exists():
            # Idempotent re-run: skip moves whose src is already gone.
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    _rewrite_changelog(repo_root / CHANGELOG_FILE, plan.changelog_section, plan.next_version)


_CHANGELOG_TITLE = "# Changelog"


def _rewrite_changelog(path: Path, new_section: str, next_version: str) -> None:
    """Insert ``new_section`` at the top of ``CHANGELOG.md``.

    Strategy: find the `# Changelog` title, drop everything from the
    title to (but not including) the first existing `## [` heading
    (the file's preamble), then write `title + new_section + rest`.
    If a `## [<next_version>]` section already exists (idempotent
    re-run), replace it instead of stacking a duplicate.
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else f"{_CHANGELOG_TITLE}\n"
    lines = existing.splitlines(keepends=True)
    # Locate the title.
    title_idx = next((i for i, line in enumerate(lines) if line.strip() == _CHANGELOG_TITLE), -1)
    if title_idx == -1:
        # No title — write a fresh file.
        path.write_text(f"{_CHANGELOG_TITLE}\n\n{new_section}\n", encoding="utf-8")
        return
    # Locate where existing release sections start (first `## [`).
    section_re = re.compile(r"^## \[")
    first_section_idx = next(
        (i for i in range(title_idx + 1, len(lines)) if section_re.match(lines[i])),
        len(lines),
    )
    # If a section for this version already exists, drop it (and its
    # body up to the next `## [` or EOF) so we replace rather than
    # stack.
    target_marker = f"## [{next_version}]"
    drop_start = next(
        (
            i
            for i in range(first_section_idx, len(lines))
            if lines[i].rstrip("\n").startswith(target_marker)
        ),
        -1,
    )
    if drop_start != -1:
        drop_end = next(
            (i for i in range(drop_start + 1, len(lines)) if section_re.match(lines[i])),
            len(lines),
        )
        lines = lines[:drop_start] + lines[drop_end:]
        first_section_idx = drop_start
    head = "".join(lines[: title_idx + 1])
    rest = "".join(lines[first_section_idx:])
    # Sandwich: title + blank + new_section + blank + rest. Trim
    # trailing whitespace on the section so we don't accumulate blank
    # lines on re-run.
    new_text = f"{head}\n{new_section.rstrip()}\n\n{rest}"
    path.write_text(new_text, encoding="utf-8")


# --- CLI ----------------------------------------------------------------------


def _plan_to_json(plan: ReleasePlan, *, bot_app_slug: str, bot_user_id: str) -> str:
    return json.dumps(
        {
            "current_version": plan.current_version,
            "next_version": plan.next_version,
            "branch": f"release/{plan.next_version}",
            "title": f"chore(release): {plan.next_version}",
            "moves": [{"src": str(m.src), "dst": str(m.dst)} for m in plan.moves],
            "changelog_section": plan.changelog_section,
            "release_notes": plan.release_notes,
            "pr_body": render_pr_body(plan, bot_app_slug=bot_app_slug, bot_user_id=bot_user_id),
        },
        indent=2,
    )


def _cmd_compute(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    plan = compute_release(repo_root, args.current_version)
    if plan is None:
        print(json.dumps({"skip": True, "reason": "no unreleased entries"}))
        return 0
    print(_plan_to_json(plan, bot_app_slug=args.bot_app_slug, bot_user_id=args.bot_user_id))
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    plan = compute_release(repo_root, args.current_version)
    if plan is None:
        print("build_release: no unreleased entries; nothing to apply", file=sys.stderr)
        return 0
    apply_release(plan, repo_root)
    print(f"build_release: applied release plan for v{plan.next_version}")
    return 0


def _cmd_render_notes(args: argparse.Namespace) -> int:
    """Re-render the release notes from the *moved* YAMLs at <version>/.

    Used by ``release-tag.yml``: by the time it runs, the
    ``@unreleased/`` directory is empty (the release-PR merge moved
    everything into ``<X.Y.Z>/``). Pulling the entries from the
    versioned subdirectory guarantees the GitHub Release body matches
    what the PR previewed.
    """
    repo_root = Path(args.repo_root).resolve()
    entries = list_versioned_entries(repo_root, args.version)
    if not entries:
        print(
            f"build_release: no entries under changelog/{args.version}/; "
            "release-tag may have been triggered for a non-release PR.",
            file=sys.stderr,
        )
        return 1
    print(render_release_notes(entries, args.version))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compute / apply / render the YAML-driven release plan. "
            "See scripts/changelog/build_release.py docstring."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    compute = sub.add_parser("compute", help="Print the release plan as JSON.")
    compute.add_argument("--repo-root", default=".")
    compute.add_argument(
        "--current-version",
        required=True,
        help="Current released version (X.Y.Z, no leading v).",
    )
    # The release commit's `Signed-off-by:` trailer must match the
    # GitHub App identity that authors the release commit (#398).
    # Both flags are required: a missing value would otherwise silently
    # render an unsigned-off or mis-attributed trailer, the exact
    # regression the issue surfaced.
    compute.add_argument(
        "--bot-app-slug",
        required=True,
        help=(
            "GitHub App slug for the release-bot identity (e.g. "
            "`agent-auth-release-bot`). Used to render the "
            "`Signed-off-by:` trailer inside the ==COMMIT_MSG== block."
        ),
    )
    compute.add_argument(
        "--bot-user-id",
        required=True,
        help=(
            "Numeric GitHub user-id for `<slug>[bot]`. Combined with "
            "`--bot-app-slug` to form the `<id>+<slug>[bot]@users."
            "noreply.github.com` no-reply email DCO auto-bypasses on."
        ),
    )
    compute.set_defaults(func=_cmd_compute)

    apply = sub.add_parser(
        "apply",
        help="Execute moves + CHANGELOG.md rewrite in the working tree.",
    )
    apply.add_argument("--repo-root", default=".")
    apply.add_argument("--current-version", required=True)
    apply.set_defaults(func=_cmd_apply)

    render_notes = sub.add_parser(
        "render-notes",
        help="Render release notes from the moved YAMLs (post-merge).",
    )
    render_notes.add_argument("--repo-root", default=".")
    render_notes.add_argument(
        "--version",
        required=True,
        help="Version directory to read (changelog/<version>/).",
    )
    render_notes.set_defaults(func=_cmd_render_notes)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    return int(args.func(args))


__all__ = [
    "COMMIT_MSG_WRAP",
    "CHANGELOG_FILE",
    "FileMove",
    "ReleasePlan",
    "SECTION_HEADINGS",
    "SECTION_ORDER",
    "UNRELEASED_DIR",
    "apply_release",
    "compute_release",
    "list_unreleased_entries",
    "list_versioned_entries",
    "render_changelog_section",
    "render_commit_msg_block",
    "render_pr_body",
    "render_release_notes",
]


if __name__ == "__main__":
    sys.exit(main())
