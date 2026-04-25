# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Layered configuration and credential storage for gpg-cli.

Resolution precedence for non-credential settings (highest first):

1. CLI flags (not emitted by git, but usable for ``gpg-cli`` as a plain tool).
2. Environment variables (``AGENT_AUTH_GPG_*``).
3. Config file at ``$XDG_CONFIG_HOME/gpg-cli/config.yaml``.
4. Built-in defaults.

The same on-disk file also stores the agent-auth token *pair*
(``access_token``, ``refresh_token``, ``family_id``, ``auth_url``) used
by the refresh + reissue retry loop in :mod:`gpg_cli.client`. Storing
credentials and connection settings in a single YAML file is the
deliberate Option-A choice from issue #327: it keeps the gpg-cli layout
single-file while a follow-up issue consolidates with
:mod:`things_cli.credentials` (which has both file and keyring backends).

The file is rewritten in-place when the retry loop persists a new
token pair after a refresh / reissue. The store enforces ``0600`` on
read **and** write so operators can't accidentally widen the file with
an editor.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, cast

import yaml

from gpg_cli.errors import (
    ConfigMigrationRequiredError,
    CredentialsBackendError,
    CredentialsNotFoundError,
)

_DEFAULT_TIMEOUT_SECONDS = 30.0

# Credential field names that the refresh path rewrites in-place.
# Connection settings (bridge_url, ca_cert_path, timeout_seconds) are
# operator-authored and are preserved verbatim across refresh writes.
_CREDENTIAL_FIELDS = ("access_token", "refresh_token", "family_id", "auth_url")
_LEGACY_TOKEN_FIELD = "token"

_MIGRATION_HINT = (
    "gpg-cli: config file at {path} uses the pre-refresh single-token schema "
    "({legacy!r}). The single bearer cannot be migrated to a refresh-capable "
    "credential pair automatically. Re-run scripts/setup-devcontainer-signing.sh "
    "with --access-token / --refresh-token / --auth-url / --family-id "
    "(see CONTRIBUTING.md § 'Signed commits inside the devcontainer')."
)


def _xdg_config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "gpg-cli")


def _default_config_path() -> str:
    return os.path.join(_xdg_config_dir(), "config.yaml")


@dataclass
class Credentials:
    """Refresh-capable credential record persisted in the config file.

    Mutable because the refresh + reissue retry loop in
    :class:`gpg_cli.client.BridgeClient` rotates ``access_token`` /
    ``refresh_token`` in-place before persisting via
    :meth:`FileStore.save`.
    """

    access_token: str
    refresh_token: str
    auth_url: str
    family_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class GpgCliConfig:
    """Resolved gpg-cli configuration.

    Holds connection settings (``bridge_url``, ``ca_cert_path``,
    ``timeout_seconds``) and a :class:`Credentials` record. The
    credential record is held by reference so the retry loop can mutate
    it on refresh without round-tripping through this dataclass.
    """

    bridge_url: str
    credentials: Credentials
    config_path: str
    ca_cert_path: str = ""
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def validated(self) -> GpgCliConfig:
        if not self.bridge_url:
            raise ValueError(
                "gpg-cli: bridge_url is required (set via --bridge-url, "
                "AGENT_AUTH_GPG_BRIDGE_URL, or the config file)"
            )
        if not self.credentials.access_token:
            raise ValueError(
                "gpg-cli: access_token is required (set via --access-token, "
                "AGENT_AUTH_GPG_ACCESS_TOKEN, or the config file). Run "
                "scripts/setup-devcontainer-signing.sh to bootstrap the "
                "credential pair."
            )
        if not self.credentials.refresh_token:
            raise ValueError(
                "gpg-cli: refresh_token is required (set via --refresh-token, "
                "AGENT_AUTH_GPG_REFRESH_TOKEN, or the config file). Run "
                "scripts/setup-devcontainer-signing.sh to bootstrap the "
                "credential pair."
            )
        if not self.credentials.auth_url:
            raise ValueError(
                "gpg-cli: auth_url is required so refresh / reissue can reach "
                "agent-auth (set via --auth-url, AGENT_AUTH_GPG_AUTH_URL, or "
                "the config file)."
            )
        return self


