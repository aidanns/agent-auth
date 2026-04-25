# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for ``scripts/changelog/version_logic.py``.

Public-API only: every test exercises ``parse_entry_file``,
``bump_for``, ``infer_next_version``, ``validate_release_as``, or
``validate_packages_against_workspace``. No tests reach into private
parser state.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from version_logic import (
    BumpType,
    ChangelogEntry,
    ChangelogValidationError,
    EntryType,
    apply_release_as,
    bump_for,
    infer_next_version,
    parse_entry_file,
    validate_packages_against_workspace,
    validate_release_as,
)


def _entry(
    entry_type: EntryType = EntryType.FIX,
    *,
    release_as: str | None = None,
    packages: tuple[str, ...] | None = None,
    source_path: Path | None = None,
) -> ChangelogEntry:
    return ChangelogEntry(
        entry_type=entry_type,
        description="example",
        links=(),
        packages=packages,
        release_as=release_as,
        source_path=source_path or Path("changelog/@unreleased/pr-1-fixture.yml"),
    )


# --- bump_for ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry_type", "current_version", "expected"),
    [
        # 0.x rows (issue's bump table column 1).
        (EntryType.FEATURE, "0.4.0", BumpType.MINOR),
        (EntryType.IMPROVEMENT, "0.4.0", BumpType.PATCH),
        (EntryType.FIX, "0.4.0", BumpType.PATCH),
        (EntryType.BREAK, "0.4.0", BumpType.MINOR),  # demoted from MAJOR
        (EntryType.DEPRECATION, "0.4.0", BumpType.PATCH),
        (EntryType.MIGRATION, "0.4.0", BumpType.PATCH),
        # 1.x+ rows (issue's bump table column 2).
        (EntryType.FEATURE, "1.0.0", BumpType.MINOR),
        (EntryType.IMPROVEMENT, "1.0.0", BumpType.PATCH),
        (EntryType.FIX, "1.0.0", BumpType.PATCH),
        (EntryType.BREAK, "1.0.0", BumpType.MAJOR),
        (EntryType.DEPRECATION, "1.0.0", BumpType.PATCH),
        (EntryType.MIGRATION, "1.0.0", BumpType.PATCH),
    ],
)
def test_bump_for_returns_bump_per_table_row(
    entry_type: EntryType, current_version: str, expected: BumpType
) -> None:
    assert bump_for(entry_type, current_version) == expected


def test_bump_for_demotes_break_to_minor_on_2x_zero_minor():
    """Even on `2.0.0`, a `break` is MAJOR (no demotion above 0.x)."""
    assert bump_for(EntryType.BREAK, "2.0.0") == BumpType.MAJOR


def test_bump_for_rejects_invalid_current_version():
    with pytest.raises(ChangelogValidationError):
        bump_for(EntryType.FIX, "not-a-version")


# --- infer_next_version ------------------------------------------------------


def test_infer_next_version_picks_largest_bump_across_entries():
    entries = [
        _entry(EntryType.FIX),
        _entry(EntryType.FEATURE),
        _entry(EntryType.IMPROVEMENT),
    ]
    # FEATURE (MINOR) wins.
    assert infer_next_version("0.4.2", entries) == "0.5.0"


def test_infer_next_version_demotes_break_in_zero_x():
    entries = [_entry(EntryType.BREAK)]
    assert infer_next_version("0.4.2", entries) == "0.5.0"


def test_infer_next_version_break_bumps_major_post_one_x():
    entries = [_entry(EntryType.BREAK), _entry(EntryType.FIX)]
    assert infer_next_version("1.2.3", entries) == "2.0.0"


def test_infer_next_version_returns_current_when_no_entries():
    assert infer_next_version("0.4.2", []) == "0.4.2"


def test_infer_next_version_patch_only_increments_patch():
    entries = [_entry(EntryType.FIX), _entry(EntryType.IMPROVEMENT)]
    assert infer_next_version("0.4.2", entries) == "0.4.3"


# --- validate_release_as -----------------------------------------------------


def test_validate_release_as_passes_when_no_overrides():
    entries = [_entry(EntryType.FIX)]
    validate_release_as(entries, "0.4.2")  # does not raise


