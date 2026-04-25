# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for scripts/setup-devcontainer-signing.sh.

The script wires devcontainer commit signing to the host's
gpg-bridge. It writes the gpg-cli config file at the canonical
``$XDG_CONFIG_HOME/gpg-cli/config.yaml`` path (the same path
``packages/gpg-cli/src/gpg_cli/config.py`` reads) and runs two
``git config --local`` calls. After issue #333 it also runs an
end-to-end smoke test (probes 1..4) before exiting 0. These tests
exercise that contract through the script's argv interface only —
they do not import the shell.

The smoke-test probes are exercised by stubbing ``gpg-cli`` and
``curl`` on a synthetic ``PATH`` that points at the test's temp
directory. Each fake binary is a tiny bash script whose behaviour
(exit code, stdout, stderr, status-fd output) is parametrised by
files in the same temp dir, so a single test can flip the fakes'
behaviour without rewriting the binary.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
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
    extra_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the setup script with a controlled environment.

    ``cwd`` must be a git working tree so ``git config --local`` has
    somewhere to write. ``xdg_config_home`` redirects the gpg-cli
    config file off the developer's real ``~/.config``. ``extra_path``
    is prepended to ``PATH`` so the test's fake ``gpg-cli`` / ``curl``
    binaries shadow any real ones; passing ``None`` keeps the host
    ``PATH`` (used by the smoke-test-skipping happy paths and the
    arg-parsing tests that exit before any probe runs).
    """
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(xdg_config_home)
    # HOME redirection guards the fallback path in the script's
    # ``${XDG_CONFIG_HOME:-${HOME}/.config}`` expression.
    env["HOME"] = str(xdg_config_home.parent)
    if extra_path is not None:
        env["PATH"] = f"{extra_path}{os.pathsep}{env.get('PATH', '')}"
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


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _make_fake_bin_dir(
    tmp_path: Path,
    *,
    gpg_cli_exit: int = 0,
    gpg_cli_status_text: str = "[GNUPG:] SIG_CREATED B foo bar baz\n",
    gpg_cli_stdout: str = "-----BEGIN PGP SIGNATURE-----\nfake\n-----END PGP SIGNATURE-----\n",
    gpg_cli_stderr_extra: str = "",
    curl_exit: int = 0,
    curl_http_status: str = "200",
    omit_gpg_cli: bool = False,
) -> Path:
    """Build a directory with fake ``gpg-cli`` and ``curl`` binaries.

    The fakes record their argv in ``$bindir/calls/<name>`` for tests
    that need to assert on what the script invoked. ``gpg-cli`` writes
    its parametrised stdout to its stdout, the parametrised status
    text to fd 2 (the script always passes ``--status-fd 2``), then
    exits with ``gpg_cli_exit``. ``curl`` echoes the parametrised HTTP
    status to stdout (the script invokes curl with
    ``--write-out '%{http_code}'``) and exits with ``curl_exit``.
    """
    bindir = tmp_path / "fake-bin"
    bindir.mkdir()
    calls_dir = bindir / "calls"
    calls_dir.mkdir()

    # Re-use the host's git binary so the script's ``git config --local``
    # calls hit a real git executable. We can't ship a fake git here
    # because the script does meaningful work with it.
    real_git = shutil.which("git")
    assert real_git, "git must be on PATH to run the test suite"
    (bindir / "git").symlink_to(real_git)

    # Symlink mktemp/grep/cat/printf etc. through to the host so the
    # script's helpers keep working under a stripped PATH (the
    # probe-1-fail test sets PATH to bindir alone, so bash itself
    # has to be findable here too).
    for tool in (
        "bash",
        "cat",
        "chmod",
        "env",
        "grep",
        "mkdir",
        "mktemp",
        "mv",
        "printf",
        "rm",
        "umask",
    ):
        host = shutil.which(tool)
        if host is not None:
            (bindir / tool).symlink_to(host)

    if not omit_gpg_cli:
        _write_executable(
            bindir / "gpg-cli",
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                # Fake gpg-cli for setup-devcontainer-signing tests.
                printf '%s' "$*" >'{calls_dir}/gpg-cli'
                # Drain stdin so the upstream pipe doesn't break with EPIPE.
                cat >/dev/null
                printf '%s' {gpg_cli_stdout!r}
                # Status text always goes to stderr; the production script
                # passes --status-fd 2.
                printf '%s' {gpg_cli_status_text!r} >&2
                if [[ -n {gpg_cli_stderr_extra!r} ]]; then
                  printf '%s' {gpg_cli_stderr_extra!r} >&2
                fi
                exit {gpg_cli_exit}
                """
            ),
        )

    _write_executable(
        bindir / "curl",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            # Fake curl for setup-devcontainer-signing tests.
            printf '%s\\n' "$*" >'{calls_dir}/curl'
            # The script asks for --write-out '%{{http_code}}'; emit the
            # parametrised status to stdout. curl's --silent --output
            # /dev/null makes everything else go to /dev/null in prod,
            # so stdout-only is the right surface to mimic.
            printf '%s' {curl_http_status!r}
            exit {curl_exit}
            """
        ),
    )

    return bindir


class TestSetupDevcontainerSigningArgvAndConfig:
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
                "--skip-smoke",
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
        result = _run(
            [*_required_args(), "--skip-smoke"],
            cwd=git_repo,
            xdg_config_home=xdg,
        )
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

    def test_signing_key_flag_writes_local_user_signingkey(
        self, tmp_path: Path, git_repo: Path
    ) -> None:
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890", "--skip-smoke"],
            cwd=git_repo,
            xdg_config_home=xdg,
        )
        assert result.returncode == 0, result.stderr

        configured = subprocess.run(
            ["git", "config", "--local", "user.signingkey"],
            cwd=git_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert configured == "ABCDEF1234567890"

    def test_idempotent_rerun_preserves_state(self, tmp_path: Path, git_repo: Path) -> None:
        xdg = tmp_path / "xdg-config"
        args = [*_required_args(), "--skip-smoke"]
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
                "--skip-smoke",
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


class TestSetupDevcontainerSigningSmokeTest:
    """Probes 1..4 from issue #333 and the ``--skip-smoke`` bypass."""

    def test_skip_smoke_emits_warning_and_exits_zero(self, tmp_path: Path, git_repo: Path) -> None:
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--skip-smoke"],
            cwd=git_repo,
            xdg_config_home=xdg,
        )
        assert result.returncode == 0, result.stderr
        assert "--skip-smoke set; install is unverified" in result.stderr

    def test_happy_path_succeeds_and_reports_resolved_fingerprint(
        self, tmp_path: Path, git_repo: Path
    ) -> None:
        bindir = _make_fake_bin_dir(tmp_path)
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890"],
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode == 0, result.stderr
        assert "trial sign succeeded with key ABCDEF1234567890" in result.stdout

        # Confirm gpg-cli was invoked with the local-user fingerprint
        # the script just wrote.
        gpg_cli_call = (bindir / "calls" / "gpg-cli").read_text()
        assert "-bsau ABCDEF1234567890" in gpg_cli_call
        assert "--status-fd 2" in gpg_cli_call

        # Confirm curl was pointed at /gpg-bridge/health under the
        # configured bridge URL, with the bearer header set, and that
        # the token never appeared on argv (visible via `ps`).
        curl_call = (bindir / "calls" / "curl").read_text()
        assert "https://host.docker.internal:8443/gpg-bridge/health" in curl_call
        assert (
            "aa_test_access" not in curl_call
        ), "bearer token must travel via header, never argv (ps would expose it)"

    def test_probe1_fails_when_gpg_cli_missing(self, tmp_path: Path, git_repo: Path) -> None:
        bindir = _make_fake_bin_dir(tmp_path, omit_gpg_cli=True)
        xdg = tmp_path / "xdg-config"
        # Strip /usr/local/bin etc. so a system-installed gpg-cli (if
        # any) doesn't shadow the missing fake. PATH is just our bindir.
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(xdg)
        env["HOME"] = str(xdg.parent)
        env["PATH"] = str(bindir)
        result = subprocess.run(
            [
                str(SCRIPT),
                *_required_args(),
                "--signing-key",
                "ABCDEF1234567890",
            ],
            cwd=str(git_repo),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "probe failed: gpg.program unresolved" in result.stderr
        assert "gpg-cli" in result.stderr

    def test_probe2_fails_when_signing_key_missing(self, tmp_path: Path, git_repo: Path) -> None:
        bindir = _make_fake_bin_dir(tmp_path)
        xdg = tmp_path / "xdg-config"
        # No --signing-key, no preexisting git config user.signingkey →
        # the script must fail probe 2 with a clear diagnostic.
        result = _run(
            _required_args(),
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode != 0
        assert "user.signingkey is unset" in result.stderr
        assert "--signing-key" in result.stderr

    def test_probe2_passes_when_git_already_has_signingkey(
        self, tmp_path: Path, git_repo: Path
    ) -> None:
        # Pre-seed git config so the script can use the existing value.
        subprocess.run(
            ["git", "config", "--local", "user.signingkey", "DEADBEEFCAFE0000"],
            cwd=git_repo,
            check=True,
        )
        bindir = _make_fake_bin_dir(tmp_path)
        xdg = tmp_path / "xdg-config"
        result = _run(
            _required_args(),
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode == 0, result.stderr
        assert "trial sign succeeded with key DEADBEEFCAFE0000" in result.stdout

    def test_probe3_fails_when_curl_returns_nonzero(self, tmp_path: Path, git_repo: Path) -> None:
        # curl exit 7 = connection refused; exit 28 = timeout. Either
        # surfaces as "bridge unreachable".
        bindir = _make_fake_bin_dir(tmp_path, curl_exit=7, curl_http_status="")
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890"],
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode != 0
        assert "bridge unreachable" in result.stderr
        assert "host.docker.internal" in result.stderr

    def test_probe3_fails_on_http_000(self, tmp_path: Path, git_repo: Path) -> None:
        # curl exits 0 but writes 000 (no response received) — e.g.
        # TLS handshake error. Treated as unreachable, not 4xx.
        bindir = _make_fake_bin_dir(tmp_path, curl_exit=0, curl_http_status="000")
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890"],
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode != 0
        assert "bridge unreachable" in result.stderr

    def test_probe3_passes_on_403(self, tmp_path: Path, git_repo: Path) -> None:
        # The token is gpg:sign-scoped, not gpg-bridge:health-scoped,
        # so a 403 here is *expected* — it still proves the network
        # path is open. Probe 4 (trial sign) is the auth check.
        bindir = _make_fake_bin_dir(tmp_path, curl_exit=0, curl_http_status="403")
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890"],
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode == 0, result.stderr

    def test_probe4_fails_on_unauthorized(self, tmp_path: Path, git_repo: Path) -> None:
        # gpg-cli exit 3 = BridgeUnauthorizedError (token rejected).
        bindir = _make_fake_bin_dir(
            tmp_path,
            gpg_cli_exit=3,
            gpg_cli_status_text="",
            gpg_cli_stderr_extra="gpg-cli: unauthorized: token rejected\n",
        )
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890"],
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode != 0
        assert "bridge rejected the token (unauthorized)" in result.stderr
        assert "gpg:sign=allow" in result.stderr

    def test_probe4_fails_on_forbidden(self, tmp_path: Path, git_repo: Path) -> None:
        # gpg-cli exit 4 = BridgeForbiddenError (scope or key denied).
        bindir = _make_fake_bin_dir(
            tmp_path,
            gpg_cli_exit=4,
            gpg_cli_status_text="",
            gpg_cli_stderr_extra="gpg-cli: forbidden: key not allowlisted\n",
        )
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890"],
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode != 0
        assert "forbidden" in result.stderr
        assert "allowed_signing_keys" in result.stderr

    def test_probe4_fails_on_bridge_unavailable(self, tmp_path: Path, git_repo: Path) -> None:
        # gpg-cli exit 5 = BridgeUnavailableError (bridge or backend).
        bindir = _make_fake_bin_dir(
            tmp_path,
            gpg_cli_exit=5,
            gpg_cli_status_text="",
            gpg_cli_stderr_extra="gpg-cli: bridge unavailable: timed out\n",
        )
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890"],
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode != 0
        assert "bridge unavailable" in result.stderr
        assert "gpg-agent" in result.stderr

    def test_probe4_fails_on_unknown_exit_code(self, tmp_path: Path, git_repo: Path) -> None:
        # Any exit code outside the documented set surfaces gpg-cli's
        # stderr verbatim and points at the operator runbook.
        bindir = _make_fake_bin_dir(
            tmp_path,
            gpg_cli_exit=42,
            gpg_cli_status_text="",
            gpg_cli_stderr_extra="gpg-cli: unexpected error: nuclear meltdown\n",
        )
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890"],
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode != 0
        assert "gpg-cli exited 42" in result.stderr
        assert "nuclear meltdown" in result.stderr
        assert "docs/operations/gpg-bridge-host-setup.md" in result.stderr

    def test_probe4_fails_on_zero_exit_without_sig_created(
        self, tmp_path: Path, git_repo: Path
    ) -> None:
        # gpg-cli exited 0 but emitted no SIG_CREATED status line —
        # treat as a contract violation, not a success, so we don't
        # ship a broken setup.
        bindir = _make_fake_bin_dir(
            tmp_path,
            gpg_cli_exit=0,
            gpg_cli_status_text="[GNUPG:] BEGIN_SIGNING\n",
        )
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890"],
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode != 0
        assert "no SIG_CREATED status line" in result.stderr

    def test_smoke_test_idempotent_on_rerun(self, tmp_path: Path, git_repo: Path) -> None:
        bindir = _make_fake_bin_dir(tmp_path)
        xdg = tmp_path / "xdg-config"
        args = [*_required_args(), "--signing-key", "ABCDEF1234567890"]

        first = _run(args, cwd=git_repo, xdg_config_home=xdg, extra_path=bindir)
        assert first.returncode == 0, first.stderr
        second = _run(args, cwd=git_repo, xdg_config_home=xdg, extra_path=bindir)
        assert second.returncode == 0, second.stderr
        assert "trial sign succeeded" in second.stdout

    def test_token_does_not_leak_via_argv(self, tmp_path: Path, git_repo: Path) -> None:
        """Bearer token must not appear on any subprocess argv.

        A token on ``ps``-visible argv leaks to every other local
        account on the system. The script must pass it via stdin, env
        var, or HTTP header — never as a positional/argument string
        to a sibling binary.
        """
        bindir = _make_fake_bin_dir(tmp_path)
        xdg = tmp_path / "xdg-config"
        result = _run(
            [*_required_args(), "--signing-key", "ABCDEF1234567890"],
            cwd=git_repo,
            xdg_config_home=xdg,
            extra_path=bindir,
        )
        assert result.returncode == 0, result.stderr
        curl_call = (bindir / "calls" / "curl").read_text()
        gpg_call = (bindir / "calls" / "gpg-cli").read_text()
        assert "aa_test_access" not in curl_call
        assert "aa_test_access" not in gpg_call
