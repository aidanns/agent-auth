# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Predict the SemVer bump a PR will trigger and emit a JSON envelope.

Consumed by the ``release-impact-comment`` job in
``.github/workflows/pr-lint.yml`` (issue #406). The job posts an
idempotent PR comment surfacing the predicted bump so a reviewer can
catch a mislabelled YAML (e.g. a ``feature`` entry that should have
been ``improvement``) at PR-review time, before the next release goes
out and the version jumps unexpectedly.

The script is plumbing — it does no bump-computation of its own. It
walks ``changelog/@unreleased/*.yml`` and delegates to
``build_release.compute_release`` (the same wrapper ``release-pr.yml``
uses) so the prediction surfaced on the PR is byte-identical to the
plan the release workflow will execute.

## CLI surface

    python3 scripts/changelog/predict_release_impact.py \
        --repo-root . \
        --current-version 0.16.1

Emits one JSON object on stdout. Two shapes:

- ``{"predict": true, "current_version", "next_version", "bump",
   "drivers": [{"path", "type", "package"?}]}`` — when there is at
  least one entry under ``@unreleased/`` whose ``type:`` implies a
  non-NONE bump.
- ``{"predict": false, "reason"}`` — when there are no entries, or
  every entry's bump is NONE (impossible today since
  ``RELEASE_BUMPING_TYPES`` excludes ``chore`` at the schema layer,
  but the branch is kept for defensive cleanliness if the taxonomy
  ever grows a NONE-mapped release-bumping type).

The exit code is 0 in both shapes. Any ``ChangelogValidationError``
raised by the underlying parser propagates as a non-zero exit so the
workflow surfaces a malformed YAML rather than silently posting "no
release impact".
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

# Keep ``build_release`` (and therefore ``version_logic``) importable
# without forcing the caller to set ``PYTHONPATH``. The explicit insert
# mirrors the idiom in ``build_release.py`` / ``lint.py``: this script
# lives at ``scripts/changelog/`` (not on the default ``sys.path``) and
# may be invoked either as a path (``python3 scripts/.../predict.py``)
# or as a module (``python3 -m predict_release_impact``); the insert
# handles the third case where another script imports this one from a
# different working directory.
_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from build_release import compute_release  # noqa: E402  -- after sys.path setup
from version_logic import BumpType, ChangelogEntry, bump_for  # noqa: E402

# Human-readable label per bump category. Surfaced in the rendered
# comment body so a reviewer sees ``MINOR`` / ``PATCH`` / ``MAJOR``
# rather than the underlying enum repr. Kept here (not in
# ``commit_taxonomy``) because it is purely a presentation concern of
# this prediction surface — the enum's ``.name`` happens to spell the
# same letters today, but a future renaming would diverge.
_BUMP_LABELS: dict[BumpType, str] = {
    BumpType.NONE: "NONE",
    BumpType.PATCH: "PATCH",
    BumpType.MINOR: "MINOR",
    BumpType.MAJOR: "MAJOR",
}


def predict(
    repo_root: Path,
    current_version: str,
) -> dict[str, object]:
    """Return the predicted release impact envelope as a plain dict.

    Pure function: does no I/O beyond what ``compute_release`` already
    does (reading ``@unreleased/*.yml``). Suitable for unit testing.

    Raises ``ChangelogValidationError`` from ``version_logic`` if any
    YAML is malformed — propagated unchanged so a release-blocking
    schema break in an unreleased entry surfaces as a workflow failure
    rather than a misleading "no impact" comment.
    """
    plan = compute_release(repo_root, current_version)
    if plan is None:
        return {"predict": False, "reason": "no unreleased entries"}
    # ``compute_release`` returns a plan whenever there is at least one
    # YAML; the largest implied bump still needs to be derived from the
    # entries to populate the envelope's ``bump`` field. Re-using
    # ``bump_for`` here (rather than diffing the version strings) keeps
    # the bump category an explicit value the caller can render — and
    # matches the same enum the release workflow operates on.
    largest = max(bump_for(entry.entry_type, current_version) for entry in plan.entries)
    if largest == BumpType.NONE:
        # Defensive branch: the YAML schema rejects ``chore`` so every
        # entry today carries a non-NONE type. Keep the branch so a
        # future taxonomy that adds a release-bumping NONE type does
        # not silently post a noise comment.
        return {"predict": False, "reason": "all entries map to NONE bump"}
    return {
        "predict": True,
        "current_version": plan.current_version,
        "next_version": plan.next_version,
        "bump": _BUMP_LABELS[largest],
        "drivers": [_driver(entry, current_version) for entry in plan.entries],
    }


def _driver(entry: ChangelogEntry, current_version: str) -> dict[str, object]:
    """Render one entry as a comment-body driver hint.

    ``path`` is repo-root-relative — the caller renders it inside a
    Markdown ``code`` span, so any leading absolute path noise from a
    test fixture would muddy the comment. ``type`` is the entry's
    declared ``type:`` (the YAML literal, not the enum repr) so the
    rendered comment quotes the same string the contributor typed.
    ``package`` is included only when ``packages:`` was a single
    explicit entry — multi-package entries expand to ``null`` to keep
    the comment terse, and a workspace-wide entry (``packages: None``)
    omits the field rather than rendering ``null``.
    """
    package: str | None = None
    if entry.packages is not None and len(entry.packages) == 1:
        package = entry.packages[0]
    driver: dict[str, object] = {
        "path": _changelog_relative(entry.source_path),
        "type": entry.entry_type.value,
        "bump": _BUMP_LABELS[bump_for(entry.entry_type, current_version)],
    }
    if package is not None:
        driver["package"] = package
    return driver


def _changelog_relative(path: Path) -> str:
    """Trim everything above ``changelog/`` so the rendered path is stable.

    ``compute_release`` populates ``entry.source_path`` from
    ``Path.iterdir()`` results, which are absolute when the caller
    passed an absolute repo root. The release-pr workflow plans
    ``changelog/<version>/...`` destinations the same way; we re-use
    the same trim so the comment shows ``changelog/@unreleased/...``
    regardless of where the runner happened to check the repo out.
    """
    parts = path.parts
    try:
        anchor = parts.index("changelog")
    except ValueError:
        # No `changelog/` ancestor (only happens on hand-constructed
        # entries in tests) — fall back to the bare name so the
        # rendered comment never accidentally exposes a /tmp prefix.
        return path.name
    return str(Path(*parts[anchor:]))


# --- CLI ----------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Emit a JSON envelope predicting the SemVer bump implied "
            "by `changelog/@unreleased/*.yml`. Consumed by the "
            "`release-impact-comment` job in `.github/workflows/pr-lint.yml`."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root to scan (default: current directory).",
    )
    parser.add_argument(
        "--current-version",
        required=True,
        help="Current released version (X.Y.Z, no leading v).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    repo_root = Path(args.repo_root).resolve()
    envelope = predict(repo_root, args.current_version)
    json.dump(envelope, sys.stdout)
    sys.stdout.write("\n")
    return 0


__all__ = ["predict", "main"]


if __name__ == "__main__":
    sys.exit(main())