def test_validate_release_as_passes_when_override_strictly_greater():
    entries = [_entry(EntryType.FIX, release_as="1.0.0")]
    # Inferred would be 0.4.3; 1.0.0 > 0.4.3.
    validate_release_as(entries, "0.4.2")


def test_validate_release_as_passes_when_overrides_agree():
    """Same value across multiple files is idempotent agreement, not a conflict."""
    entries = [
        _entry(EntryType.FIX, release_as="1.0.0", source_path=Path("pr-1-a.yml")),
        _entry(EntryType.FEATURE, release_as="1.0.0", source_path=Path("pr-1-b.yml")),
    ]
    validate_release_as(entries, "0.4.2")


def test_validate_release_as_rejects_override_equal_to_inferred():
    """Boundary: override == inferred fails (must be strictly greater)."""
    entries = [_entry(EntryType.FEATURE, release_as="0.5.0")]
    with pytest.raises(ChangelogValidationError) as exc_info:
        validate_release_as(entries, "0.4.2")
    assert "strictly greater" in str(exc_info.value)
    assert exc_info.value.field == "release-as"


def test_validate_release_as_rejects_override_less_than_inferred():
    entries = [_entry(EntryType.FEATURE, release_as="0.4.3")]
    with pytest.raises(ChangelogValidationError) as exc_info:
        validate_release_as(entries, "0.4.2")
    assert "strictly greater" in str(exc_info.value)


def test_validate_release_as_rejects_conflicting_overrides():
    entries = [
        _entry(EntryType.FIX, release_as="1.0.0", source_path=Path("pr-1-a.yml")),
        _entry(EntryType.FIX, release_as="2.0.0", source_path=Path("pr-1-b.yml")),
    ]
    with pytest.raises(ChangelogValidationError) as exc_info:
        validate_release_as(entries, "0.4.2")
    assert "conflicting" in str(exc_info.value)


def test_apply_release_as_returns_inferred_when_no_override():
    assert apply_release_as("0.5.0", [_entry(EntryType.FEATURE)]) == "0.5.0"


def test_apply_release_as_returns_override_when_present():
    entries = [_entry(EntryType.FEATURE, release_as="1.0.0")]
    assert apply_release_as("0.5.0", entries) == "1.0.0"


# --- parse_entry_file --------------------------------------------------------


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_entry_file_parses_minimal_feature(tmp_path: Path):
    yaml = """\
type: feature
feature:
  description: New thing.
"""
    path = _write(tmp_path / "pr-1-x.yml", yaml)
    entry = parse_entry_file(path)
    assert entry.entry_type is EntryType.FEATURE
    assert entry.description == "New thing."
    assert entry.links == ()
    assert entry.packages is None
    assert entry.is_workspace_wide
    assert entry.release_as is None
    assert entry.source_path == path


def test_parse_entry_file_parses_full_schema(tmp_path: Path):
    yaml = """\
type: break
break:
  description: Drops /v0 endpoint.
  links:
    - https://github.com/aidanns/agent-auth/pull/100
packages:
  - agent-auth
  - agent-auth-common
release-as: 1.0.0
"""
    path = _write(tmp_path / "pr-100-graduate.yml", yaml)
    entry = parse_entry_file(path)
    assert entry.entry_type is EntryType.BREAK
    assert entry.links == ("https://github.com/aidanns/agent-auth/pull/100",)
    assert entry.packages == ("agent-auth", "agent-auth-common")
    assert entry.release_as == "1.0.0"
    assert not entry.is_workspace_wide


def test_parse_entry_file_rejects_missing_type(tmp_path: Path):
    yaml = """\
feature:
  description: x.
"""
    path = _write(tmp_path / "pr-1-x.yml", yaml)
    with pytest.raises(ChangelogValidationError) as exc_info:
        parse_entry_file(path)
    assert exc_info.value.field == "type"


def test_parse_entry_file_rejects_unknown_type(tmp_path: Path):
    yaml = """\
type: cleanup
cleanup:
  description: x.
"""
    path = _write(tmp_path / "pr-1-x.yml", yaml)
    with pytest.raises(ChangelogValidationError) as exc_info:
        parse_entry_file(path)
    assert exc_info.value.field == "type"
    assert "unknown type" in str(exc_info.value)


