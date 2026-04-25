# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for scripts/setup-devcontainer-signing.sh.

The script wires devcontainer commit signing to the host's
gpg-bridge. It writes the gpg-cli config file at the canonical
``$XDG_CONFIG_HOME/gpg-cli/config.yaml`` path (the same path
``packages/gpg-cli/src/gpg_cli/config.py`` reads) and runs two
``git config --local`` calls. These tests exercise that contract
through the script's argv interface only — they do not import the
shell.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "setup-devcontainer-signing.sh"


def _required_args(
    *,
    access_token: str = "aa_test_access",
    refresh_token: str = "rt_test_refresh",
    auth_url: str = "https://host.docker.internal:9100",
    bridge_url: str = "https://host.docker.internal:8443",
) -> list[str]:
    """Build the four-flag minimum argv every successful run needs."""
    return [
        "--access-token",
        access_token,
        "--refresh-token",
        refresh_token,
        "--auth-url",
        auth_url,
        "--bridge-url",
        bridge_url,
    ]


def _run(
    args: list[str],
    *,
    cwd: Path,
    xdg_config_home: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the setup script with a controlled environment.

    ``cwd`` must be a git working tree so ``git config --local`` has
    somewhere to write. ``xdg_config_home`` redirects the gpg-cli
    config file off the developer's real ``~/.config``.
    """
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(xdg_config_home)
    # HOME redirection guards the fallback path in the script's
    # ``${XDG_CONFIG_HOME:-${HOME}/.config}`` expression.
    env["HOME"] = str(xdg_config_home.parent)
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialise an empty git repo at ``tmp_path/repo`` and return it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True, capture_output=True)
    return repo


class TestSetupDevcontainerSigning:
    """Argv -> config-file + git-config contract for the setup script."""

    def test_writes_canonical_config_and_sets_git_config(
        self, tmp_path: Path, git_repo: Path
    ) -> None:
        xdg = tmp_path / "xdg-config"
        result = _run(
            [
                *_required_args(),
                "--family-id",
                "fam-1",
                "--ca-cert-path",
                "/tmp/ca.pem",
                "--timeout-seconds",
                "20",
            ],
            cwd=git_repo,
            xdg_config_home=xdg,
        )
        assert result.returncode == 0, result.stderr

        config_path = xdg / "gpg-cli" / "config.yaml"
        assert config_path.exists()
        loaded = yaml.safe_load(config_path.read_text())
        assert loaded == {
            "bridge_url": "https://host.docker.internal:8443",
            "auth_url": "https://host.docker.internal:9100",
            "access_token": "aa_test_access",
            "refresh_token": "rt_test_refresh",
            "family_id": "fam-1",
            "ca_cert_path": "/tmp/ca.pem",
            "timeout_seconds": 20,
        }

        # The credential pair is bearer material — the file must be
        # 0600 so other local accounts can't read it. gpg-cli also
        # rewrites the file on every refresh (also at 0600), so this
        # invariant holds across the credential's whole lifetime.
        mode = stat.S_IMODE(config_path.stat().st_mode)
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"

        gpg_program = subprocess.run(
            ["git", "config", "--local", "gpg.program"],
            cwd=git_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert gpg_program == "gpg-cli"

        commit_gpgsign = subprocess.run(
            ["git", "config", "--local", "commit.gpgsign"],
            cwd=git_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert commit_gpgsign == "true"

    def test_optional_flags_omitted_writes_only_required_keys(
        self, tmp_path: Path, git_repo: Path
    ) -> None:
        xdg = tmp_path / "xdg-config"
        result = _run(_required_args(), cwd=git_repo, xdg_config_home=xdg)
        assert result.returncode == 0, result.stderr

        loaded = yaml.safe_load((xdg / "gpg-cli" / "config.yaml").read_text())
        # ``family_id``, ``ca_cert_path`` and ``timeout_seconds`` are
        # absent so ``gpg_cli.config.load_config`` falls back to its
        # built-in defaults (no CA, 30s timeout, no reissue path until
        # the operator re-runs the script with --family-id).
        assert loaded == {
            "bridge_url": "https://host.docker.internal:8443",
            "auth_url": "https://host.docker.internal:9100",
            "access_token": "aa_test_access",
            "refresh_token": "rt_test_refresh",
        }

    def test_idempotent_rerun_preserves_state(self, tmp_path: Path, git_repo: Path) -> None:
        xdg = tmp_path / "xdg-config"
        args = _required_args()
        first = _run(args, cwd=git_repo, xdg_config_home=xdg)
        assert first.returncode == 0, first.stderr

        config_path = xdg / "gpg-cli" / "config.yaml"
        first_contents = config_path.read_text()

        second = _run(args, cwd=git_repo, xdg_config_home=xdg)
        assert second.returncode == 0, second.stderr
        assert config_path.read_text() == first_contents

        # git config --local should still hold the same values
        # (no duplicate entries from re-runs).
        program_lines = (
            subprocess.run(
                ["git", "config", "--local", "--get-all", "gpg.program"],
                cwd=git_repo,
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .splitlines()
        )
        assert program_lines == ["gpg-cli"]

    def test_rejects_missing_access_token(self, tmp_path: Path, git_repo: Path) -> None:
        xdg = tmp_path / "xdg-config"
        args = _required_args()
        # Drop the --access-token pair from the argv.
        idx = args.index("--access-token")
        del args[idx : idx + 2]
        result = _run(args, cwd=git_repo, xdg_config_home=xdg)
        assert result.returncode != 0
        assert "--access-token is required" in result.stderr

    def test_rejects_missing_refresh_token(self, tmp_path: Path, git_repo: Path) -> None:
        xdg = tmp_path / "xdg-config"
        args = _required_args()
        idx = args.index("--refresh-token")
        del args[idx : idx + 2]
        result = _run(args, cwd=git_repo, xdg_config_home=xdg)
        assert result.returncode != 0
        assert "--refresh-token is required" in result.stderr

    def test_rejects_missing_auth_url(self, tmp_path: Path, git_repo: Path) -> None:
        xdg = tmp_path / "xdg-config"
        args = _required_args()
        idx = args.index("--auth-url")
        del args[idx : idx + 2]
        result = _run(args, cwd=git_repo, xdg_config_home=xdg)
        assert result.returncode != 0
        assert "--auth-url is required" in result.stderr

    def test_rejects_missing_bridge_url(self, tmp_path: Path, git_repo: Path) -> None:
        xdg = tmp_path / "xdg-config"
        args = _required_args()
        idx = args.index("--bridge-url")
        del args[idx : idx + 2]
        result = _run(args, cwd=git_repo, xdg_config_home=xdg)
        assert result.returncode != 0
        assert "--bridge-url is required" in result.stderr

    def test_rejects_unknown_flag(self, tmp_path: Path, git_repo: Path) -> None:
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--bogus", "x"],
            cwd=git_repo,
            xdg_config_home=xdg,
        )
        assert result.returncode != 0
        assert "unknown argument" in result.stderr

    def test_rejects_non_numeric_timeout(self, tmp_path: Path, git_repo: Path) -> None:
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--timeout-seconds", "fast"],
            cwd=git_repo,
            xdg_config_home=xdg,
        )
        assert result.returncode != 0
        assert "must be a number" in result.stderr

    def test_rejects_outside_git_worktree(self, tmp_path: Path) -> None:
        not_a_repo = tmp_path / "not-a-repo"
        not_a_repo.mkdir()
        xdg = tmp_path / "xdg-config"
        result = _run(
            _required_args(),
            cwd=not_a_repo,
            xdg_config_home=xdg,
        )
        assert result.returncode != 0
        assert "git working tree" in result.stderr

    def test_config_round_trips_through_gpg_cli_loader(
        self, tmp_path: Path, git_repo: Path
    ) -> None:
        """The script writes a file the gpg-cli loader can read.

        Belt-and-braces against drift between the script's emitted
        keys and ``gpg_cli.config.load_config``'s expected schema.
        ``packages/gpg-cli/src`` is already on the workspace pytest
        pythonpath (see ``pyproject.toml`` ``[tool.pytest.ini_options]
        pythonpath``), so the import resolves without manipulation.
        """
        from gpg_cli.config import load_config

        xdg = tmp_path / "xdg-config"
        result = _run(
            [
                *_required_args(),
                "--family-id",
                "fam-roundtrip",
                "--ca-cert-path",
                "/tmp/ca.pem",
                "--timeout-seconds",
                "12.5",
            ],
            cwd=git_repo,
            xdg_config_home=xdg,
        )
        assert result.returncode == 0, result.stderr

        cfg = load_config(config_path=str(xdg / "gpg-cli" / "config.yaml")).validated()
        assert cfg.bridge_url == "https://host.docker.internal:8443"
        assert cfg.credentials.access_token == "aa_test_access"
        assert cfg.credentials.refresh_token == "rt_test_refresh"
        assert cfg.credentials.auth_url == "https://host.docker.internal:9100"
        assert cfg.credentials.family_id == "fam-roundtrip"
        assert cfg.ca_cert_path == "/tmp/ca.pem"
        assert cfg.timeout_seconds == 12.5
