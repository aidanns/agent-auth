# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for ``scripts/ci/check_license_allowlist.py``.

The Python helper drives the per-package license-allowlist gate
(issue #575 / ADR 0048). The bash driver
(``scripts/check-license-allowlist.sh``) is the public surface; the
helper is the unit covered here, focusing on the SPDX disjunction +
conjunction logic, the exception-file shape rules, and the
acceptance criteria called out in the Agent Brief that the gate
must enforce verbatim.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_helper():
    repo_root = Path(__file__).resolve().parents[1]
    helper_path = repo_root / "scripts" / "ci" / "check_license_allowlist.py"
    spec = importlib.util.spec_from_file_location("check_license_allowlist", helper_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_license_allowlist"] = module
    spec.loader.exec_module(module)
    return module


helper = _load_helper()


def test_pure_allowed_license_passes() -> None:
    """A bare allowlisted SPDX expression must pass."""

    allowed, _ = helper.evaluate_expression("MIT")
    assert allowed


def test_rejected_license_fails() -> None:
    """A bare GPL expression must fail with the rejection-detail signal."""

    allowed, detail = helper.evaluate_expression("GPL-2.0-or-later")
    assert not allowed
    assert "rejected" in detail


def test_unknown_license_fails() -> None:
    """A custom / unrecognised expression fails (brief's explicit policy)."""

    allowed, detail = helper.evaluate_expression("My-Custom-License-1.0")
    assert not allowed
    assert "not on allowlist" in detail


def test_disjunction_picks_first_allowlisted_alternative() -> None:
    """Acceptance criterion: ``A OR B`` resolves to first allowlisted hit.

    Brief locks: SPDX disjunction (``A OR B``) resolves to the first
    allowlisted alternative; the gate only fails when **no**
    alternative is on the allowlist. Tests both the pass case (one
    side allowed) and the fail case (no side allowed).
    """

    allowed, detail = helper.evaluate_expression("MIT OR GPL-2.0")
    assert allowed
    assert "MIT" in detail


def test_disjunction_with_no_allowed_alternative_fails() -> None:
    """``GPL-2.0 OR AGPL-3.0`` fails — neither alternative is allowed."""

    allowed, _ = helper.evaluate_expression("GPL-2.0 OR AGPL-3.0")
    assert not allowed


def test_conjunction_requires_every_component_on_allowlist() -> None:
    """``A AND B`` requires both A and B to be allowed (SPDX semantics)."""

    allowed, _ = helper.evaluate_expression("MIT AND Apache-2.0")
    assert allowed

    allowed, _ = helper.evaluate_expression("MIT AND GPL-3.0-or-later")
    assert not allowed


def test_legacy_classifier_aliases_normalise_to_spdx() -> None:
    """Free-form classifier strings fold onto canonical SPDX ids.

    Many older Python dists put e.g. ``Apache Software License`` in
    the ``License`` field; the gate must canonicalise that onto
    ``Apache-2.0`` so the allowlist match succeeds.
    """

    allowed, _ = helper.evaluate_expression("Apache Software License")
    assert allowed

    allowed, _ = helper.evaluate_expression("MIT License")
    assert allowed

    # PSF-2.0 / PSFL — common pip-licenses spelling for Python-2.0.
    allowed, _ = helper.evaluate_expression("PSF-2.0")
    assert allowed


def test_empty_expression_fails() -> None:
    """No license metadata at all is itself a policy failure."""

    allowed, detail = helper.evaluate_expression("")
    assert not allowed
    assert "no license metadata" in detail


def test_metadata_select_prefers_pep639_expression(tmp_path: Path) -> None:
    """``License-Expression`` (PEP 639) must beat the legacy free-form."""

    metadata = [
        {
            "name": "cryptography",
            "version": "46.0.7",
            "license_expression": "Apache-2.0 OR BSD-3-Clause",
            "license": "<not used>",
            "classifiers": [],
        }
    ]
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata))
    parsed = helper.parse_metadata(metadata_path)
    assert parsed[("cryptography", "46.0.7")] == "Apache-2.0 OR BSD-3-Clause"


