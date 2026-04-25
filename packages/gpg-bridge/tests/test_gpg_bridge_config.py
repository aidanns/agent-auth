# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for :mod:`gpg_bridge.config`."""

from __future__ import annotations

import os

import pytest

from gpg_bridge.config import Config, load_config


class TestConfigDefaults:
    @pytest.mark.covers_function("Load Bridge Configuration")
    def test_defaults(self) -> None:
        cfg = Config()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9300
        assert cfg.gpg_backend_command == ["gpg-backend-cli-host"]
        assert cfg.allowed_signing_keys == []

    @pytest.mark.covers_function("Load Bridge Configuration")
    def test_tls_half_configured_raises(self) -> None:
        with pytest.raises(ValueError, match="tls_cert_path and tls_key_path"):
            Config(tls_cert_path="cert.pem")

    @pytest.mark.covers_function("Load Bridge Configuration")
    def test_empty_backend_command_rejected(self) -> None:
        with pytest.raises(ValueError, match="gpg_backend_command"):
            Config(gpg_backend_command=[])

    @pytest.mark.covers_function("Load Bridge Configuration")
    def test_tls_enabled_when_both_set(self, tmp_path) -> None:
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("x")
        key.write_text("y")
        cfg = Config(tls_cert_path=str(cert), tls_key_path=str(key))
        assert cfg.tls_enabled


class TestAllowedSigningKeys:
    @pytest.mark.covers_function("Apply Per-Key Allowlist")
    def test_normalises_case_and_strips(self) -> None:
        cfg = Config(allowed_signing_keys=["  abcd1234  ", "0xdeadbeef"])
        assert cfg.allowed_signing_keys == ["ABCD1234", "0XDEADBEEF"]

    @pytest.mark.covers_function("Apply Per-Key Allowlist")
    def test_empty_allowlist_allows_any(self) -> None:
        cfg = Config()
        assert cfg.key_allowed("any-key")
        assert cfg.key_allowed("0xDEAD")

    @pytest.mark.covers_function("Apply Per-Key Allowlist")
    def test_allowlist_exact_match(self) -> None:
        cfg = Config(allowed_signing_keys=["ABCDEF0123456789"])
        assert cfg.key_allowed("abcdef0123456789")
        assert cfg.key_allowed("0xABCDEF0123456789")
        assert not cfg.key_allowed("1234")

    @pytest.mark.covers_function("Apply Per-Key Allowlist")
    def test_allowlist_suffix_match_for_short_id(self) -> None:
        # gpg short / long ids are tail substrings of the full fingerprint.
        cfg = Config(allowed_signing_keys=["0123456789ABCDEF0123456789ABCDEF01234567"])
        assert cfg.key_allowed("89ABCDEF01234567")


class TestLoadConfig:
    @pytest.mark.covers_function("Load Bridge Configuration")
    def test_missing_file_returns_defaults(self, tmp_path) -> None:
        cfg = load_config(str(tmp_path / "absent.yaml"))
        assert cfg == Config()

    @pytest.mark.covers_function("Load Bridge Configuration")
    def test_reads_yaml(self, tmp_path) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("host: 0.0.0.0\nport: 9999\nallowed_signing_keys:\n  - ABCD1234\n")
        cfg = load_config(str(cfg_path))
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9999
        assert cfg.allowed_signing_keys == ["ABCD1234"]

    @pytest.mark.covers_function("Load Bridge Configuration")
    def test_ignores_unknown_fields(self, tmp_path) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("host: 127.0.0.1\nfoo: bar\n")
        cfg = load_config(str(cfg_path))
        assert cfg.host == "127.0.0.1"

    @pytest.mark.covers_function("Load Bridge Configuration")
    def test_log_path_defaults_under_state_dir(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        cfg = Config()
        assert cfg.log_path.startswith(str(tmp_path))
        assert os.path.basename(cfg.log_path) == "server.log"
