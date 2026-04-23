# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Configuration loading for agent-auth.

Paths follow the XDG Base Directory Specification:
- Config: ``$XDG_CONFIG_HOME/agent-auth`` (default ``~/.config/agent-auth``)
- Data:   ``$XDG_DATA_HOME/agent-auth``   (default ``~/.local/share/agent-auth``)
- State:  ``$XDG_STATE_HOME/agent-auth``  (default ``~/.local/state/agent-auth``)
"""

import os
from dataclasses import dataclass
from typing import Any, cast

import yaml


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
    # URL of the out-of-process notifier that agent-auth POSTs to
    # on a prompt-tier approval. Default empty = no notifier
    # configured → prompt-tier scopes fail closed (deny). See ADR
    # 0023 and `design/DESIGN.md` "Notification plugin wire
    # protocol".
    notification_plugin_url: str = ""
    notification_plugin_timeout_seconds: float = 30.0
    db_path: str = ""
    log_path: str = ""
    # Upper bound on how long ``serve`` will wait for in-flight requests to
    # drain after SIGTERM before a watchdog thread force-exits the process.
    # Must fit inside the deployment's container ``stop_grace_period``.
    shutdown_deadline_seconds: float = 5.0
    # TLS server-side config. Both paths must be set together to enable
    # TLS; setting only one is a config error. When neither is set the
    # server binds plaintext HTTP — fine for the default loopback-only
    # deployment (SC-8 satisfied by the 127.0.0.1 bind), required for
    # devcontainer-to-host deployments where the socket crosses a
    # virtual network interface (see ADR 0025).
    tls_cert_path: str = ""
    tls_key_path: str = ""
    # Per-token-family request ceiling in requests per minute. Each
    # request that resolves a non-revoked ``family_id`` consumes one
    # token from an in-memory bucket keyed on that family; an
    # exhausted bucket surfaces as 429 with a ``Retry-After`` header.
    # Bucket capacity equals the per-minute rate, so the first minute
    # of a fresh family can burst the full quota. A value of 0
    # disables rate limiting entirely (the deferred posture originally
    # recorded in ADR 0022 and superseded by ADR 0026). The default of
    # 600 (10 rps) is above any interactive workload but tight enough
    # to bound a compromised-process DB-growth rate.
    rate_limit_per_minute: int = 600

    def __post_init__(self) -> None:
        if not self.db_path:
            self.db_path = os.path.join(_default_data_dir(), "tokens.db")
        if not self.log_path:
            self.log_path = os.path.join(_default_state_dir(), "audit.log")
        # Fail loudly when only one half of the TLS pair is present.
        # Silently falling back to plaintext here would be a security
        # foot-gun; downgrading from an intended TLS deployment to
        # plaintext is exactly the regression SC-8 is meant to prevent.
        if bool(self.tls_cert_path) != bool(self.tls_key_path):
            raise ValueError(
                "Config: tls_cert_path and tls_key_path must both be set or both be empty; "
                f"got cert={self.tls_cert_path!r} key={self.tls_key_path!r}"
            )

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_cert_path and self.tls_key_path)


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
    config_path = os.path.join(base_dir, "config.yaml")
    valid_fields = set(Config.__dataclass_fields__)

    if os.path.exists(config_path):
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        if raw is None:
            data: dict[str, Any] = {}
        elif isinstance(raw, dict):
            data = cast(dict[str, Any], raw)
        else:
            raise ValueError(
                f"Config file at {config_path} must be a YAML mapping, " f"got {type(raw).__name__}"
            )
        return Config(**{k: v for k, v in data.items() if k in valid_fields})

    if config_dir:
        return Config(
            db_path=os.path.join(config_dir, "tokens.db"),
            log_path=os.path.join(config_dir, "audit.log"),
        )

    return Config()
