# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Layered configuration for gpg-cli.

Resolution precedence (highest first):
1. CLI flags (not emitted by git, but usable for ``gpg-cli`` as a plain tool).
2. Environment variables (``AGENT_AUTH_GPG_*``).
3. Config file at ``$XDG_CONFIG_HOME/gpg-cli/config.yaml``.
4. Built-in defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, cast

import yaml

_DEFAULT_TIMEOUT_SECONDS = 30.0


def _xdg_config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "gpg-cli")


def _default_config_path() -> str:
    return os.path.join(_xdg_config_dir(), "config.yaml")


@dataclass(frozen=True)
class GpgCliConfig:
    bridge_url: str = ""
    token: str = ""
    ca_cert_path: str = ""
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def validated(self) -> GpgCliConfig:
        if not self.bridge_url:
            raise ValueError(
                "gpg-cli: bridge_url is required (set via --bridge-url, "
                "AGENT_AUTH_GPG_BRIDGE_URL, or the config file)"
            )
        if not self.token:
            raise ValueError(
                "gpg-cli: token is required (set via --token, "
                "AGENT_AUTH_GPG_TOKEN, or the config file)"
            )
        return self


def load_config(
    *,
    cli_bridge_url: str | None = None,
    cli_token: str | None = None,
    cli_ca_cert_path: str | None = None,
    cli_timeout_seconds: float | None = None,
    config_path: str | None = None,
) -> GpgCliConfig:
    path = config_path or _default_config_path()
    file_values: dict[str, Any] = {}
    if os.path.exists(path):
        with open(path) as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):
            file_values = cast(dict[str, Any], raw)

    env_bridge_url = os.environ.get("AGENT_AUTH_GPG_BRIDGE_URL")
    env_token = os.environ.get("AGENT_AUTH_GPG_TOKEN")
    env_ca_cert = os.environ.get("AGENT_AUTH_GPG_CA_CERT_PATH")
    env_timeout_raw = os.environ.get("AGENT_AUTH_GPG_TIMEOUT_SECONDS")

    bridge_url = (
        cli_bridge_url
        if cli_bridge_url
        else (env_bridge_url or file_values.get("bridge_url") or "")
    )
    token = cli_token if cli_token else (env_token or file_values.get("token") or "")
    ca_cert_path = (
        cli_ca_cert_path
        if cli_ca_cert_path is not None
        else (env_ca_cert or file_values.get("ca_cert_path") or "")
    )

    if cli_timeout_seconds is not None:
        timeout_seconds = cli_timeout_seconds
    elif env_timeout_raw:
        try:
            timeout_seconds = float(env_timeout_raw)
        except ValueError as exc:
            raise ValueError(
                f"AGENT_AUTH_GPG_TIMEOUT_SECONDS: expected a float, got {env_timeout_raw!r}"
            ) from exc
    else:
        raw_timeout = file_values.get("timeout_seconds")
        timeout_seconds = (
            float(raw_timeout) if isinstance(raw_timeout, int | float) else _DEFAULT_TIMEOUT_SECONDS
        )

    return GpgCliConfig(
        bridge_url=str(bridge_url),
        token=str(token),
        ca_cert_path=str(ca_cert_path),
        timeout_seconds=timeout_seconds,
    )


__all__ = ["GpgCliConfig", "load_config"]
