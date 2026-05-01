# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Drift guard between the bundled and canonical ``commit_taxonomy``.

The package bundles a copy of ``scripts/lint/commit_taxonomy.py`` so
the released wheel is self-contained — see
``src/pr_lint_validator/commit_taxonomy.py``'s docstring for the
rationale. Until #477 deletes the ``scripts/`` originals, both copies
coexist; this test asserts the three static constants
(``ALLOWED_TYPES``, ``AREA_SCOPES``, ``INTERNAL_ONLY_SCOPES``) and
the ``ReleaseImpact`` enum agree byte-for-byte.

The dynamic ``PACKAGE_SCOPES`` discovery is intentionally divergent
(the canonical module walks up from ``__file__``; the bundled module
walks up from CWD so it works inside a wheel install), so the test
does not compare it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from pr_lint_validator import commit_taxonomy as bundled


def _load_canonical() -> ModuleType:
    """Import ``scripts/lint/commit_taxonomy.py`` via path-spec.

    The canonical module is not on ``sys.path`` (it lives in
    ``scripts/lint/``, an internal-tooling tree). Loading it via
    ``importlib.util.spec_from_file_location`` with a unique name
    avoids polluting ``sys.modules`` for other tests that may import
    a different ``commit_taxonomy``.
    """
    repo_root = Path(__file__).resolve().parents[3]
    canonical_path = repo_root / "scripts" / "lint" / "commit_taxonomy.py"
    assert canonical_path.is_file(), f"canonical commit_taxonomy missing at {canonical_path}"
    spec = importlib.util.spec_from_file_location(
        "_canonical_commit_taxonomy_for_drift_test", canonical_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_allowed_types_dict_in_sync() -> None:
    """``ALLOWED_TYPES`` must match name-for-name and impact-for-impact.

    The bundled and canonical modules each define their own
    ``ReleaseImpact`` enum, so the values are not the same Python
    objects — comparing by ``.name`` keeps the assertion meaningful
    across module boundaries.
    """
    canonical = _load_canonical()
    bundled_pairs = [(name, impact.name) for name, impact in bundled.ALLOWED_TYPES.items()]
    canonical_pairs = [(name, impact.name) for name, impact in canonical.ALLOWED_TYPES.items()]
    assert bundled_pairs == canonical_pairs, (
        "ALLOWED_TYPES drift between packages/pr-lint-validator and "
        "scripts/lint/commit_taxonomy.py — sync the bundled copy."
    )


def test_release_impact_enum_in_sync() -> None:
    """The ``ReleaseImpact`` enum members and integer values match."""
    canonical = _load_canonical()
    bundled_members = [(m.name, m.value) for m in bundled.ReleaseImpact]
    canonical_members = [(m.name, m.value) for m in canonical.ReleaseImpact]
    assert bundled_members == canonical_members


def test_area_scopes_tuple_in_sync() -> None:
    canonical = _load_canonical()
    assert bundled.AREA_SCOPES == canonical.AREA_SCOPES


def test_internal_only_scopes_in_sync() -> None:
    canonical = _load_canonical()
    assert bundled.INTERNAL_ONLY_SCOPES == canonical.INTERNAL_ONLY_SCOPES


def test_release_bumping_types_in_sync() -> None:
    canonical = _load_canonical()
    assert bundled.RELEASE_BUMPING_TYPES == canonical.RELEASE_BUMPING_TYPES