def test_parse_entry_file_rejects_type_nested_key_mismatch(tmp_path: Path):
    yaml = """\
type: feature
fix:
  description: x.
"""
    path = _write(tmp_path / "pr-1-x.yml", yaml)
    with pytest.raises(ChangelogValidationError) as exc_info:
        parse_entry_file(path)
    # Either the missing nested `feature:` or the sibling `fix:` collides.
    assert "feature" in str(exc_info.value)


def test_parse_entry_file_rejects_missing_description(tmp_path: Path):
    yaml = """\
type: fix
fix:
  links:
    - https://example.com
"""
    path = _write(tmp_path / "pr-1-x.yml", yaml)
    with pytest.raises(ChangelogValidationError) as exc_info:
        parse_entry_file(path)
    assert "description" in str(exc_info.value)


def test_parse_entry_file_rejects_unknown_top_level_key(tmp_path: Path):
    yaml = """\
type: fix
fix:
  description: x.
typo-field: oops
"""
    path = _write(tmp_path / "pr-1-x.yml", yaml)
    with pytest.raises(ChangelogValidationError) as exc_info:
        parse_entry_file(path)
    assert "typo-field" in str(exc_info.value)


def test_parse_entry_file_rejects_unknown_nested_key(tmp_path: Path):
    yaml = """\
type: fix
fix:
  description: x.
  bogus: y
"""
    path = _write(tmp_path / "pr-1-x.yml", yaml)
    with pytest.raises(ChangelogValidationError) as exc_info:
        parse_entry_file(path)
    assert "bogus" in str(exc_info.value)


def test_parse_entry_file_rejects_empty_packages_list(tmp_path: Path):
    yaml = """\
type: fix
fix:
  description: x.
packages: []
"""
    path = _write(tmp_path / "pr-1-x.yml", yaml)
    with pytest.raises(ChangelogValidationError) as exc_info:
        parse_entry_file(path)
    assert "packages" in str(exc_info.value)
    assert "ambiguous" in str(exc_info.value)


def test_parse_entry_file_rejects_malformed_release_as(tmp_path: Path):
    yaml = """\
type: fix
fix:
  description: x.
release-as: 1.0
"""
    path = _write(tmp_path / "pr-1-x.yml", yaml)
    with pytest.raises(ChangelogValidationError) as exc_info:
        parse_entry_file(path)
    assert exc_info.value.field == "release-as"


def test_parse_entry_file_rejects_empty_file(tmp_path: Path):
    path = _write(tmp_path / "pr-1-x.yml", "")
    with pytest.raises(ChangelogValidationError) as exc_info:
        parse_entry_file(path)
    assert "empty" in str(exc_info.value)


def test_parse_entry_file_rejects_non_mapping_root(tmp_path: Path):
    path = _write(tmp_path / "pr-1-x.yml", "- a list at the root\n")
    with pytest.raises(ChangelogValidationError):
        parse_entry_file(path)


def test_parse_entry_file_rejects_malformed_yaml(tmp_path: Path):
    # Unbalanced flow-mapping brace — guaranteed to trip yaml.safe_load.
    path = _write(tmp_path / "pr-1-x.yml", "type: { feature\n")
    with pytest.raises(ChangelogValidationError) as exc_info:
        parse_entry_file(path)
    assert "malformed YAML" in str(exc_info.value)


# --- validate_packages_against_workspace -------------------------------------


def test_validate_packages_passes_for_workspace_wide_entry():
    entry = _entry(packages=None)
    validate_packages_against_workspace(entry, ["agent-auth", "agent-auth-common"])


def test_validate_packages_passes_when_all_known():
    entry = _entry(packages=("agent-auth",))
    validate_packages_against_workspace(entry, ["agent-auth", "agent-auth-common"])


def test_validate_packages_rejects_unknown_member():
    entry = _entry(packages=("agent-auth", "imaginary-svc"))
    with pytest.raises(ChangelogValidationError) as exc_info:
        validate_packages_against_workspace(entry, ["agent-auth", "agent-auth-common"])
    assert "imaginary-svc" in str(exc_info.value)
    assert exc_info.value.field == "packages"
