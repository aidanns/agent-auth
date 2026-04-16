"""Configuration loading for things-bridge.

Paths follow the XDG Base Directory Specification:
- Config: ``$XDG_CONFIG_HOME/things-bridge`` (default ``~/.config/things-bridge``)
- State:  ``$XDG_STATE_HOME/things-bridge``  (default ``~/.local/state/things-bridge``)
"""

import json
import os
from dataclasses import dataclass


def _xdg_dir(env_var: str, fallback_segments: tuple[str, ...]) -> str:
    base = os.environ.get(env_var) or os.path.join(os.path.expanduser("~"), *fallback_segments)
    return os.path.join(base, "things-bridge")


def _default_config_dir() -> str:
    return _xdg_dir("XDG_CONFIG_HOME", (".config",))


def _default_state_dir() -> str:
    return _xdg_dir("XDG_STATE_HOME", (".local", "state"))


@dataclass
class Config:
    config_dir: str = ""
    host: str = "127.0.0.1"
    port: int = 9200
    auth_url: str = "http://127.0.0.1:9100"
    osascript_path: str = "/usr/bin/osascript"
    request_timeout_seconds: float = 30.0
    log_path: str = ""

    def __post_init__(self):
        if not self.log_path:
            self.log_path = os.path.join(_default_state_dir(), "bridge.log")


def load_config(config_dir: str | None = None) -> Config:
    """Load configuration from disk, or return defaults if the file is absent.

    Does not create the config directory or write a default config file — a
    freshly-installed things-bridge runs with built-in defaults until the user
    chooses to customise them.
    """
    base_dir = config_dir or _default_config_dir()
    config_path = os.path.join(base_dir, "config.json")
    valid_fields = set(Config.__dataclass_fields__)

    if os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
        data["config_dir"] = base_dir
        return Config(**{k: v for k, v in data.items() if k in valid_fields})

    if config_dir:
        return Config(
            config_dir=config_dir,
            log_path=os.path.join(config_dir, "bridge.log"),
        )

    return Config()
