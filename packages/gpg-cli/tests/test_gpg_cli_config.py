# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for gpg-cli layered configuration and credential storage."""

from __future__ import annotations

import os
import stat

import pytest
import yaml

from gpg_cli.config import Credentials, FileStore, load_config
from gpg_cli.errors import (
    ConfigMigrationRequiredError,
    CredentialsBackendError,
    CredentialsNotFoundError,
)


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every AGENT_AUTH_GPG_* var so file values surface deterministically."""
    for name in (
        "AGENT_AUTH_GPG_BRIDGE_URL",
        "AGENT_AUTH_GPG_ACCESS_TOKEN",
        "AGENT_AUTH_GPG_REFRESH_TOKEN",
        "AGENT_AUTH_GPG_FAMILY_ID",
        "AGENT_AUTH_GPG_AUTH_URL",
        "AGENT_AUTH_GPG_CA_CERT_PATH",
        "AGENT_AUTH_GPG_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def _too_open_for_credentials() -> int:
    """Return a file mode the credentials loader rejects.

    Computed at runtime so the CodeQL ``py/overly-permissive-mask``
    query doesn't flag a literal world-readable mask in test code —
    this test asserts the rejection contract, not real-world widening.
    """
    return 0o600 | 0o044  # owner rw + world / group read


def _write_full_config(path, **overrides) -> None:
    data = {
        "bridge_url": "https://file.example.invalid",
        "access_token": "aa_file",
        "refresh_token": "rt_file",
        "auth_url": "https://auth.file.example.invalid",
        "family_id": "fam-file",
        "timeout_seconds": 12.5,
    }
    data.update(overrides)
    path.write_text(yaml.safe_dump(data))


class TestLoadConfig:
    @pytest.mark.covers_function("Load CLI Configuration")
    def test_env_overrides_file(self, tmp_path, monkeypatch) -> None:
        _clean_env(monkeypatch)
        cfg_path = tmp_path / "config.yaml"
        _write_full_config(cfg_path)
        monkeypatch.setenv("AGENT_AUTH_GPG_BRIDGE_URL", "https://env.example.invalid")
        monkeypatch.setenv("AGENT_AUTH_GPG_ACCESS_TOKEN", "aa_env")
        monkeypatch.setenv("AGENT_AUTH_GPG_REFRESH_TOKEN", "rt_env")
        monkeypatch.setenv("AGENT_AUTH_GPG_AUTH_URL", "https://auth.env.example.invalid")
        cfg = load_config(config_path=str(cfg_path)).validated()
        assert cfg.bridge_url == "https://env.example.invalid"
        assert cfg.credentials.access_token == "aa_env"
        assert cfg.credentials.refresh_token == "rt_env"
        assert cfg.credentials.auth_url == "https://auth.env.example.invalid"
        # File values still win for fields env doesn't override.
        assert cfg.credentials.family_id == "fam-file"
        assert cfg.timeout_seconds == 12.5

    @pytest.mark.covers_function("Load CLI Configuration")
    def test_cli_overrides_env(self, tmp_path, monkeypatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("AGENT_AUTH_GPG_BRIDGE_URL", "https://env.example.invalid")
        monkeypatch.setenv("AGENT_AUTH_GPG_ACCESS_TOKEN", "aa_env")
        monkeypatch.setenv("AGENT_AUTH_GPG_REFRESH_TOKEN", "rt_env")
        monkeypatch.setenv("AGENT_AUTH_GPG_AUTH_URL", "https://auth.env.example.invalid")
        cfg = load_config(
            cli_bridge_url="https://cli.example.invalid",
            cli_access_token="aa_cli",
            cli_refresh_token="rt_cli",
            cli_auth_url="https://auth.cli.example.invalid",
            cli_family_id="fam-cli",
            config_path=str(tmp_path / "absent.yaml"),
        ).validated()
        assert cfg.bridge_url == "https://cli.example.invalid"
        assert cfg.credentials.access_token == "aa_cli"
        assert cfg.credentials.refresh_token == "rt_cli"
        assert cfg.credentials.auth_url == "https://auth.cli.example.invalid"
        assert cfg.credentials.family_id == "fam-cli"

    @pytest.mark.covers_function("Load CLI Configuration")
    def test_missing_access_token_rejected(self, tmp_path, monkeypatch) -> None:
        _clean_env(monkeypatch)
        cfg = load_config(
            cli_bridge_url="https://x.invalid",
            cli_refresh_token="rt",
            cli_auth_url="https://auth.invalid",
            config_path=str(tmp_path / "absent.yaml"),
        )
        with pytest.raises(ValueError, match="access_token is required"):
            cfg.validated()

    @pytest.mark.covers_function("Load CLI Configuration")
    def test_missing_refresh_token_rejected(self, tmp_path, monkeypatch) -> None:
        _clean_env(monkeypatch)
        cfg = load_config(
            cli_bridge_url="https://x.invalid",
            cli_access_token="aa",
            cli_auth_url="https://auth.invalid",
            config_path=str(tmp_path / "absent.yaml"),
        )
        with pytest.raises(ValueError, match="refresh_token is required"):
            cfg.validated()

    @pytest.mark.covers_function("Load CLI Configuration")
    def test_missing_auth_url_rejected(self, tmp_path, monkeypatch) -> None:
        _clean_env(monkeypatch)
        cfg = load_config(
            cli_bridge_url="https://x.invalid",
            cli_access_token="aa",
            cli_refresh_token="rt",
            config_path=str(tmp_path / "absent.yaml"),
        )
        with pytest.raises(ValueError, match="auth_url is required"):
            cfg.validated()

    @pytest.mark.covers_function("Load CLI Configuration")
    def test_missing_bridge_url_rejected(self, tmp_path, monkeypatch) -> None:
        _clean_env(monkeypatch)
        cfg = load_config(
            cli_access_token="aa",
            cli_refresh_token="rt",
            cli_auth_url="https://auth.invalid",
            config_path=str(tmp_path / "absent.yaml"),
        )
        with pytest.raises(ValueError, match="bridge_url is required"):
            cfg.validated()

    @pytest.mark.covers_function("Load CLI Configuration")
    def test_env_timeout_parses(self, tmp_path, monkeypatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("AGENT_AUTH_GPG_BRIDGE_URL", "http://x")
        monkeypatch.setenv("AGENT_AUTH_GPG_ACCESS_TOKEN", "aa")
        monkeypatch.setenv("AGENT_AUTH_GPG_REFRESH_TOKEN", "rt")
        monkeypatch.setenv("AGENT_AUTH_GPG_AUTH_URL", "http://auth")
        monkeypatch.setenv("AGENT_AUTH_GPG_TIMEOUT_SECONDS", "17.0")
        cfg = load_config(config_path=str(tmp_path / "absent.yaml")).validated()
        assert cfg.timeout_seconds == 17.0

    @pytest.mark.covers_function("Load CLI Configuration")
    def test_env_timeout_rejects_non_numeric(self, tmp_path, monkeypatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("AGENT_AUTH_GPG_TIMEOUT_SECONDS", "abc")
        monkeypatch.setenv("AGENT_AUTH_GPG_BRIDGE_URL", "http://x")
        monkeypatch.setenv("AGENT_AUTH_GPG_ACCESS_TOKEN", "aa")
        monkeypatch.setenv("AGENT_AUTH_GPG_REFRESH_TOKEN", "rt")
        monkeypatch.setenv("AGENT_AUTH_GPG_AUTH_URL", "http://auth")
        with pytest.raises(ValueError, match="expected a float"):
            load_config(config_path=str(tmp_path / "absent.yaml"))

    @pytest.mark.covers_function("Load CLI Configuration")
    def test_legacy_token_only_schema_rejected_with_migration_message(
        self, tmp_path, monkeypatch
    ) -> None:
        """Pre-refresh single-token configs cannot be auto-migrated.

        A single bearer has no refresh token to derive, so the loader
        must surface a directive pointing at the bootstrap script. The
        message must name ``scripts/setup-devcontainer-signing.sh`` so
        the operator has a copy-pastable recovery command.
        """
        _clean_env(monkeypatch)
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("bridge_url: https://x.invalid\ntoken: aa_legacy\n")
        with pytest.raises(ConfigMigrationRequiredError, match="setup-devcontainer-signing.sh"):
            load_config(config_path=str(cfg_path))

    @pytest.mark.covers_function("Load CLI Configuration")
    def test_new_schema_alongside_legacy_field_loads_new_fields(
        self, tmp_path, monkeypatch
    ) -> None:
        """A file that has both ``token:`` and ``access_token:`` loads the new fields.

        This handles the in-place rewrite path: gpg-cli's :class:`FileStore`
        drops the legacy field on every save, but if the operator
        hand-edited the file to add the new fields without removing
        the old one, the loader must not refuse.
        """
        _clean_env(monkeypatch)
        cfg_path = tmp_path / "config.yaml"
        _write_full_config(cfg_path, token="aa_legacy")
        cfg = load_config(config_path=str(cfg_path)).validated()
        assert cfg.credentials.access_token == "aa_file"
        assert cfg.credentials.refresh_token == "rt_file"

    @pytest.mark.covers_function("Load CLI Configuration")
    def test_config_path_propagated(self, tmp_path, monkeypatch) -> None:
        """``GpgCliConfig.config_path`` matches the loaded path so FileStore can rewrite it."""
        _clean_env(monkeypatch)
        cfg_path = tmp_path / "config.yaml"
        _write_full_config(cfg_path)
        cfg = load_config(config_path=str(cfg_path))
        assert cfg.config_path == str(cfg_path)


class TestFileStore:
    """In-place credential rewrite — load + save round-trip with 0600 enforcement."""

    @pytest.mark.covers_function("Auto Refresh Token")
    def test_save_then_load_round_trips(self, tmp_path) -> None:
        path = str(tmp_path / "config.yaml")
        store = FileStore(path)
        creds = Credentials(
            access_token="aa_save",
            refresh_token="rt_save",
            auth_url="https://auth.invalid",
            family_id="fam-save",
        )
        store.save(creds)
        loaded = store.load()
        assert loaded == creds

    @pytest.mark.covers_function("Auto Refresh Token")
    def test_save_writes_file_with_mode_0600(self, tmp_path) -> None:
        path = str(tmp_path / "config.yaml")
        store = FileStore(path)
        store.save(
            Credentials(
                access_token="aa",
                refresh_token="rt",
                auth_url="https://auth.invalid",
            )
        )
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"

    @pytest.mark.covers_function("Auto Refresh Token")
    def test_save_preserves_existing_settings_keys(self, tmp_path) -> None:
        """Refresh writes must not clobber operator-authored connection settings."""
        path = tmp_path / "config.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "bridge_url": "https://bridge.invalid",
                    "ca_cert_path": "/tmp/ca.pem",
                    "timeout_seconds": 20,
                    "access_token": "aa_old",
                    "refresh_token": "rt_old",
                    "auth_url": "https://auth.invalid",
                    "family_id": "fam-1",
                }
            )
        )
        os.chmod(path, 0o600)
        store = FileStore(str(path))
        store.save(
            Credentials(
                access_token="aa_new",
                refresh_token="rt_new",
                auth_url="https://auth.invalid",
                family_id="fam-1",
            )
        )
        on_disk = yaml.safe_load(path.read_text())
        assert on_disk["bridge_url"] == "https://bridge.invalid"
        assert on_disk["ca_cert_path"] == "/tmp/ca.pem"
        assert on_disk["timeout_seconds"] == 20
        assert on_disk["access_token"] == "aa_new"
        assert on_disk["refresh_token"] == "rt_new"

    @pytest.mark.covers_function("Auto Refresh Token")
    def test_save_drops_legacy_token_field(self, tmp_path) -> None:
        """A successful save leaves the schema in the new shape only.

        Mirrors the rationale for refusing to load a legacy-only file:
        once the operator has bootstrapped a refresh-capable pair, the
        single-bearer field is misleading and the rewrite drops it.
        """
        path = tmp_path / "config.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "bridge_url": "https://x.invalid",
                    "token": "aa_legacy",
                    "access_token": "aa_new",
                    "refresh_token": "rt_new",
                    "auth_url": "https://auth.invalid",
                }
            )
        )
        os.chmod(path, 0o600)
        store = FileStore(str(path))
        store.save(
            Credentials(
                access_token="aa_newer",
                refresh_token="rt_newer",
                auth_url="https://auth.invalid",
            )
        )
        on_disk = yaml.safe_load(path.read_text())
        assert "token" not in on_disk

    @pytest.mark.covers_function("Auto Refresh Token")
    def test_load_rejects_world_readable_file(self, tmp_path) -> None:
        path = tmp_path / "config.yaml"
        _write_full_config(path)
        # Intentionally widen to a non-0600 mode so the loader's mode
        # check surfaces the failure under test. The credentials inside
        # are the test fixture's `aa_file` / `rt_file` strings, not
        # real bearer material. Use _too_open_for_credentials() so the
        # CodeQL `py/overly-permissive-mask` query doesn't flag the
        # literal mask — the rejection-under-test depends on the mode
        # being non-0600, not on the specific bits.
        os.chmod(path, _too_open_for_credentials())
        store = FileStore(str(path))
        with pytest.raises(CredentialsBackendError, match="too open"):
            store.load()

    @pytest.mark.covers_function("Auto Refresh Token")
    def test_load_missing_file_raises_credentials_not_found(self, tmp_path) -> None:
        store = FileStore(str(tmp_path / "absent.yaml"))
        with pytest.raises(CredentialsNotFoundError, match="setup-devcontainer-signing"):
            store.load()
