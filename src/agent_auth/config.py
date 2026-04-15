"""Configuration loading for agent-auth.

Paths follow the XDG Base Directory Specification:
- Config: ``$XDG_CONFIG_HOME/agent-auth`` (default ``~/.config/agent-auth``)
- Data:   ``$XDG_DATA_HOME/agent-auth``   (default ``~/.local/share/agent-auth``)
- State:  ``$XDG_STATE_HOME/agent-auth``  (default ``~/.local/state/agent-auth``)
"""

import json
import os
from dataclasses import dataclass, field


def _xdg_dir(env_var: str, fallback_segments: tuple[str, ...]) -> str:
    base = os.environ.get(env_var) or os.path.join(os.path.expanduser("~"), *fallback_segments)
    return os.path.join(base, "agent-auth")


def _default_config_dir() -> str:
    return _xdg_dir("XDG_CONFIG_HOME", (".config",))


def _default_data_dir() -> str:
    return _xdg_dir("XDG_DATA_HOME", (".local", "share"))


def _default_state_dir() -> str:
    return _xdg_dir("XDG_STATE_HOME", (".local", "state"))


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 9100
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 28800
    notification_plugin: str = "terminal"
    notification_plugin_config: dict = field(default_factory=dict)
    db_path: str = ""
    log_path: str = ""

    def __post_init__(self):
        if not self.db_path:
            self.db_path = os.path.join(_default_data_dir(), "tokens.db")
        if not self.log_path:
            self.log_path = os.path.join(_default_state_dir(), "audit.log")


def load_config(config_dir: str | None = None) -> Config:
    """Load configuration from disk, or return defaults if the file is absent.

    Does not create the config directory or write a default config file — a
    freshly-installed agent-auth runs with built-in defaults until the user
    chooses to customise them.

    When ``config_dir`` is provided (e.g. via ``--config-dir`` or from tests),
    any default paths are rooted inside it so a single directory holds the
    config, database, and logs. Otherwise XDG defaults apply.
    """
    base_dir = config_dir or _default_config_dir()
    config_path = os.path.join(base_dir, "config.json")
    valid_fields = set(Config.__dataclass_fields__)

    if os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
        return Config(**{k: v for k, v in data.items() if k in valid_fields})

    if config_dir:
        return Config(
            db_path=os.path.join(config_dir, "tokens.db"),
            log_path=os.path.join(config_dir, "audit.log"),
        )

    return Config()
