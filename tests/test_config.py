# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for configuration loading."""

import json
import os

from agent_auth.config import Config, load_config


def test_default_config_when_file_absent(tmp_dir):
    """load_config returns defaults without creating a config file."""
    config = load_config(tmp_dir)
    assert config.host == "127.0.0.1"
    assert config.port == 9100
    assert config.access_token_ttl_seconds == 900
    assert config.refresh_token_ttl_seconds == 28800
    assert config.notification_plugin == "terminal"
    # Defaults must not be persisted — the config file is optional.
    assert not os.path.exists(os.path.join(tmp_dir, "config.json"))


def test_default_config_dir_roots_paths_when_no_file(tmp_dir):
    """Passing config_dir roots the db and log paths inside it."""
    config = load_config(tmp_dir)
    assert config.db_path == os.path.join(tmp_dir, "tokens.db")
    assert config.log_path == os.path.join(tmp_dir, "audit.log")


def test_loads_existing_config(tmp_dir):
    config_path = os.path.join(tmp_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump({"port": 9999, "notification_plugin": "desktop"}, f)

    config = load_config(tmp_dir)
    assert config.port == 9999
    assert config.notification_plugin == "desktop"


def test_config_post_init_xdg_defaults(monkeypatch, tmp_path):
    """Without a config_dir override, paths follow the XDG spec."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config = Config()
    assert config.db_path == str(tmp_path / "data" / "agent-auth" / "tokens.db")
    assert config.log_path == str(tmp_path / "state" / "agent-auth" / "audit.log")
