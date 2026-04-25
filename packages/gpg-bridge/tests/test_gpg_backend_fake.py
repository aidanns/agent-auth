# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the in-tree backend fake."""

from __future__ import annotations

import hashlib

import pytest
import yaml
from gpg_backend_fake.store import FakeBackendStore, load_fixture

from gpg_models.errors import (
    GpgBadSignatureError,
    GpgNoSuchKeyError,
    GpgPermissionError,
)
from gpg_models.models import SignRequest, VerifyRequest

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


def _store() -> FakeBackendStore:
    return load_fixture(FIXTURE)


class TestFakeSign:
    def test_sign_round_trips_to_verify(self) -> None:
        store = _store()
        payload = b"commit payload"
        sign_result = store.sign(
            SignRequest(local_user="test@example.invalid", payload=payload, armor=True)
        )
        assert sign_result.resolved_key_fingerprint == "D7A2B4C0E8F11234567890ABCDEF1234567890AB"
        assert sign_result.signature.startswith(b"-----BEGIN PGP SIGNATURE-----")
        assert "[GNUPG:] SIG_CREATED" in sign_result.status_text

        verify_result = store.verify(
            VerifyRequest(signature=sign_result.signature, payload=payload)
        )
        assert verify_result.exit_code == 0
        assert "[GNUPG:] GOODSIG" in verify_result.status_text

    def test_sign_resolves_alias(self) -> None:
        store = _store()
        result = store.sign(SignRequest(local_user="0xCDEF1234567890AB", payload=b"x", armor=True))
        assert result.resolved_key_fingerprint == "D7A2B4C0E8F11234567890ABCDEF1234567890AB"

    def test_sign_unknown_key_raises(self) -> None:
        store = _store()
        with pytest.raises(GpgNoSuchKeyError):
            store.sign(SignRequest(local_user="unknown@invalid", payload=b"x"))

    def test_sign_permission_denied_when_fixture_says_so(self) -> None:
        store = load_fixture({**FIXTURE, "behaviours": {"permission_denied": True}})
        with pytest.raises(GpgPermissionError):
            store.sign(SignRequest(local_user="test@example.invalid", payload=b"x"))


class TestFakeVerify:
    def test_verify_rejects_corrupted_signature(self) -> None:
        store = _store()
        sign_result = store.sign(
            SignRequest(local_user="test@example.invalid", payload=b"data", armor=True)
        )
        bad = sign_result.signature.replace(b"FAKE-FP:", b"FAKE-XX:")
        with pytest.raises(GpgBadSignatureError):
            store.verify(VerifyRequest(signature=bad, payload=b"data"))

    def test_verify_rejects_payload_tampering(self) -> None:
        store = _store()
        sign_result = store.sign(
            SignRequest(local_user="test@example.invalid", payload=b"data", armor=True)
        )
        with pytest.raises(GpgBadSignatureError):
            store.verify(VerifyRequest(signature=sign_result.signature, payload=b"different"))

    def test_verify_forced_bad_via_behaviour(self) -> None:
        store = load_fixture({**FIXTURE, "behaviours": {"corrupt_verify": True}})
        # Even a well-formed signature fails.
        sign_result = _store().sign(
            SignRequest(local_user="test@example.invalid", payload=b"data", armor=True)
        )
        with pytest.raises(GpgBadSignatureError):
            store.verify(VerifyRequest(signature=sign_result.signature, payload=b"data"))


class TestFixtureParsing:
    def test_rejects_non_mapping(self) -> None:
        with pytest.raises(Exception, match="mapping"):
            load_fixture([])

    def test_missing_fingerprint(self) -> None:
        with pytest.raises(Exception, match="fingerprint"):
            load_fixture({"keys": [{}]})

    def test_yaml_dump_round_trips(self, tmp_path) -> None:
        path = tmp_path / "fixture.yaml"
        path.write_text(yaml.safe_dump(FIXTURE))
        raw = yaml.safe_load(path.read_text())
        store = load_fixture(raw)
        result = store.sign(
            SignRequest(local_user="test@example.invalid", payload=b"x", armor=True)
        )
        # Derived digest inside the synthetic sig is stable.
        digest = hashlib.sha256(b"x").hexdigest().upper()
        assert f"PAYLOAD-HASH:{digest}".encode("ascii") in result.signature
