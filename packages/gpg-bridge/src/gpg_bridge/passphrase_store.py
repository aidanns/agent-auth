# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Bridge-owned passphrase persistence for gpg signing keys.

Stores per-fingerprint passphrases in the system keyring under
``service = "gpg-bridge"`` and ``username = <FP>``. See
:doc:`design/decisions/0042-gpg-bridge-passphrase-store` for the
trust-boundary discussion and ADR 0008 for the underlying
system-keyring posture this builds on.

The store is consumed by :class:`gpg_bridge.gpg_client.GpgSubprocessClient`
on the sign path: when ``get(<FP>)`` returns a non-empty passphrase the
bridge spawns ``gpg`` with ``--passphrase-fd`` and writes the value
into the child via :func:`os.pipe`. When ``get`` returns ``None`` the
existing keyless / agent-cached path runs unchanged.
"""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError as _KeyringBackendError

from gpg_bridge.errors import PassphraseStoreError

# Keyring service name. Per ADR 0008 each agent-auth-family service
# uses its own service name so the backend's ``list`` view stays
# legible to operators inspecting Keychain / libsecret directly.
SERVICE_NAME = "gpg-bridge"

# Sentinel pseudo-username under ``service = "gpg-bridge"`` whose
# entry value carries a newline-separated index of fingerprints
# currently holding a stored passphrase. Some keyring backends
# (notably macOS Keychain accessed via ``keyring``) do not expose
# a fully-portable "list usernames for service" API; tracking the
# index ourselves keeps :meth:`KeyringPassphraseStore.list_fingerprints`
# correct on every supported backend at the cost of one extra
# read-modify-write per ``set`` / ``delete``.
_INDEX_USERNAME = "__index__"


def _normalise_fingerprint(fingerprint: str) -> str:
    """Return the canonical form used as the keyring username.

    Uppercase hex, ``0x`` prefix stripped, whitespace stripped. Matches
    the normalisation in :class:`gpg_bridge.config.Config.key_allowed`
    so a fingerprint stored here resolves the same way the allowlist
    resolves a request.
    """
    needle = fingerprint.strip().upper()
    if needle.startswith("0X"):
        needle = needle[2:]
    if not needle:
        raise ValueError("fingerprint must not be empty")
    return needle


class KeyringPassphraseStore:
    """Persist per-fingerprint signing-key passphrases via the system keyring.

    Mirrors the shape of :class:`things_cli.credentials.KeyringStore`
    (one keyring entry per stable username, backend errors wrapped
    into a project-local exception type, idempotent ``delete``) but
    keyed per fingerprint instead of per credential field.
    """

    def __init__(self, service: str = SERVICE_NAME) -> None:
        self._service = service

    # ----- read --------------------------------------------------------------

    def get(self, fingerprint: str) -> str | None:
        """Return the stored passphrase for ``fingerprint``, or ``None``.

        Returns ``None`` rather than raising for the missing-entry case
        because every sign request consults the store; the absence of
        an entry is the common case, not an error.
        """
        username = _normalise_fingerprint(fingerprint)
        try:
            return keyring.get_password(self._service, username)
        except _KeyringBackendError as exc:
            raise PassphraseStoreError(f"Keyring backend failed: {exc}") from exc

    def list_fingerprints(self) -> list[str]:
        """Return the fingerprints currently holding a stored passphrase.

        Sourced from the keyring index entry, deduplicated and sorted
        for deterministic output. Never reads passphrases.
        """
        try:
            raw = keyring.get_password(self._service, _INDEX_USERNAME)
        except _KeyringBackendError as exc:
            raise PassphraseStoreError(f"Keyring backend failed: {exc}") from exc
        if not raw:
            return []
        seen: set[str] = set()
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped:
                seen.add(stripped)
        return sorted(seen)

    # ----- write -------------------------------------------------------------

    def set(self, fingerprint: str, passphrase: str) -> None:
        """Persist ``passphrase`` against ``fingerprint``.

        The empty string is rejected; an operator who wants to remove
        an entry calls :meth:`delete`.
        """
        if not passphrase:
            raise ValueError("passphrase must not be empty")
        username = _normalise_fingerprint(fingerprint)
        try:
            keyring.set_password(self._service, username, passphrase)
        except _KeyringBackendError as exc:
            raise PassphraseStoreError(f"Keyring backend failed: {exc}") from exc
        self._update_index(add=username)

    def delete(self, fingerprint: str) -> None:
        """Remove the stored passphrase for ``fingerprint``.

        Idempotent: deleting an entry that does not exist is a no-op,
        matching :meth:`things_cli.credentials.KeyringStore.clear`.
        """
        username = _normalise_fingerprint(fingerprint)
        try:
            keyring.delete_password(self._service, username)
        except _KeyringBackendError:
            # No existing entry — treat as already cleared, just like
            # ``things_cli.credentials._delete_quietly``.
            pass
        except Exception:
            # Some backends raise PasswordDeleteError, which subclasses
            # Exception but not KeyringError. Best-effort delete.
            pass
        self._update_index(remove=username)

    # ----- internals ---------------------------------------------------------

    def _update_index(self, *, add: str | None = None, remove: str | None = None) -> None:
        try:
            raw = keyring.get_password(self._service, _INDEX_USERNAME) or ""
        except _KeyringBackendError as exc:
            raise PassphraseStoreError(f"Keyring backend failed: {exc}") from exc
        current = {line.strip() for line in raw.splitlines() if line.strip()}
        if add is not None:
            current.add(add)
        if remove is not None:
            current.discard(remove)
        new_value = "\n".join(sorted(current))
        try:
            if new_value:
                keyring.set_password(self._service, _INDEX_USERNAME, new_value)
            else:
                # Empty index: drop the sentinel entry so an inspector
                # doesn't see a stale empty record.
                try:
                    keyring.delete_password(self._service, _INDEX_USERNAME)
                except _KeyringBackendError:
                    pass
                except Exception:
                    pass
        except _KeyringBackendError as exc:
            raise PassphraseStoreError(f"Keyring backend failed: {exc}") from exc


__all__ = ["KeyringPassphraseStore", "SERVICE_NAME"]
