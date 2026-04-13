"""Tests for configuration loading."""

import json
import os

from agent_auth.config import Config, load_config


def test_default_config(tmp_dir):
    config = load_config(tmp_dir)
    assert config.host == "127.0.0.1"
    assert config.port == 9100
    assert config.access_token_ttl == 900
    assert config.refresh_token_ttl == 28800
    assert config.notification_plugin == "terminal"
    assert os.path.exists(os.path.join(tmp_dir, "config.json"))


def test_loads_existing_config(tmp_dir):
    config_path = os.path.join(tmp_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump({"port": 9999, "notification_plugin": "desktop"}, f)

    config = load_config(tmp_dir)
    assert config.port == 9999
    assert config.notification_plugin == "desktop"


def test_config_post_init_defaults():
    config = Config()
    assert config.db_path.endswith("tokens.db")
    assert config.log_path.endswith("audit.log")
