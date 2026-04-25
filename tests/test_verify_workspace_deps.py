# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for scripts/verify_workspace_deps.py.

The script is the load-bearing piece of ADR 0036's allowlist: if it
fails to notice an unexpected workspace edge, a reverse dep (or a
service-to-service leak) lands on main without an ADR update. These
tests drive the script against fixture pyproject.toml trees — both
the happy path and an injected reverse-dep — so the allowlist stays
honestly enforced.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "verify_workspace_deps.py"


def _write_pyproject(root: Path, name: str, deps: list[str]) -> None:
    """Create a minimal pyproject.toml for ``name`` under ``root/<name>/``."""
    pkg_dir = root / name
    pkg_dir.mkdir(parents=True)
    deps_block = ", ".join(f'"{dep}"' for dep in deps)
    pkg_dir.joinpath("pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "{name}"
            version = "0"
            requires-python = ">=3.11"
            dependencies = [{deps_block}]
            """
        )
    )


def _run(packages_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--packages-dir", str(packages_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_current_workspace_graph_matches_allowlist() -> None:
    # The authoritative invariant: the real packages/ tree must be
    # clean. Running without --packages-dir exercises the default
    # path so the script's own bootstrapping stays covered.
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "matches the ADR 0036 allowlist" in result.stdout


def test_injected_reverse_dep_fails(tmp_path: Path) -> None:
    # Reverse dep: agent-auth-common picks up agent-auth as a
    # runtime dependency. This inverts the intended layering (the
    # common library should not know about the services that
    # consume it) and must fail loudly.
    packages = tmp_path / "packages"
    _write_pyproject(packages, "agent-auth", ["agent-auth-common"])
    _write_pyproject(packages, "agent-auth-common", ["agent-auth"])

    result = _run(packages)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "unexpected workspace-internal edges" in result.stderr
    assert "agent-auth-common -> agent-auth" in result.stderr


def test_service_to_service_leak_fails(tmp_path: Path) -> None:
    # A CLI picking up a service runtime dep (e.g. things-cli
    # reaching into things-bridge) is the other shape of unintended
    # coupling — each CLI should only lean on agent-auth-common's
    # HTTP client layer.
    packages = tmp_path / "packages"
    _write_pyproject(packages, "agent-auth-common", [])
    _write_pyproject(packages, "things-bridge", ["agent-auth-common"])
    _write_pyproject(packages, "things-cli", ["agent-auth-common", "things-bridge"])

    result = _run(packages)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "things-cli -> things-bridge" in result.stderr


def test_missing_allowlisted_edge_fails(tmp_path: Path) -> None:
    # If ALLOWED_EDGES names an edge that no package actually
    # declares (e.g. a package was deleted but the allowlist was
    # not cleaned up), the allowlist has drifted — flag it so the
    # two stay in sync.
    packages = tmp_path / "packages"
    _write_pyproject(packages, "agent-auth-common", [])
    _write_pyproject(packages, "agent-auth", ["agent-auth-common"])
    # Deliberately omit the other six service packages that the
    # allowlist names; the script should report them as missing.

    result = _run(packages)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "allowlisted edges not observed" in result.stderr
    assert "things-bridge -> agent-auth-common" in result.stderr


def test_third_party_deps_are_ignored(tmp_path: Path) -> None:
    # PyPI dependencies like ``cryptography`` or ``pyyaml`` must
    # never show up in the edge graph — the script only considers
    # names that also appear as a workspace member.
    packages = tmp_path / "packages"
    _write_pyproject(packages, "agent-auth-common", [])
    _write_pyproject(
        packages,
        "agent-auth",
        ["agent-auth-common", "cryptography>=42.0", "keyring>=25.0", "pyyaml>=6.0"],
    )
    _write_pyproject(packages, "gpg-backend-cli-host", ["agent-auth-common"])
    _write_pyproject(packages, "gpg-bridge", ["agent-auth-common"])
    _write_pyproject(packages, "gpg-cli", ["agent-auth-common"])
    _write_pyproject(packages, "things-bridge", ["agent-auth-common"])
    _write_pyproject(packages, "things-cli", ["agent-auth-common"])
    _write_pyproject(packages, "things-client-cli-applescript", ["agent-auth-common"])

    result = _run(packages)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "matches the ADR 0036 allowlist" in result.stdout