def test_metadata_select_falls_back_to_classifiers(tmp_path: Path) -> None:
    """When neither expression nor legacy is set, classifiers map to SPDX.

    Many older dists set neither ``License-Expression`` nor a clean
    ``License`` SPDX id — the gate must still derive an SPDX
    expression from the ``License ::`` classifier list rather than
    silently passing every dist with no metadata.
    """

    metadata = [
        {
            "name": "old-pkg",
            "version": "1.0.0",
            "license_expression": "",
            "license": "",
            "classifiers": [
                "License :: OSI Approved :: Apache Software License",
                "License :: OSI Approved :: MIT License",
            ],
        }
    ]
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata))
    parsed = helper.parse_metadata(metadata_path)
    expression = parsed[("old-pkg", "1.0.0")]
    assert "Apache-2.0" in expression
    assert "MIT" in expression


def test_exception_missing_reason_fails(tmp_path: Path) -> None:
    """Acceptance criterion: missing ``reason`` field fails the gate.

    Brief locks: every exception entry MUST set ``reason`` (and
    ``expires``); entries missing either are themselves a violation
    that the gate surfaces.
    """

    exception_path = tmp_path / "licenses.exceptions.yml"
    exception_path.write_text(
        "entries:\n"
        "  - name: bad-pkg\n"
        "    version: '1.0'\n"
        "    license: GPL-2.0-only\n"
        "    expires: 2099-01-01\n"
    )
    entries, errors = helper.load_exceptions(exception_path)
    assert entries == []
    assert errors
    assert "reason" in errors[0]


def test_exception_missing_expires_fails(tmp_path: Path) -> None:
    """Acceptance criterion: missing ``expires`` field fails the gate."""

    exception_path = tmp_path / "licenses.exceptions.yml"
    exception_path.write_text(
        "entries:\n"
        "  - name: bad-pkg\n"
        "    version: '1.0'\n"
        "    license: GPL-2.0-only\n"
        "    reason: 'because'\n"
    )
    entries, errors = helper.load_exceptions(exception_path)
    assert entries == []
    assert errors
    assert "expires" in errors[0]


def test_expired_exception_is_flagged(tmp_path: Path) -> None:
    """Acceptance criterion: an ``expires`` date in the past fails."""

    exception_path = tmp_path / "licenses.exceptions.yml"
    exception_path.write_text(
        "entries:\n"
        "  - name: stale-pkg\n"
        "    version: '1.0'\n"
        "    license: GPL-2.0-only\n"
        "    reason: 'archive'\n"
        "    expires: 2020-01-01\n"
    )
    entries, _ = helper.load_exceptions(exception_path)
    today = datetime.date(2026, 5, 3)
    expired = helper.find_expired_exceptions(entries, today)
    assert len(expired) == 1
    assert expired[0].name == "stale-pkg"


def test_active_exception_suppresses_violation() -> None:
    """A non-expired exception lets a copyleft dep through.

    Brief locks: the gate fails when a license is outside the
    allowlist, **except** when matched by a non-expired exception
    entry.
    """

    today = datetime.date(2026, 5, 3)
    closure = {("reuse", "6.2.0")}
    metadata = {
        ("reuse", "6.2.0"): "GPL-3.0-or-later",
    }
    active = [
        helper.ExceptionEntry(
            name="reuse",
            version="6.2.0",
            license="GPL-3.0-or-later",
            reason="dev-only static analysis",
            expires=datetime.date(2099, 1, 1),
        )
    ]
    violations = helper.evaluate_closure("agent-auth", closure, metadata, active, today)
    assert violations == []


def test_pep_503_normalisation_matches_uv_export_to_metadata() -> None:
    """``backports.tarfile`` and ``backports-tarfile`` collapse onto one key.

    ``pip-licenses`` reports the ``.``-separated spelling while ``uv export``
    writes the ``-``-separated spelling; without normalisation the two
    sources never join and every dual-spelling dep would surface as a
    false-positive "missing from metadata" violation.
    """

    assert helper.normalise_name("backports.tarfile") == "backports-tarfile"
    assert helper.normalise_name("backports-tarfile") == "backports-tarfile"
    assert helper.normalise_name("Foo_Bar.Baz") == "foo-bar-baz"


