# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for :mod:`gpg_bridge.passphrase_store`.

Mirrors the in-memory keyring fixture pattern established in
``packages/things-cli/tests/test_things_cli_credentials.py`` so the
two stores are tested against the same backend abstraction.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from gpg_bridge.errors import PassphraseStoreError
from gpg_bridge.passphrase_store import KeyringPassphraseStore

_FP = "D7A2B4C0E8F11234567890ABCDEF1234567890AB"
_FP_OTHER = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


_KeyringDict = dict[tuple[str, str], str]


@pytest.fixture
def mock_keyring() -> object:
    """Patch the ``keyring`` module to use an in-memory dict."""
    store: _KeyringDict = {}

    def get_password(service: str, username: str) -> str | None:
        return store.get((service, username))

    def set_password(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def delete_password(service: str, username: str) -> None:
        if (service, username) in store:
            del store[(service, username)]
        else:
            from keyring.errors import PasswordDeleteError

            raise PasswordDeleteError("no such entry")

    with (
        patch("gpg_bridge.passphrase_store.keyring.get_password", side_effect=get_password),
        patch("gpg_bridge.passphrase_store.keyring.set_password", side_effect=set_password),
        patch(
            "gpg_bridge.passphrase_store.keyring.delete_password",
            side_effect=delete_password,
        ),
    ):
        yield store


class TestKeyringPassphraseStore:
    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_set_then_get_round_trip(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        store.set(_FP, "hunter2")
        assert store.get(_FP) == "hunter2"

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_get_missing_returns_none(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        assert store.get(_FP) is None

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_set_normalises_fingerprint(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        store.set("  0x" + _FP.lower() + "  ", "p")
        # ``get`` accepts equivalent forms — leading 0x, lowercase, padding.
        assert store.get(_FP) == "p"
        assert store.get("0x" + _FP) == "p"
        assert store.get(_FP.lower()) == "p"

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_set_rejects_empty_passphrase(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        with pytest.raises(ValueError):
            store.set(_FP, "")

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_set_rejects_empty_fingerprint(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        with pytest.raises(ValueError):
            store.set("   ", "p")

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_delete_then_get_returns_none(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        store.set(_FP, "p")
        store.delete(_FP)
        assert store.get(_FP) is None

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_delete_missing_is_idempotent(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        store.delete(_FP)  # no-op; must not raise
        store.delete(_FP)

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_list_fingerprints_returns_sorted_unique(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        store.set(_FP, "p1")
        store.set(_FP_OTHER, "p2")
        # Re-set the first entry to confirm the index doesn't dupe it.
        store.set(_FP, "p1-rotated")
        listed = store.list_fingerprints()
        assert listed == sorted({_FP, _FP_OTHER})

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_list_fingerprints_after_delete(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        store.set(_FP, "p1")
        store.set(_FP_OTHER, "p2")
        store.delete(_FP)
        assert store.list_fingerprints() == [_FP_OTHER]

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_list_fingerprints_empty_when_no_entries(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        assert store.list_fingerprints() == []

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_list_never_returns_passphrase(self, mock_keyring: _KeyringDict) -> None:
        store = KeyringPassphraseStore()
        store.set(_FP, "definitely-secret")
        listed = store.list_fingerprints()
        for entry in listed:
            assert "definitely-secret" not in entry

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_keyring_backend_error_wraps(self) -> None:
        from typing import Any

        from keyring.errors import KeyringError as _KeyringBackendError

        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise _KeyringBackendError("backend down")

        with patch("gpg_bridge.passphrase_store.keyring.get_password", side_effect=boom):
            store = KeyringPassphraseStore()
            with pytest.raises(PassphraseStoreError, match="backend down"):
                store.get(_FP)

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_set_backend_error_wraps(self) -> None:
        from typing import Any

        from keyring.errors import KeyringError as _KeyringBackendError

        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise _KeyringBackendError("backend down")

        # Override every method to raise so the index update path also
        # raises predictably.
        with (
            patch(
                "gpg_bridge.passphrase_store.keyring.set_password",
                side_effect=boom,
            ),
            patch(
                "gpg_bridge.passphrase_store.keyring.get_password",
                return_value=None,
            ),
        ):
            store = KeyringPassphraseStore()
            with pytest.raises(PassphraseStoreError, match="backend down"):
                store.set(_FP, "p")
