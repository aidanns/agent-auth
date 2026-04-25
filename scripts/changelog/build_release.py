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
    bullet rather than fragmenting into separate ones.
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
    return out


def render_release_notes(entries: Sequence[ChangelogEntry], next_version: str) -> str:
    """Render the prose body shared by the release-PR and the GitHub Release.

    Output is plain prose — no markdown headings, no bullet lists, no
    checkboxes — so it satisfies ``validate-commit-msg-block.py``. The
    structure is one paragraph per group, prefixed with the group
    label, followed by the wrapped descriptions. Lines wrap at
    :data:`COMMIT_MSG_WRAP` characters.

    The shape:

        Release vX.Y.Z.

        Breaking changes:

        - <description line 1>
          <continuation>
        - <description line 2>

        Features:
        ...

    The leading bullets here are emitted with a single ``- `` prefix.
    The PR-body validator's "no bullet lists" rule is checked against
    the *==COMMIT_MSG== block*, which we render WITHOUT bullets — see
    ``render_commit_msg_block``. ``render_release_notes`` is the
    GitHub Release body; that surface accepts markdown.
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
    return out


def render_commit_msg_block(entries: Sequence[ChangelogEntry], next_version: str) -> str:
    """Render the body that goes inside the release-PR's ==COMMIT_MSG== block.

    Differs from ``render_release_notes`` in that:

    - No markdown bullets / dashes (the PR-body lint forbids them).
    - Prose is grouped by type and joined with semicolons.
    - Lines wrap at :data:`COMMIT_MSG_WRAP` chars.

    Uses prose rather than bullets so the validator's
    ``DISALLOWED_PATTERNS`` (markdown headings, bullet lists,
    numbered lists, task checkboxes) all pass.
    """
    grouped = _grouped(entries)
    paragraphs: list[str] = [f"Release v{next_version}."]
    for entry_type in SECTION_ORDER:
        bucket = grouped[entry_type]
        if not bucket:
            continue
        # One paragraph per group: "<heading>: <desc1>; <desc2>; ...".
        sentences = [_flatten_description(entry.description) for entry in bucket]
        paragraph = f"{SECTION_HEADINGS[entry_type]}: " + "; ".join(sentences)
        if not paragraph.endswith("."):
            paragraph += "."
        paragraphs.append(_wrap_paragraph(paragraph, COMMIT_MSG_WRAP))
    return "\n\n".join(paragraphs)


def _flatten_description(text: str) -> str:
    """Collapse a multi-line YAML description into a single sentence.

    YAML `description: |` block scalars routinely span multiple lines
    (the schema encourages prose). The ==COMMIT_MSG== block can't
    carry markdown bullets, so each entry is collapsed to a single
    semicolon-separated phrase. Trailing periods are trimmed so the
    final paragraph period (added by the caller) doesn't double up.
    """
    flat = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return flat.rstrip(".")


def _wrap_paragraph(text: str, width: int) -> str:
    """Greedy word-wrap; preserves URL tokens whole.

    `textwrap.fill` breaks long URLs at boundary chars; this trivial
    greedy wrapper instead keeps each whitespace-separated token
    intact so the rendered notes never split a link.
    """
    out_lines: list[str] = []
    current = ""
    for token in text.split():
        if not current:
            current = token
            continue
        if len(current) + 1 + len(token) <= width:
            current = f"{current} {token}"
        else:
            out_lines.append(current)
            current = token
    if current:
        out_lines.append(current)
    return "\n".join(out_lines)


def render_pr_body(plan: ReleasePlan) -> str:
    """Render the full release-PR description (==COMMIT_MSG== + Review notes).

    The body MUST satisfy `pr-lint.yml`:
    - One ``==COMMIT_MSG==`` block; well-wrapped prose; no markdown
      formatting inside the block.
    - The standard ``## Review notes`` section sits outside the block
      (it is dropped at squash-merge time).
    """
    commit_msg_body = render_commit_msg_block(plan.entries, plan.next_version)
    signoff = "Signed-off-by: github-actions[bot] <noreply@github.com>"
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


def _plan_to_json(plan: ReleasePlan) -> str:
    return json.dumps(
        {
            "current_version": plan.current_version,
            "next_version": plan.next_version,
            "branch": f"release/{plan.next_version}",
            "title": f"chore(release): {plan.next_version}",
            "moves": [{"src": str(m.src), "dst": str(m.dst)} for m in plan.moves],
            "changelog_section": plan.changelog_section,
            "release_notes": plan.release_notes,
            "pr_body": render_pr_body(plan),
        },
        indent=2,
    )


def _cmd_compute(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    plan = compute_release(repo_root, args.current_version)
    if plan is None:
        print(json.dumps({"skip": True, "reason": "no unreleased entries"}))
        return 0
    print(_plan_to_json(plan))
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
