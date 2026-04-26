# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Configuration loading for gpg-bridge.

Paths follow the XDG Base Directory Specification:
- Config: ``$XDG_CONFIG_HOME/gpg-bridge`` (default ``~/.config/gpg-bridge``)
- State:  ``$XDG_STATE_HOME/gpg-bridge``  (default ``~/.local/state/gpg-bridge``)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, cast

import yaml


def _xdg_dir(env_var: str, fallback_segments: tuple[str, ...]) -> str:
    base = os.environ.get(env_var) or os.path.join(os.path.expanduser("~"), *fallback_segments)
    return os.path.join(base, "gpg-bridge")


def _default_config_dir() -> str:
    return _xdg_dir("XDG_CONFIG_HOME", (".config",))


def _default_state_dir() -> str:
    return _xdg_dir("XDG_STATE_HOME", (".local", "state"))


def _default_gpg_command() -> list[str]:
    return ["gpg"]


def _empty_str_list() -> list[str]:
    return []


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 9300
    auth_url: str = "http://127.0.0.1:9100"
    # Argv prefix used to invoke gpg. Defaults to whatever ``gpg`` PATH
    # resolves to on the host. Tests override this to point at the
    # in-tree fake (``python -m gpg_backend_fake --fixtures …``).
    # Renamed from ``gpg_backend_command`` in 2026-04 (issue #316,
    # ADR 0033 amendment) when the separate backend CLI was collapsed
    # into the bridge.
    gpg_command: list[str] = field(default_factory=_default_gpg_command)
    request_timeout_seconds: float = 35.0
    shutdown_deadline_seconds: float = 5.0
    log_path: str = ""
    tls_cert_path: str = ""
    tls_key_path: str = ""
    auth_ca_cert_path: str = ""
    # Long key IDs or full fingerprints allowed for ``--local-user``.
    # Empty list = trust any key the host gpg has.
    allowed_signing_keys: list[str] = field(default_factory=_empty_str_list)
    # Cap on HTTP request body size. Commit payloads are a few KiB in
    # practice; 1 MiB fails closed before the gpg subprocess spawn.
    max_request_bytes: int = 1 * 1024 * 1024
    # When true (default), the bridge consults its keyring-backed
    # :class:`gpg_bridge.passphrase_store.KeyringPassphraseStore` on
    # each sign request and feeds any stored passphrase to ``gpg``
    # via ``--passphrase-fd``. Operators who prefer to keep relying
    # on the host ``gpg-agent``'s passphrase cache (or who run with
    # passphrase-less signing keys) set this to ``false`` to revert
    # the sign path to its pre-ADR-0042 shape (no keyring read, no
    # ``--passphrase-fd`` in argv). The keyring is empty on first
    # boot, so a no-op default still matches the keyless / cached
    # path until the operator runs ``gpg-bridge passphrase set``.
    passphrase_store_enabled: bool = True

    def __post_init__(self) -> None:
        if not self.log_path:
            self.log_path = os.path.join(_default_state_dir(), "server.log")
        if bool(self.tls_cert_path) != bool(self.tls_key_path):
            raise ValueError(
                "Config: tls_cert_path and tls_key_path must both be set or both be empty; "
                f"got cert={self.tls_cert_path!r} key={self.tls_key_path!r}"
            )
        if not self.gpg_command:
            raise ValueError("Config: gpg_command must not be empty")
        normalised: list[str] = []
        for entry in self.allowed_signing_keys:
            stripped = str(entry).strip().upper()
            if stripped:
                normalised.append(stripped)
        self.allowed_signing_keys = normalised

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_cert_path and self.tls_key_path)

    def key_allowed(self, requested: str) -> bool:
        """Return True if the allowlist permits signing with ``requested``.

        Empty allowlist means "any key the host has". A non-empty
        allowlist matches case-insensitively and tolerates the ``0x``
        prefix gpg sometimes prints.
        """
        if not self.allowed_signing_keys:
            return True
        needle = requested.strip().upper()
        if needle.startswith("0X"):
            needle = needle[2:]
        for entry in self.allowed_signing_keys:
            candidate = entry[2:] if entry.startswith("0X") else entry
            if needle == candidate or needle.endswith(candidate) or candidate.endswith(needle):
                return True
        return False


def load_config(config_path: str | None = None) -> Config:
    """Load configuration from disk, or return defaults if the file is absent."""
    path = config_path or os.path.join(_default_config_dir(), "config.yaml")
    valid_fields = set(Config.__dataclass_fields__)
    if not os.path.exists(path):
        return Config()
    with open(path) as f:
        raw = yaml.safe_load(f)
    data: dict[str, Any] = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
    kwargs = {k: v for k, v in data.items() if k in valid_fields}
    return Config(**kwargs)