def test_closure_membership_filters_by_marker(tmp_path: Path) -> None:
    """Marker-gated closure entries silently pass when not installed.

    The CI matrix runs only on Linux. Deps gated by a Windows or
    macOS env marker (``pywin32-ctypes``, ``colorama``) appear in
    the ``uv export`` output but are never installed in the Linux
    venv. The gate correctly skips them rather than flagging a
    spurious "missing from metadata" violation. Documented as the
    Linux-only-marker-filtering consequence in ADR 0048.
    """

    today = datetime.date(2026, 5, 3)
    closure = {
        ("good-pkg", "1.0.0"),  # in metadata, allowlisted
        ("ghost-pkg", "2.0.0"),  # NOT in metadata (marker-gated)
    }
    metadata = {("good-pkg", "1.0.0"): "MIT"}
    violations = helper.evaluate_closure("agent-auth", closure, metadata, [], today)
    assert violations == []


def test_load_exceptions_missing_file_yields_empty(tmp_path: Path) -> None:
    """No exception file is fine — every dep just goes through the gate."""

    entries, errors = helper.load_exceptions(tmp_path / "does-not-exist.yml")
    assert entries == []
    assert errors == []


def test_emit_metadata_returns_json_array() -> None:
    """``--emit-metadata`` mode dumps the active env as a JSON array.

    Output shape contract: a list of objects, each carrying ``name``,
    ``version``, ``license_expression``, ``license``, and
    ``classifiers``. The bash driver feeds this back as
    ``--metadata`` so the contract is part of the gate's stable
    interface.
    """

    raw = helper.emit_installed_metadata()
    parsed = json.loads(raw)
    assert isinstance(parsed, list)
    assert parsed, "the active env must have at least one installed dist"
    sample = parsed[0]
    for required_key in (
        "name",
        "version",
        "license_expression",
        "license",
        "classifiers",
    ):
        assert required_key in sample, f"metadata entry missing key: {required_key!r}"


def test_disjunction_alternative_can_itself_be_a_conjunction() -> None:
    """``(MIT AND Apache-2.0) OR GPL-2.0`` semantics — flat AND inside OR.

    The flat splitter handles ``MIT AND Apache-2.0 OR GPL-2.0`` by
    treating it as two top-level alternatives:
    ``MIT AND Apache-2.0`` and ``GPL-2.0``. The first alternative
    requires both conjuncts on the allowlist; if it does, the gate
    passes regardless of the second.
    """

    allowed, _ = helper.evaluate_expression("MIT AND Apache-2.0 OR GPL-2.0")
    assert allowed

    allowed, _ = helper.evaluate_expression("MIT AND GPL-3.0-or-later OR Apache-2.0")
    # First alternative fails (GPL component); second alternative
    # (Apache-2.0) passes — gate accepts the disjunction as a whole.
    assert allowed

    allowed, _ = helper.evaluate_expression("MIT AND GPL-3.0-or-later OR LGPL-3.0")
    # Both alternatives include a rejected component; gate fails.
    assert not allowed


@pytest.mark.parametrize(
    "expression",
    [
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "Python-2.0",
        "MPL-2.0",
    ],
)
def test_every_allowlisted_id_passes_bare(expression: str) -> None:
    """Each entry on the brief's allowlist passes a bare-string check."""

    allowed, _ = helper.evaluate_expression(expression)
    assert allowed, f"{expression!r} is on the allowlist but failed the gate"


@pytest.mark.parametrize(
    "expression",
    [
        "GPL-2.0-only",
        "GPL-3.0-or-later",
        "LGPL-2.1-or-later",
        "AGPL-3.0",
        "SSPL-1.0",
        "BUSL-1.1",
    ],
)
def test_every_rejected_glob_fails_bare(expression: str) -> None:
    """Each entry on the brief's reject globs fails a bare-string check."""

    allowed, detail = helper.evaluate_expression(expression)
    assert not allowed, f"{expression!r} should be rejected but passed"
    assert "rejected" in detail
