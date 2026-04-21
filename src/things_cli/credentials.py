# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Credential storage for things-cli.

Two backends:

- :class:`KeyringStore` — default; uses the ``keyring`` library to store each
  credential field as a separate entry under the ``things-cli`` service.
- :class:`FileStore` — opt-in via ``--credential-store=file``; writes a single
  YAML file at ``~/.config/things-cli/credentials.yaml`` with mode ``0600``.

Stored fields match the table in ``design/DESIGN.md``:
``access_token``, ``refresh_token``, ``family_id``, ``bridge_url``, ``auth_url``.
"""

import contextlib
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, cast

import keyring
import yaml
from keyring.errors import KeyringError as _KeyringBackendError

from things_cli.errors import CredentialsBackendError, CredentialsNotFoundError

SERVICE_NAME = "things-cli"
_FIELDS = ("access_token", "refresh_token", "family_id", "bridge_url", "auth_url")
_REQUIRED_FIELDS = ("access_token", "refresh_token", "bridge_url", "auth_url")


@dataclass
class Credentials:
    access_token: str
    refresh_token: str
    bridge_url: str
    auth_url: str
    family_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


class CredentialStore:
    """Abstract credential store."""

    def save(self, creds: Credentials) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def load(self) -> Credentials:  # pragma: no cover - interface
        raise NotImplementedError

    def clear(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def exists(self) -> bool:
        try:
            self.load()
        except CredentialsNotFoundError:
            return False
        return True


class KeyringStore(CredentialStore):
    """Persist credentials via the system keyring."""

    def __init__(self, service: str = SERVICE_NAME):
        self._service = service

    def save(self, creds: Credentials) -> None:
        try:
            for name in _FIELDS:
                value = getattr(creds, name)
                if value is None:
                    _delete_quietly(self._service, name)
                    continue
                keyring.set_password(self._service, name, value)
        except _KeyringBackendError as exc:
            raise CredentialsBackendError(f"Keyring backend failed: {exc}") from exc

    def load(self) -> Credentials:
        try:
            values = {name: keyring.get_password(self._service, name) for name in _FIELDS}
        except _KeyringBackendError as exc:
            raise CredentialsBackendError(f"Keyring backend failed: {exc}") from exc
        missing = [name for name in _REQUIRED_FIELDS if not values.get(name)]
        if missing:
            raise CredentialsNotFoundError(
                f"No credentials found in keyring; missing {missing}. Run `things-cli login`."
            )
        # Required-field narrowing: ``missing`` is empty, so each required
        # entry is a non-empty string.
        access_token = values["access_token"]
        refresh_token = values["refresh_token"]
        bridge_url = values["bridge_url"]
        auth_url = values["auth_url"]
        assert access_token is not None
        assert refresh_token is not None
        assert bridge_url is not None
        assert auth_url is not None
        return Credentials(
            access_token=access_token,
            refresh_token=refresh_token,
            bridge_url=bridge_url,
            auth_url=auth_url,
            family_id=values.get("family_id"),
        )

    def clear(self) -> None:
        for name in _FIELDS:
            _delete_quietly(self._service, name)


def _delete_quietly(service: str, name: str) -> None:
    try:
        keyring.delete_password(service, name)
    except _KeyringBackendError:
        # No existing entry — treat as already cleared.
        pass
    except Exception:
        # Some backends raise PasswordDeleteError which subclasses Exception
        # but not KeyringError; treat as best-effort.
        pass


class FileStore(CredentialStore):
    """Persist credentials to ``~/.config/things-cli/credentials.yaml`` with 0600 mode."""

    def __init__(self, path: str):
        self._path = path

    def save(self, creds: Credentials) -> None:
        Path(os.path.dirname(self._path)).mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in creds.to_dict().items() if v is not None}
        # Write atomically: create temp file with 0600, write, then rename.
        # The 0600 mode is set on open (before any data is written) so that
        # credentials are never world-readable, even momentarily.
        tmp_path = self._path + ".tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                yaml.safe_dump(data, f, default_flow_style=False)
        except Exception:
            os.unlink(tmp_path)
            raise
        os.replace(tmp_path, self._path)
        # Verify the final file has the correct permissions.
        actual_mode = os.stat(self._path).st_mode & 0o777
        if actual_mode != 0o600:
            raise CredentialsBackendError(
                f"Credentials file {self._path} has mode {oct(actual_mode)}, expected 0o600"
            )

    def load(self) -> Credentials:
        try:
            actual_mode = os.stat(self._path).st_mode & 0o777
        except FileNotFoundError as exc:
            raise CredentialsNotFoundError(
                f"No credentials file at {self._path}. Run `things-cli login`."
            ) from exc
        if actual_mode != 0o600:
            raise CredentialsBackendError(
                f"Permissions {oct(actual_mode)} for '{self._path}' are too open. "
                f"Credentials file must not be accessible by others. "
                f"Run: chmod 600 '{self._path}'"
            )
        try:
            with open(self._path) as f:
                raw = yaml.safe_load(f)
            data: dict[str, Any] = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
        except yaml.YAMLError as exc:
            raise CredentialsBackendError(
                f"Credentials file at {self._path} is corrupt: {exc}"
            ) from exc
        missing = [name for name in _REQUIRED_FIELDS if not data.get(name)]
        if missing:
            raise CredentialsNotFoundError(
                f"Credentials file at {self._path} is missing fields: {missing}"
            )
        known = {f.name for f in fields(Credentials)}
        return Credentials(**{k: v for k, v in data.items() if k in known})

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._path)


def select_store(
    backend: str = "auto",
    *,
    file_path: str | None = None,
    service: str = SERVICE_NAME,
) -> CredentialStore:
    """Select a credential store backend.

    ``backend`` values:
    - ``"keyring"`` — always use keyring (raises if unavailable)
    - ``"file"`` — always use the file store; ``file_path`` must be provided
    - ``"auto"`` — use keyring if a non-fail backend is available, otherwise
      fall back to the on-disk file store automatically

    The CLI layer is responsible for mapping ``--credential-store=file`` to
    ``"file"`` and defaulting otherwise.
    """
    if backend == "file":
        if file_path is None:
            raise ValueError("file_path is required when backend='file'")
        return FileStore(file_path)
    if backend == "keyring":
        return KeyringStore(service=service)
    if backend == "auto":
        if _keyring_available():
            return KeyringStore(service=service)
        if file_path is None:
            raise ValueError("file_path is required for file-store fallback")
        return FileStore(file_path)
    raise ValueError(f"Unknown credential store backend: {backend!r}")


def _keyring_available() -> bool:
    """Best-effort detection of a working keyring backend."""
    fail_keyring_cls: type | None
    try:
        from keyring.backends.fail import Keyring as _FailKeyring

        fail_keyring_cls = _FailKeyring
    except ImportError:
        fail_keyring_cls = None
    try:
        backend = keyring.get_keyring()
    except _KeyringBackendError:
        return False
    return not (fail_keyring_cls is not None and isinstance(backend, fail_keyring_cls))