class FileStore:
    """Persist :class:`Credentials` to ``$XDG_CONFIG_HOME/gpg-cli/config.yaml``.

    Mirrors :class:`things_cli.credentials.FileStore`'s on-disk discipline
    (atomic temp + rename, ``0600`` enforced both on write and on read)
    while keeping the credential fields in the same single YAML file
    that holds connection settings — see the module docstring for the
    rationale.
    """

    def __init__(self, path: str):
        self._path = path

    def save(self, creds: Credentials) -> None:
        Path(os.path.dirname(self._path)).mkdir(parents=True, exist_ok=True)
        merged = _read_existing(self._path)
        for name in _CREDENTIAL_FIELDS:
            value = getattr(creds, name)
            if value is None:
                merged.pop(name, None)
            else:
                merged[name] = value
        # Drop the legacy field on every write so a successful save
        # leaves the on-disk schema in the new shape even if the
        # operator hand-edited the file before the first refresh.
        merged.pop(_LEGACY_TOKEN_FIELD, None)
        _atomic_write_yaml(self._path, merged)

    def load(self) -> Credentials:
        try:
            data = _read_yaml_strict(self._path)
        except FileNotFoundError as exc:
            raise CredentialsNotFoundError(
                f"No gpg-cli config file at {self._path}. Run "
                f"scripts/setup-devcontainer-signing.sh to create one."
            ) from exc
        _reject_legacy_schema(self._path, data)
        required = ("access_token", "refresh_token", "auth_url")
        missing = [name for name in required if not data.get(name)]
        if missing:
            raise CredentialsNotFoundError(
                f"gpg-cli config file at {self._path} is missing fields: {missing}. "
                f"Run scripts/setup-devcontainer-signing.sh to bootstrap the "
                f"credential pair."
            )
        known = {f.name for f in fields(Credentials)}
        return Credentials(**{k: v for k, v in data.items() if k in known})

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._path)


def load_config(
    *,
    cli_bridge_url: str | None = None,
    cli_access_token: str | None = None,
    cli_refresh_token: str | None = None,
    cli_family_id: str | None = None,
    cli_auth_url: str | None = None,
    cli_ca_cert_path: str | None = None,
    cli_timeout_seconds: float | None = None,
    config_path: str | None = None,
) -> GpgCliConfig:
    """Resolve gpg-cli configuration with CLI > env > file > default precedence.

    Raises :class:`ConfigMigrationRequiredError` when the on-disk file
    uses the pre-refresh ``token:`` schema. Auto-migration is impossible
    (a single bearer has no refresh token to derive), so the operator
    must re-run the setup script.
    """
    path = config_path or _default_config_path()
    file_values: dict[str, Any] = {}
    if os.path.exists(path):
        with open(path) as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):
            file_values = cast(dict[str, Any], raw)
    _reject_legacy_schema(path, file_values)

    env_bridge_url = os.environ.get("AGENT_AUTH_GPG_BRIDGE_URL")
    env_access_token = os.environ.get("AGENT_AUTH_GPG_ACCESS_TOKEN")
    env_refresh_token = os.environ.get("AGENT_AUTH_GPG_REFRESH_TOKEN")
    env_family_id = os.environ.get("AGENT_AUTH_GPG_FAMILY_ID")
    env_auth_url = os.environ.get("AGENT_AUTH_GPG_AUTH_URL")
    env_ca_cert = os.environ.get("AGENT_AUTH_GPG_CA_CERT_PATH")
    env_timeout_raw = os.environ.get("AGENT_AUTH_GPG_TIMEOUT_SECONDS")

    bridge_url = _coalesce(cli_bridge_url, env_bridge_url, file_values.get("bridge_url"))
    access_token = _coalesce(cli_access_token, env_access_token, file_values.get("access_token"))
    refresh_token = _coalesce(
        cli_refresh_token, env_refresh_token, file_values.get("refresh_token")
    )
    auth_url = _coalesce(cli_auth_url, env_auth_url, file_values.get("auth_url"))
    family_id_raw = _coalesce(cli_family_id, env_family_id, file_values.get("family_id"))
    family_id = family_id_raw or None  # normalise empty string to None
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

    credentials = Credentials(
        access_token=str(access_token),
        refresh_token=str(refresh_token),
        auth_url=str(auth_url),
        family_id=str(family_id) if family_id else None,
    )
    return GpgCliConfig(
        bridge_url=str(bridge_url),
        credentials=credentials,
        config_path=path,
        ca_cert_path=str(ca_cert_path),
        timeout_seconds=timeout_seconds,
    )


