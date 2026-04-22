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
    # Upper bound on how long ``serve`` will wait for in-flight requests to
    # drain after SIGTERM before a watchdog thread force-exits the process.
    # Must fit inside the deployment's container ``stop_grace_period``.
    shutdown_deadline_seconds: float = 5.0
    log_path: str = ""
    # TLS server-side config. Both paths must be set together to enable
    # TLS; setting only one is a config error. Plaintext remains the
    # default for the loopback-only deployment; TLS is required when the
    # bridge is reached from a devcontainer over a virtual network
    # interface (see ADR 0025 and SECURITY.md §SC-8).
    tls_cert_path: str = ""
    tls_key_path: str = ""
    # PEM-encoded bundle used to verify ``auth_url`` when it is served
    # over HTTPS with a self-signed or private CA. Empty means fall back
    # to the system trust store (appropriate when ``auth_url`` uses a
    # public CA, or plaintext HTTP on loopback).
    auth_ca_cert_path: str = ""

    def __post_init__(self) -> None:
        if not self.log_path:
            self.log_path = os.path.join(_default_state_dir(), "server.log")
        # Fail loudly on half-configured TLS; silently degrading to
        # plaintext would break the SC-8 posture the field was added to
        # guarantee (see ADR 0025).
        if bool(self.tls_cert_path) != bool(self.tls_key_path):
            raise ValueError(
                "Config: tls_cert_path and tls_key_path must both be set or both be empty; "
                f"got cert={self.tls_cert_path!r} key={self.tls_key_path!r}"
            )

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_cert_path and self.tls_key_path)


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
