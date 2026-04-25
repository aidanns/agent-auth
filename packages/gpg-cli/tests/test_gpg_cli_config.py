# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for gpg-cli layered configuration."""

from __future__ import annotations

import pytest

from gpg_cli.config import load_config


class TestLoadConfig:
    def test_env_overrides_file(self, tmp_path, monkeypatch) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "bridge_url: https://file.example.invalid\n"
            "token: file-token\n"
            "timeout_seconds: 12.5\n"
        )
        monkeypatch.setenv("AGENT_AUTH_GPG_BRIDGE_URL", "https://env.example.invalid")
        monkeypatch.setenv("AGENT_AUTH_GPG_TOKEN", "env-token")
        cfg = load_config(config_path=str(cfg_path)).validated()
        assert cfg.bridge_url == "https://env.example.invalid"
        assert cfg.token == "env-token"
        assert cfg.timeout_seconds == 12.5

    def test_cli_overrides_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_AUTH_GPG_BRIDGE_URL", "https://env.example.invalid")
        monkeypatch.setenv("AGENT_AUTH_GPG_TOKEN", "env-token")
        cfg = load_config(
            cli_bridge_url="https://cli.example.invalid",
            cli_token="cli-token",
            config_path=str(tmp_path / "absent.yaml"),
        ).validated()
        assert cfg.bridge_url == "https://cli.example.invalid"
        assert cfg.token == "cli-token"

    def test_missing_token_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_AUTH_GPG_BRIDGE_URL", "https://x.invalid")
        monkeypatch.delenv("AGENT_AUTH_GPG_TOKEN", raising=False)
        monkeypatch.delenv("AGENT_AUTH_GPG_CA_CERT_PATH", raising=False)
        monkeypatch.delenv("AGENT_AUTH_GPG_TIMEOUT_SECONDS", raising=False)
        cfg = load_config(config_path=str(tmp_path / "absent.yaml"))
        with pytest.raises(ValueError, match="token is required"):
            cfg.validated()

    def test_missing_bridge_url_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("AGENT_AUTH_GPG_BRIDGE_URL", raising=False)
        monkeypatch.setenv("AGENT_AUTH_GPG_TOKEN", "x")
        cfg = load_config(config_path=str(tmp_path / "absent.yaml"))
        with pytest.raises(ValueError, match="bridge_url is required"):
            cfg.validated()

    def test_env_timeout_parses(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_AUTH_GPG_BRIDGE_URL", "http://x")
        monkeypatch.setenv("AGENT_AUTH_GPG_TOKEN", "t")
        monkeypatch.setenv("AGENT_AUTH_GPG_TIMEOUT_SECONDS", "17.0")
        cfg = load_config(config_path=str(tmp_path / "absent.yaml")).validated()
        assert cfg.timeout_seconds == 17.0

    def test_env_timeout_rejects_non_numeric(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_AUTH_GPG_TIMEOUT_SECONDS", "abc")
        monkeypatch.setenv("AGENT_AUTH_GPG_BRIDGE_URL", "http://x")
        monkeypatch.setenv("AGENT_AUTH_GPG_TOKEN", "t")
        with pytest.raises(ValueError, match="expected a float"):
            load_config(config_path=str(tmp_path / "absent.yaml"))
