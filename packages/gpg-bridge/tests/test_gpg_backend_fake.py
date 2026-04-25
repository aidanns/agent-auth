# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the in-tree ``gpg``-substitute fake."""

from __future__ import annotations

import hashlib

import pytest
import yaml
from gpg_backend_fake.store import (
    BadSignatureError,
    FakeKeyring,
    NoSuchKeyError,
    PermissionDeniedError,
    load_fixture,
)

FIXTURE = {
    "keys": [
        {
            "fingerprint": "D7A2B4C0E8F11234567890ABCDEF1234567890AB",
            "user_ids": ["Test Key <test@example.invalid>"],
            "aliases": ["0xCDEF1234567890AB", "test@example.invalid"],
        }
    ],
    "behaviours": {},
}


def _store() -> FakeKeyring:
    return load_fixture(FIXTURE)


class TestFakeSign:
    @pytest.mark.covers_function("Sign Payload")
    @pytest.mark.covers_function("Verify Signature")
    def test_sign_round_trips_to_verify(self) -> None:
        store = _store()
        payload = b"commit payload"
        signature, status_text = store.sign(
            local_user="test@example.invalid", payload=payload, armor=True
        )
        assert signature.startswith(b"-----BEGIN PGP SIGNATURE-----")
        assert "[GNUPG:] SIG_CREATED" in status_text

        verify_text = store.verify(signature=signature, payload=payload)
        assert "[GNUPG:] GOODSIG" in verify_text

    def test_sign_resolves_alias(self) -> None:
        store = _store()
        signature, _ = store.sign(local_user="0xCDEF1234567890AB", payload=b"x", armor=True)
        # Synthetic signature carries the resolved fingerprint.
        assert b"FAKE-FP:D7A2B4C0E8F11234567890ABCDEF1234567890AB" in signature

    def test_sign_unknown_key_raises(self) -> None:
        store = _store()
        with pytest.raises(NoSuchKeyError):
            store.sign(local_user="unknown@invalid", payload=b"x", armor=False)

    def test_sign_permission_denied_when_fixture_says_so(self) -> None:
        store = load_fixture({**FIXTURE, "behaviours": {"permission_denied": True}})
        with pytest.raises(PermissionDeniedError):
            store.sign(local_user="test@example.invalid", payload=b"x", armor=False)


class TestFakeVerify:
    def test_verify_rejects_corrupted_signature(self) -> None:
        store = _store()
        signature, _ = store.sign(local_user="test@example.invalid", payload=b"data", armor=True)
        bad = signature.replace(b"FAKE-FP:", b"FAKE-XX:")
        with pytest.raises(BadSignatureError):
            store.verify(signature=bad, payload=b"data")

    def test_verify_rejects_payload_tampering(self) -> None:
        store = _store()
        signature, _ = store.sign(local_user="test@example.invalid", payload=b"data", armor=True)
        with pytest.raises(BadSignatureError):
            store.verify(signature=signature, payload=b"different")

    def test_verify_forced_bad_via_behaviour(self) -> None:
        store = load_fixture({**FIXTURE, "behaviours": {"corrupt_verify": True}})
        # Even a well-formed signature fails.
        signature, _ = _store().sign(local_user="test@example.invalid", payload=b"data", armor=True)
        with pytest.raises(BadSignatureError):
            store.verify(signature=signature, payload=b"data")


class TestFixtureParsing:
    def test_rejects_non_mapping(self) -> None:
        with pytest.raises(ValueError, match="mapping"):
            load_fixture([])

    def test_missing_fingerprint(self) -> None:
        with pytest.raises(ValueError, match="fingerprint"):
            load_fixture({"keys": [{}]})

    def test_yaml_dump_round_trips(self, tmp_path) -> None:
        path = tmp_path / "fixture.yaml"
        path.write_text(yaml.safe_dump(FIXTURE))
        raw = yaml.safe_load(path.read_text())
        store = load_fixture(raw)
        signature, _ = store.sign(local_user="test@example.invalid", payload=b"x", armor=True)
        # Derived digest inside the synthetic sig is stable.
        digest = hashlib.sha256(b"x").hexdigest().upper()
        assert f"PAYLOAD-HASH:{digest}".encode("ascii") in signature
