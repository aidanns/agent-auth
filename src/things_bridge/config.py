# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Configuration loading for things-bridge.

Paths follow the XDG Base Directory Specification:
- Config: ``$XDG_CONFIG_HOME/things-bridge`` (default ``~/.config/things-bridge``)
- State:  ``$XDG_STATE_HOME/things-bridge``  (default ``~/.local/state/things-bridge``)
"""

import os
from dataclasses import dataclass, field
from typing import Any, cast

import yaml


def _xdg_dir(env_var: str, fallback_segments: tuple[str, ...]) -> str:
    base = os.environ.get(env_var) or os.path.join(os.path.expanduser("~"), *fallback_segments)
    return os.path.join(base, "things-bridge")


def _default_config_dir() -> str:
    return _xdg_dir("XDG_CONFIG_HOME", (".config",))


def _default_state_dir() -> str:
    return _xdg_dir("XDG_STATE_HOME", (".local", "state"))


def _default_things_client_command() -> list[str]:
    return ["things-client-cli-applescript"]


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 9200
    auth_url: str = "http://127.0.0.1:9100"
    # Argv prefix for the Things client subprocess. The bridge appends the
    # request-specific sub-command (``todos list --status open``, etc.)
    # before invoking. Tests override this to point at the in-tree fake.
    things_client_command: list[str] = field(default_factory=_default_things_client_command)
    # Kept above the shipped CLI's own 30s osascript timeout so the child can
    # surface a structured timeout envelope before the bridge kills it.
    request_timeout_seconds: float = 35.0
    log_path: str = ""

    def __post_init__(self) -> None:
        if not self.log_path:
            self.log_path = os.path.join(_default_state_dir(), "server.log")


def load_config() -> Config:
    """Load configuration from disk, or return defaults if the file is absent.

    Does not create the config directory or write a default config file — a
    freshly-installed things-bridge runs with built-in defaults until the user
    chooses to customise them.
    """
    config_dir = _default_config_dir()
    config_path = os.path.join(config_dir, "config.yaml")
    valid_fields = set(Config.__dataclass_fields__)

    if not os.path.exists(config_path):
        return Config()

    with open(config_path) as f:
        raw = yaml.safe_load(f)
    data: dict[str, Any] = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
    kwargs = {k: v for k, v in data.items() if k in valid_fields}
    return Config(**kwargs)