def _coalesce(*values: str | None) -> str:
    """Return the first non-empty value, falling back to ``""``."""
    for value in values:
        if value:
            return str(value)
    return ""


def _reject_legacy_schema(path: str, data: dict[str, Any]) -> None:
    """Refuse to load the pre-refresh single-token schema."""
    has_legacy = bool(data.get(_LEGACY_TOKEN_FIELD))
    has_new = any(data.get(name) for name in _CREDENTIAL_FIELDS)
    if has_legacy and not has_new:
        raise ConfigMigrationRequiredError(
            _MIGRATION_HINT.format(path=path, legacy=_LEGACY_TOKEN_FIELD)
        )


def _read_existing(path: str) -> dict[str, Any]:
    """Read the YAML file at ``path`` for in-place rewrite.

    Missing file => ``{}`` so the first save lands cleanly. The 0600
    check is *not* applied here because :meth:`FileStore.save` always
    writes a fresh file with mode 0600 regardless of the prior mode;
    enforcing the read-side check would block the very save that fixes
    a wrong-mode file.
    """
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CredentialsBackendError(
            f"Config file at {path} is corrupt: expected a YAML mapping, got "
            f"{type(raw).__name__}"
        )
    return cast(dict[str, Any], raw)


def _read_yaml_strict(path: str) -> dict[str, Any]:
    """Read the YAML file at ``path`` enforcing 0600 mode.

    Raises :class:`FileNotFoundError` (translated by the caller),
    :class:`CredentialsBackendError` for wrong mode or malformed YAML.
    """
    actual_mode = os.stat(path).st_mode & 0o777
    if actual_mode != 0o600:
        raise CredentialsBackendError(
            f"Permissions {oct(actual_mode)} for {path!r} are too open. "
            f"Credentials file must not be accessible by others. "
            f"Run: chmod 600 {path!r}"
        )
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise CredentialsBackendError(f"Config file at {path} is corrupt: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CredentialsBackendError(
            f"Config file at {path} is corrupt: expected a YAML mapping, got "
            f"{type(raw).__name__}"
        )
    return cast(dict[str, Any], raw)


def _atomic_write_yaml(path: str, data: dict[str, Any]) -> None:
    """Atomically replace ``path`` with ``data`` serialised as YAML, mode 0600.

    The temp file is opened with mode 0600 *before* any data is written
    so the credentials never spend a moment world-readable on disk.
    """
    tmp_path = path + ".tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=True)
    except Exception:
        os.unlink(tmp_path)
        raise
    os.replace(tmp_path, path)
    actual_mode = os.stat(path).st_mode & 0o777
    if actual_mode != 0o600:
        raise CredentialsBackendError(
            f"Config file {path} has mode {oct(actual_mode)}, expected 0o600"
        )


__all__ = [
    "Credentials",
    "FileStore",
    "GpgCliConfig",
    "load_config",
]
