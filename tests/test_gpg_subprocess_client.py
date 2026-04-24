# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration-style tests of the bridge's subprocess contract against the fake."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_models.errors import (
    GpgBadSignatureError,
    GpgError,
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
}


@pytest.fixture
def fixture_path(tmp_path: Path) -> str:
    path = tmp_path / "fixture.yaml"
    path.write_text(yaml.safe_dump(FIXTURE))
    return str(path)


@pytest.fixture
def client(fixture_path: str) -> GpgSubprocessClient:
    return GpgSubprocessClient(
        command=[sys.executable, "-m", "tests.gpg_backend_fake", "--fixtures", fixture_path],
        timeout_seconds=15.0,
    )


class TestSignRoundTrip:
    def test_sign_and_verify(self, client: GpgSubprocessClient) -> None:
        sign = client.sign(
            SignRequest(
                local_user="test@example.invalid",
                payload=b"commit content",
                armor=True,
            )
        )
        assert sign.signature.startswith(b"-----BEGIN PGP SIGNATURE-----")
        assert "[GNUPG:] SIG_CREATED" in sign.status_text
        assert sign.resolved_key_fingerprint.startswith("D7A2B4C0")
        verify = client.verify(VerifyRequest(signature=sign.signature, payload=b"commit content"))
        assert verify.exit_code == 0
        assert "[GNUPG:] GOODSIG" in verify.status_text

    def test_unknown_key_maps_to_gpg_no_such_key(self, client: GpgSubprocessClient) -> None:
        with pytest.raises(GpgNoSuchKeyError):
            client.sign(SignRequest(local_user="unknown@example.invalid", payload=b"x"))

    def test_bad_signature_bytes_raise_bad_signature(self, client: GpgSubprocessClient) -> None:
        signed = client.sign(
            SignRequest(local_user="test@example.invalid", payload=b"x", armor=True)
        )
        bad = signed.signature.replace(b"FAKE-FP:", b"FAKE-XX:")
        with pytest.raises(GpgBadSignatureError):
            client.verify(VerifyRequest(signature=bad, payload=b"x"))


class TestSubprocessContractFailures:
    def test_missing_binary_raises_gpg_error(self, tmp_path: Path) -> None:
        client = GpgSubprocessClient(
            command=[str(tmp_path / "does-not-exist")], timeout_seconds=2.0
        )
        with pytest.raises(GpgError):
            client.sign(SignRequest(local_user="k", payload=b"x"))

    def test_permission_denied_fixture_maps_cleanly(self, tmp_path: Path) -> None:
        fx = tmp_path / "fx.yaml"
        fx.write_text(yaml.safe_dump({**FIXTURE, "behaviours": {"permission_denied": True}}))
        client = GpgSubprocessClient(
            command=[sys.executable, "-m", "tests.gpg_backend_fake", "--fixtures", str(fx)],
            timeout_seconds=15.0,
        )
        with pytest.raises(GpgPermissionError):
            client.sign(SignRequest(local_user="test@example.invalid", payload=b"x"))

    def test_rejects_empty_command(self) -> None:
        with pytest.raises(ValueError):
            GpgSubprocessClient(command=[])
