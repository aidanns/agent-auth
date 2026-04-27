# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for ``scripts/changelog/predict_release_impact.py``.

Public-API only — every test exercises ``predict`` (the pure
function) or the ``main`` CLI entrypoint. The module is the
PR-comment-time prediction surface for the ``release-impact-comment``
workflow job introduced in #406; a regression here changes what
contributors see when their PR touches ``changelog/@unreleased/``.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from predict_release_impact import main as predict_main
from predict_release_impact import predict
from version_logic import ChangelogValidationError


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed(repo: Path, name: str, body: str) -> Path:
    path = repo / "changelog" / "@unreleased" / name
    _write(path, body)
    return path


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A minimal repo layout the predictor walks."""
    (tmp_path / "changelog" / "@unreleased").mkdir(parents=True)
    return tmp_path


# --- bump matrix --------------------------------------------------------------


def test_predict_feature_implies_minor(repo: Path) -> None:
    """A `feature` entry surfaces as a MINOR bump on a 0.x current version."""
    _seed(
        repo,
        "pr-100-x.yml",
        "type: feature\nfeature:\n  description: New thing.\n",
    )
    envelope = predict(repo, "0.16.1")
    assert envelope["predict"] is True
    assert envelope["bump"] == "MINOR"
    assert envelope["current_version"] == "0.16.1"
    assert envelope["next_version"] == "0.17.0"
    drivers = envelope["drivers"]
    assert isinstance(drivers, list) and len(drivers) == 1
    assert drivers[0]["type"] == "feature"
    assert drivers[0]["bump"] == "MINOR"
    assert drivers[0]["path"].endswith("pr-100-x.yml")


def test_predict_improvement_implies_patch(repo: Path) -> None:
    """An `improvement` entry on its own implies a PATCH bump."""
    _seed(
        repo,
        "pr-101-x.yml",
        "type: improvement\nimprovement:\n  description: Tweak.\n",
    )
    envelope = predict(repo, "0.16.1")
    assert envelope["predict"] is True
    assert envelope["bump"] == "PATCH"
    assert envelope["next_version"] == "0.16.2"


def test_predict_fix_implies_patch(repo: Path) -> None:
    """A `fix` entry on its own implies a PATCH bump."""
    _seed(
        repo,
        "pr-102-x.yml",
        "type: fix\nfix:\n  description: Fix it.\n",
    )
    envelope = predict(repo, "0.16.1")
    assert envelope["predict"] is True
    assert envelope["bump"] == "PATCH"
    assert envelope["next_version"] == "0.16.2"


def test_predict_break_demoted_to_minor_on_zero_x(repo: Path) -> None:
    """`break` demotes to MINOR while the project is in the 0.x range (ADR 0026)."""
    _seed(
        repo,
        "pr-103-x.yml",
        "type: break\nbreak:\n  description: Drops /v0.\n",
    )
    envelope = predict(repo, "0.16.1")
    assert envelope["predict"] is True
    assert envelope["bump"] == "MINOR"
    assert envelope["next_version"] == "0.17.0"


def test_predict_break_promotes_to_major_post_one_x(repo: Path) -> None:
    """`break` produces a MAJOR bump once the project graduates to 1.x."""
    _seed(
        repo,
        "pr-104-x.yml",
        "type: break\nbreak:\n  description: Drops /v0.\n",
    )
    envelope = predict(repo, "1.2.3")
    assert envelope["predict"] is True
    assert envelope["bump"] == "MAJOR"
    assert envelope["next_version"] == "2.0.0"


def test_predict_mixed_picks_largest_bump(repo: Path) -> None:
    """A `feature` + `fix` mix surfaces as MINOR (largest bump wins)."""
    _seed(
        repo,
        "pr-105-fix.yml",
        "type: fix\nfix:\n  description: A bug fix.\n",
    )
    _seed(
        repo,
        "pr-106-feature.yml",
        "type: feature\nfeature:\n  description: A new thing.\n",
    )
    envelope = predict(repo, "0.16.1")
    assert envelope["predict"] is True
    assert envelope["bump"] == "MINOR"
    assert envelope["next_version"] == "0.17.0"
    # Both entries surface as drivers so the rendered comment can name
    # all of them — not just the largest-bump one.
    drivers = envelope["drivers"]
    assert isinstance(drivers, list) and len(drivers) == 2
    types = sorted(driver["type"] for driver in drivers)
    assert types == ["feature", "fix"]


# --- empty / no-impact branches ----------------------------------------------


def test_predict_returns_no_impact_for_empty_unreleased(repo: Path) -> None:
    """An empty `@unreleased/` directory surfaces as ``predict: False``."""
    envelope = predict(repo, "0.16.1")
    assert envelope == {"predict": False, "reason": "no unreleased entries"}


def test_predict_returns_no_impact_when_unreleased_dir_missing(tmp_path: Path) -> None:
    """A repo without a `changelog/@unreleased/` dir at all returns no-impact."""
    envelope = predict(tmp_path, "0.16.1")
    assert envelope == {"predict": False, "reason": "no unreleased entries"}


# --- driver shape -------------------------------------------------------------


def test_predict_driver_includes_single_package_scope(repo: Path) -> None:
    """A single-package entry surfaces ``package`` so the comment can name it."""
    _seed(
        repo,
        "pr-107-x.yml",
        (
            "type: feature\n"
            "feature:\n"
            "  description: Scoped change.\n"
            "packages:\n"
            "  - agent-auth\n"
        ),
    )
    envelope = predict(repo, "0.16.1")
    assert envelope["predict"] is True
    drivers = envelope["drivers"]
    assert isinstance(drivers, list) and len(drivers) == 1
    assert drivers[0]["package"] == "agent-auth"


def test_predict_driver_omits_package_for_workspace_wide_entry(repo: Path) -> None:
    """Workspace-wide entries omit ``package`` rather than rendering ``null``."""
    _seed(
        repo,
        "pr-108-x.yml",
        "type: feature\nfeature:\n  description: Workspace-wide.\n",
    )
    envelope = predict(repo, "0.16.1")
    drivers = envelope["drivers"]
    assert isinstance(drivers, list) and len(drivers) == 1
    assert "package" not in drivers[0]


def test_predict_driver_omits_package_for_multi_package_entry(repo: Path) -> None:
    """Multi-package entries omit ``package`` to keep the comment terse."""
    _seed(
        repo,
        "pr-109-x.yml",
        (
            "type: feature\n"
            "feature:\n"
            "  description: Multi.\n"
            "packages:\n"
            "  - agent-auth\n"
            "  - agent-auth-common\n"
        ),
    )
    envelope = predict(repo, "0.16.1")
    drivers = envelope["drivers"]
    assert isinstance(drivers, list) and len(drivers) == 1
    assert "package" not in drivers[0]


def test_predict_driver_path_is_repo_relative(repo: Path) -> None:
    """The ``path`` field is trimmed to start at ``changelog/`` regardless of cwd."""
    _seed(
        repo,
        "pr-110-x.yml",
        "type: feature\nfeature:\n  description: Trim test.\n",
    )
    envelope = predict(repo, "0.16.1")
    drivers = envelope["drivers"]
    assert isinstance(drivers, list)
    assert drivers[0]["path"] == "changelog/@unreleased/pr-110-x.yml"


# --- malformed YAML surfaces ---------------------------------------------------


def test_predict_propagates_validation_error_on_malformed_yaml(repo: Path) -> None:
    """A YAML that fails the schema raises so the workflow fails closed."""
    _seed(
        repo,
        "pr-111-bad.yml",
        "type: feature\n# missing the required `feature:` nested key\n",
    )
    with pytest.raises(ChangelogValidationError):
        predict(repo, "0.16.1")


# --- CLI entrypoint -----------------------------------------------------------


def test_cli_emits_json_envelope_with_predict_true(repo: Path) -> None:
    """Running the CLI prints a single JSON object on stdout."""
    _seed(
        repo,
        "pr-112-x.yml",
        "type: feature\nfeature:\n  description: New thing.\n",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = predict_main(
            [
                "--repo-root",
                str(repo),
                "--current-version",
                "0.16.1",
            ]
        )
    assert rc == 0
    # A single line of JSON is emitted; assert it parses and matches
    # the public envelope shape.
    payload = json.loads(buf.getvalue())
    assert payload["predict"] is True
    assert payload["bump"] == "MINOR"
    assert payload["current_version"] == "0.16.1"
    assert payload["next_version"] == "0.17.0"


def test_cli_emits_json_envelope_with_predict_false(repo: Path) -> None:
    """An empty unreleased dir round-trips as a ``predict: false`` envelope."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = predict_main(
            [
                "--repo-root",
                str(repo),
                "--current-version",
                "0.16.1",
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload == {"predict": False, "reason": "no unreleased entries"}
