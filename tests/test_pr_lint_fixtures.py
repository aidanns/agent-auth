# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Every pr-lint fixture gives its expected outcome in both validators.

A PR body that a validator wrongly accepts can put a malformed squash
commit on main; one it wrongly rejects blocks a good PR. Each
``valid-*.md`` fixture must pass and each ``invalid-*.md`` fixture
must fail, in both the ``pr_lint_validator`` package and the legacy
``scripts/validate-commit-msg-block.py``, so the two copies of each
rule cannot drift apart unnoticed.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from pr_lint_validator import commit_msg

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / ".github" / "workflows" / "tests" / "pr-lint-fixtures"
LEGACY_SCRIPT = REPO_ROOT / "scripts" / "validate-commit-msg-block.py"


def _load_legacy_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_commit_msg_block", LEGACY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LEGACY = _load_legacy_validator()
_VALIDATORS: list[tuple[Callable[[str], None], type[Exception]]] = [
    (commit_msg.validate, commit_msg.ValidationError),
    (_LEGACY.validate, _LEGACY.ValidationError),
]
_FIXTURES = sorted(FIXTURES_DIR.glob("*-*.md"))


def test_fixture_directory_is_populated() -> None:
    assert any(f.name.startswith("valid-") for f in _FIXTURES)
    assert any(f.name.startswith("invalid-") for f in _FIXTURES)


@pytest.mark.parametrize("validator", _VALIDATORS, ids=["package", "legacy"])
@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda f: f.stem)
def test_fixture_outcome(
    fixture: Path, validator: tuple[Callable[[str], None], type[Exception]]
) -> None:
    validate, error_cls = validator
    body = fixture.read_text(encoding="utf-8")
    if fixture.name.startswith("valid-"):
        validate(body)
    else:
        assert fixture.name.startswith("invalid-"), f"unexpected fixture name {fixture.name}"
        with pytest.raises(error_cls):
            validate(body)
