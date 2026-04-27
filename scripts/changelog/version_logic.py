# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Changelog YAML schema, bump-table, and version-inference library.

Shared between the PR-time lint (``scripts/changelog/lint.py``) and the
release workflow (#296). The CLI helper (#297) and the bot-mediated
authoring path (#298) bind against the same surface.

## Public API

The following names form the stable surface that downstream sub-issues
import. Renaming or breaking the signatures requires updating those
sub-issues simultaneously.

### Enums and dataclasses

- ``EntryType`` — the six allowed values of the YAML ``type:`` field
  (feature, improvement, fix, break, deprecation, migration). String
  enum so callers can compare against literals.
- ``BumpType`` — the SemVer bump category implied by an entry on a
  given current version (none, patch, minor, major).
- ``ChangelogEntry`` — parsed representation of a single
  ``changelog/@unreleased/*.yml`` file. Carries the ``source_path``
  back to the file so error messages can name it.
- ``ChangelogValidationError`` — every failure in this module raises
  ``ChangelogValidationError``. The exception carries the offending
  ``path``, ``field`` (or ``None`` for whole-file failures), and a
  human-readable ``reason``.

### Functions

- ``parse_entry_file(path: pathlib.Path) -> ChangelogEntry`` — read
  one YAML file, validate the schema, return a typed entry. Raises
  ``ChangelogValidationError`` on any deviation.
- ``bump_for(entry_type: EntryType, current_version: str) -> BumpType``
  — single source of truth for the type-to-bump mapping. Encodes the
  0.x demote-to-minor rule.
- ``infer_next_version(current_version: str, entries: list[ChangelogEntry]) -> str``
  — apply the largest implied bump across all entries against
  ``current_version``. Honours ``release-as`` overrides only via
  ``apply_release_as`` (kept separate so the lint can validate the
  override against the *unoverridden* inferred version).
- ``apply_release_as(inferred_version: str, entries: list[ChangelogEntry]) -> str``
  — return the final release version after applying any ``release-as``
  override. Assumes ``validate_release_as`` has already passed.
- ``validate_release_as(entries: list[ChangelogEntry], current_version: str) -> None``
  — raise ``ChangelogValidationError`` if any ``release-as`` override
  is ``<=`` the inferred version, or if multiple entries carry
  conflicting overrides.

The library deliberately rejects parsing ambiguities up front so
callers get a single failure mode (``ChangelogValidationError``)
rather than a mix of ``ValueError``, ``KeyError``, ``TypeError``.
"""

from __future__ import annotations

import enum
import importlib.util
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Single source of truth for the type→release-impact mapping lives in
# ``scripts/lint/commit_taxonomy``. ``version_logic`` consumes the
# canonical data and re-exposes it under the names this module's
# downstream callers (lint, release workflow, CLI) already import:
# ``BumpType`` (the enum) and ``EntryType`` (the YAML ``type:`` enum
# of release-bumping types). Adding a new PR-title prefix is therefore
# a single-file edit in ``commit_taxonomy``.
#
# Loaded via ``importlib.util.spec_from_file_location`` rather than a
# regular ``import`` so this production module never mutates
# ``sys.path``. A ``sys.path.insert`` here would be inherited by every
# caller that imports ``version_logic`` (lint, release workflow, CLI,
# tests), and could shadow same-named modules in unrelated
# environments. Same pattern that ``scripts/changelog/bot.py`` uses to
# load ``validate-commit-msg-block.py`` without touching ``sys.path``.
#
# The loaded module is cached under ``sys.modules["commit_taxonomy"]``
# so a subsequent bare-name ``import commit_taxonomy`` (used by tests
# whose ``conftest.py`` puts ``scripts/lint/`` on the path) returns
# *this* module instance — preserving identity contracts like
# ``version_logic.BumpType is commit_taxonomy.ReleaseImpact``. The
# inverse case (this module's load happens after a bare-name import
# already populated ``sys.modules``) reuses the cached module instead
# of re-executing the file, for the same reason.
_COMMIT_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "lint" / "commit_taxonomy.py"
_commit_taxonomy = sys.modules.get("commit_taxonomy")
if _commit_taxonomy is None:
    _spec = importlib.util.spec_from_file_location("commit_taxonomy", _COMMIT_TAXONOMY_PATH)
    if _spec is None or _spec.loader is None:  # pragma: no cover - import-time guard
        raise ImportError(f"cannot load commit_taxonomy from {_COMMIT_TAXONOMY_PATH}")
    _commit_taxonomy = importlib.util.module_from_spec(_spec)
    sys.modules["commit_taxonomy"] = _commit_taxonomy
    _spec.loader.exec_module(_commit_taxonomy)
ALLOWED_TYPES = _commit_taxonomy.ALLOWED_TYPES
RELEASE_BUMPING_TYPES = _commit_taxonomy.RELEASE_BUMPING_TYPES
ReleaseImpact = _commit_taxonomy.ReleaseImpact

# Filename pattern used by both the schema parser and the lint's
# file-presence/file-naming checks. Captures the PR number so the lint
# can verify the embedded number matches the PR being scanned.
ENTRY_FILENAME_PATTERN = re.compile(r"^pr-(?P<pr_number>\d+)-[A-Za-z0-9_-]+\.yml$")

# Workspace member set is informational here — the actual list lives in
# pyproject.toml ``[tool.uv.workspace]`` and is re-derived by the lint
# from the on-disk ``packages/`` tree. Keeping the parser unaware of
# that dynamic list lets us exercise ``parse_entry_file`` in unit tests
# with arbitrary package names.

_SEMVER_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")


# ``EntryType`` is derived from the canonical taxonomy: it's exactly
# ``ALLOWED_TYPES`` minus ``chore`` (chore PRs do not produce a
# changelog YAML, so ``chore`` is not a valid YAML ``type:`` value).
# Using ``enum.Enum(...)`` functional form lets us name members from
# the canonical strings without re-typing them — the (NAME, value)
# pairs are generated from ``RELEASE_BUMPING_TYPES``.
EntryType = enum.Enum(
    "EntryType",
    {name.upper(): name for name in sorted(RELEASE_BUMPING_TYPES)},
    type=str,
)
EntryType.__doc__ = (
    "Allowed values of the YAML ``type:`` field.\n\n"
    "String-valued so YAML literals compare directly: "
    "``EntryType.FEATURE == 'feature'`` is ``True``. Members are "
    "derived from ``commit_taxonomy.RELEASE_BUMPING_TYPES``; adding a "
    "new release-bumping type is a single-line edit there."
)


# ``BumpType`` is the historical name this module exposed before #405
# extracted ``ReleaseImpact`` to ``commit_taxonomy``. Kept as an alias
# so every existing caller (the lint, ``build_release``, the CLI, the
# tests) keeps importing ``BumpType`` from ``version_logic`` unchanged.
BumpType = ReleaseImpact


@dataclass(frozen=True)
class ChangelogEntry:
    """Parsed representation of a single ``@unreleased/*.yml`` file.

    The ``source_path`` lets error messages name the offending file
    when downstream callers (lint, release workflow) aggregate entries
    across the whole directory.
    """

    entry_type: EntryType
    description: str
    links: tuple[str, ...]
    packages: tuple[str, ...] | None
    release_as: str | None
    source_path: Path

    @property
    def is_workspace_wide(self) -> bool:
        """Whether the entry contributes to the workspace-level bump.

        ``packages: None`` (the field was absent) means a workspace-wide
        change. An explicit empty list is rejected by the parser as
        ambiguous.
        """
        return self.packages is None


class ChangelogValidationError(ValueError):
    """Single failure mode for every parsing / validation deviation.

    Callers format the message with ``str(exc)``; the structured
    fields (``path``, ``field``, ``reason``) are exposed so the lint
    can render GitHub annotations with file/line provenance.
    """

    def __init__(
        self,
        path: Path | None,
        field: str | None,
        reason: str,
    ) -> None:
        self.path = path
        self.field = field
        self.reason = reason
        location = f"{path}" if path is not None else "<input>"
        if field is not None:
            location = f"{location}: {field}"
        super().__init__(f"{location}: {reason}")


# --- Bump table ---------------------------------------------------------------

# Type → bump mapping for the post-1.x case, derived from the canonical
# taxonomy in ``commit_taxonomy.ALLOWED_TYPES``. The 0.x demote-to-minor
# rule for ``break`` is applied separately in ``bump_for``.
_BUMP_TABLE_POST_1X: dict[EntryType, BumpType] = {
    entry_type: ALLOWED_TYPES[entry_type.value] for entry_type in EntryType
}


def _parse_semver(
    version: str, *, source: Path | None = None, field_name: str | None = None
) -> tuple[int, int, int]:
    """Parse ``X.Y.Z`` into an int triple. Raises ``ChangelogValidationError``."""
    match = _SEMVER_PATTERN.match(version)
    if match is None:
        raise ChangelogValidationError(
            source,
            field_name,
            f"version must be `X.Y.Z` (got {version!r})",
        )
    return int(match["major"]), int(match["minor"]), int(match["patch"])


def bump_for(entry_type: EntryType, current_version: str) -> BumpType:
    """Return the bump implied by ``entry_type`` against ``current_version``.

    ``break`` demotes to ``MINOR`` while ``current_version`` is in the
    ``0.x`` range (per ADR 0026 § Pre-1.0 behaviour and the issue body).
    """
    major, _minor, _patch = _parse_semver(current_version)
    bump = _BUMP_TABLE_POST_1X[entry_type]
    if major == 0 and bump == BumpType.MAJOR:
        return BumpType.MINOR
    return bump


def _apply_bump(current: tuple[int, int, int], bump: BumpType) -> tuple[int, int, int]:
    major, minor, patch = current
    if bump == BumpType.MAJOR:
        return (major + 1, 0, 0)
    if bump == BumpType.MINOR:
        return (major, minor + 1, 0)
    if bump == BumpType.PATCH:
        return (major, minor, patch + 1)
    return current


def infer_next_version(current_version: str, entries: Sequence[ChangelogEntry]) -> str:
    """Apply the largest bump implied by ``entries`` against ``current_version``.

    Returns the *natural* next version with no ``release-as`` override
    applied. Use ``apply_release_as`` afterwards to honour overrides
    (kept separate so the lint can validate ``release-as`` against the
    unoverridden version, per the issue's "must be strictly greater
    than the inferred version" rule).

    Raises ``ChangelogValidationError`` if ``current_version`` is not
    valid SemVer.
    """
    current = _parse_semver(current_version)
    if not entries:
        return current_version
    largest = max(bump_for(entry.entry_type, current_version) for entry in entries)
    if largest == BumpType.NONE:
        return current_version
    next_tuple = _apply_bump(current, largest)
    return f"{next_tuple[0]}.{next_tuple[1]}.{next_tuple[2]}"


def _collect_release_as(entries: Iterable[ChangelogEntry]) -> list[ChangelogEntry]:
    return [entry for entry in entries if entry.release_as is not None]


def validate_release_as(
    entries: Sequence[ChangelogEntry],
    current_version: str,
) -> None:
    """Validate the ``release-as`` invariant across all entries.

    Two failure modes:

    1. **Conflict** — two or more entries carry different
       ``release-as`` values. The release workflow has no rule to pick
       between them, so the lint forces the contributor to reconcile.
    2. **Non-monotonic** — the (agreed) ``release-as`` value is not
       strictly greater than ``infer_next_version(current_version,
       entries)`` ignoring the override. A release-as that demotes the
       implied version is meaningless; an equal value is also rejected
       so the override always carries semantic intent.

    Idempotent agreement (multiple entries with the same value) passes.
    """
    overrides = _collect_release_as(entries)
    if not overrides:
        return

    # Check 1: conflicting values.
    distinct = {entry.release_as for entry in overrides}
    if len(distinct) > 1:
        rendered = ", ".join(f"{entry.source_path.name}={entry.release_as}" for entry in overrides)
        raise ChangelogValidationError(
            overrides[0].source_path,
            "release-as",
            f"conflicting release-as values across entries ({rendered})",
        )

    # Check 2: monotonic against the natural inferred version.
    override_value = overrides[0].release_as
    assert override_value is not None  # narrowed by the branch above
    inferred = infer_next_version(current_version, list(entries))
    override_tuple = _parse_semver(
        override_value,
        source=overrides[0].source_path,
        field_name="release-as",
    )
    inferred_tuple = _parse_semver(inferred)
    if override_tuple <= inferred_tuple:
        raise ChangelogValidationError(
            overrides[0].source_path,
            "release-as",
            (
                f"release-as {override_value!r} must be strictly greater than "
                f"the inferred next version {inferred!r}"
            ),
        )


def apply_release_as(inferred_version: str, entries: Sequence[ChangelogEntry]) -> str:
    """Return the final version, applying any ``release-as`` override.

    Pre-condition: ``validate_release_as`` has been called with the
    same entries against the corresponding ``current_version`` and
    raised nothing — so any override here is known to be greater than
    ``inferred_version`` and consistent across files.
    """
    overrides = _collect_release_as(entries)
    if not overrides:
        return inferred_version
    override_value = overrides[0].release_as
    assert override_value is not None
    return override_value


# --- YAML parsing -------------------------------------------------------------

_REQUIRED_NESTED_KEYS = {"description"}
_ALLOWED_NESTED_KEYS = {"description", "links"}
_ALLOWED_TOP_LEVEL_KEYS = {"type", "packages", "release-as"} | {t.value for t in EntryType}


def parse_entry_file(path: Path) -> ChangelogEntry:
    """Parse one ``changelog/@unreleased/*.yml`` file into a ``ChangelogEntry``.

    Raises ``ChangelogValidationError`` for any deviation: malformed
    YAML, missing or unknown ``type``, missing/extra nested key,
    type/nested-key mismatch, malformed ``release-as``, etc.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ChangelogValidationError(path, None, f"malformed YAML: {exc}") from exc
    except OSError as exc:
        raise ChangelogValidationError(path, None, f"cannot read file: {exc}") from exc

    if raw is None:
        raise ChangelogValidationError(path, None, "file is empty")
    if not isinstance(raw, dict):
        raise ChangelogValidationError(
            path,
            None,
            f"expected a YAML mapping at the top level (got {type(raw).__name__})",
        )

    # Required: `type:`.
    type_value = raw.get("type")
    if type_value is None:
        raise ChangelogValidationError(path, "type", "required field missing")
    if not isinstance(type_value, str):
        raise ChangelogValidationError(
            path,
            "type",
            f"must be a string (got {type(type_value).__name__})",
        )
    try:
        entry_type = EntryType(type_value)
    except ValueError as exc:
        allowed = ", ".join(sorted(t.value for t in EntryType))
        raise ChangelogValidationError(
            path,
            "type",
            f"unknown type {type_value!r}; allowed values: {allowed}",
        ) from exc

    # Reject unknown top-level keys so typos don't slip through silently.
    unknown_top_level = set(raw.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown_top_level:
        rendered = ", ".join(sorted(unknown_top_level))
        raise ChangelogValidationError(
            path,
            None,
            f"unknown top-level keys: {rendered}",
        )

    # Required: nested key whose name matches `type:`.
    nested_key = entry_type.value
    nested_value = raw.get(nested_key)
    if nested_value is None:
        raise ChangelogValidationError(
            path,
            nested_key,
            f"required nested key {nested_key!r} missing (matches `type: {nested_key}`)",
        )

    # The nested key must be the only `EntryType`-named key — multiple
    # would be ambiguous about which one the parser should read.
    sibling_type_keys = {t.value for t in EntryType} & set(raw.keys()) - {nested_key}
    if sibling_type_keys:
        rendered = ", ".join(sorted(sibling_type_keys))
        raise ChangelogValidationError(
            path,
            None,
            (
                f"nested key {nested_key!r} (from `type: {nested_key}`) collides with "
                f"sibling type-named keys: {rendered}"
            ),
        )

    if not isinstance(nested_value, dict):
        raise ChangelogValidationError(
            path,
            nested_key,
            f"must be a mapping (got {type(nested_value).__name__})",
        )

    nested_keys = set(nested_value.keys())
    missing_nested = _REQUIRED_NESTED_KEYS - nested_keys
    if missing_nested:
        rendered = ", ".join(sorted(missing_nested))
        raise ChangelogValidationError(
            path,
            f"{nested_key}.{rendered}",
            "required nested field missing",
        )
    unknown_nested = nested_keys - _ALLOWED_NESTED_KEYS
    if unknown_nested:
        rendered = ", ".join(sorted(unknown_nested))
        raise ChangelogValidationError(
            path,
            nested_key,
            f"unknown nested keys: {rendered}",
        )

    description = nested_value["description"]
    if not isinstance(description, str) or not description.strip():
        raise ChangelogValidationError(
            path,
            f"{nested_key}.description",
            "must be a non-empty string",
        )

    links_raw = nested_value.get("links", [])
    links = _parse_links(links_raw, path=path, field_name=f"{nested_key}.links")

    packages = _parse_packages(raw.get("packages", _SENTINEL_ABSENT), path=path)

    release_as_raw = raw.get("release-as")
    release_as = _parse_release_as(release_as_raw, path=path)

    return ChangelogEntry(
        entry_type=entry_type,
        description=description,
        links=links,
        packages=packages,
        release_as=release_as,
        source_path=path,
    )


_SENTINEL_ABSENT = object()


def _parse_links(value: Any, *, path: Path, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ChangelogValidationError(
            path,
            field_name,
            f"must be a list of strings (got {type(value).__name__})",
        )
    parsed: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ChangelogValidationError(
                path,
                f"{field_name}[{index}]",
                f"must be a string (got {type(item).__name__})",
            )
        parsed.append(item)
    return tuple(parsed)


def _parse_packages(value: Any, *, path: Path) -> tuple[str, ...] | None:
    """Parse the optional ``packages:`` field.

    ``None`` (absent) means workspace-wide; an explicit empty list is
    rejected as ambiguous (use the absent-key form instead).
    """
    if value is _SENTINEL_ABSENT or value is None:
        return None
    if not isinstance(value, list):
        raise ChangelogValidationError(
            path,
            "packages",
            f"must be a list of workspace member names (got {type(value).__name__})",
        )
    if not value:
        raise ChangelogValidationError(
            path,
            "packages",
            "explicit empty list is ambiguous; omit the field for workspace-wide entries",
        )
    parsed: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ChangelogValidationError(
                path,
                f"packages[{index}]",
                f"must be a non-empty string (got {item!r})",
            )
        parsed.append(item)
    return tuple(parsed)


def _parse_release_as(value: Any, *, path: Path) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ChangelogValidationError(
            path,
            "release-as",
            f"must be a string in `X.Y.Z` form (got {type(value).__name__})",
        )
    # Validate the SemVer shape early so downstream callers can rely on it.
    _parse_semver(value, source=path, field_name="release-as")
    return value


# --- Workspace-aware validation ------------------------------------------------


def validate_packages_against_workspace(
    entry: ChangelogEntry,
    known_packages: Iterable[str],
) -> None:
    """Verify each ``packages:`` entry names a real workspace member.

    Skips the check for workspace-wide entries (``packages: None``).
    """
    if entry.packages is None:
        return
    known = set(known_packages)
    unknown = [name for name in entry.packages if name not in known]
    if unknown:
        rendered = ", ".join(sorted(unknown))
        raise ChangelogValidationError(
            entry.source_path,
            "packages",
            f"unknown workspace members: {rendered}",
        )


# Re-exported public surface — keeps the import-from spelling stable
# even if internals are reshuffled.
__all__ = [
    "BumpType",
    "ChangelogEntry",
    "ChangelogValidationError",
    "ENTRY_FILENAME_PATTERN",
    "EntryType",
    "apply_release_as",
    "bump_for",
    "infer_next_version",
    "parse_entry_file",
    "validate_packages_against_workspace",
    "validate_release_as",
]
