# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for :mod:`gpg_models.models` round-trips and validation."""

from __future__ import annotations

import base64

import pytest

from gpg_models.models import (
    SignRequest,
    SignResult,
    VerifyRequest,
    VerifyResult,
    validate_keyid_format,
)


class TestValidateKeyidFormat:
    def test_accepts_known_formats(self) -> None:
        for value in ("none", "short", "0xshort", "long", "0xlong"):
            assert validate_keyid_format(value) == value

    def test_rejects_unknown(self) -> None:
        with pytest.raises(ValueError, match="Invalid keyid_format"):
            validate_keyid_format("hex")


class TestSignRequest:
    def test_from_json_round_trips(self) -> None:
        original = SignRequest(
            local_user="0xABCD", payload=b"hello", armor=True, keyid_format="long"
        )
        reparsed = SignRequest.from_json(original.to_json())
        assert reparsed == original

    def test_from_json_requires_local_user(self) -> None:
        body = {"payload_b64": base64.b64encode(b"x").decode("ascii")}
        with pytest.raises(ValueError, match="local_user"):
            SignRequest.from_json(body)

    def test_from_json_requires_payload(self) -> None:
        with pytest.raises(ValueError, match="payload_b64"):
            SignRequest.from_json({"local_user": "k"})

    def test_from_json_rejects_bad_keyid_format(self) -> None:
        body = {
            "local_user": "k",
            "payload_b64": base64.b64encode(b"x").decode("ascii"),
            "keyid_format": "hex",
        }
        with pytest.raises(ValueError, match="Invalid keyid_format"):
            SignRequest.from_json(body)


class TestSignResult:
    def test_round_trips_with_fingerprint(self) -> None:
        original = SignResult(
            signature=b"-----SIG-----",
            status_text="[GNUPG:] SIG_CREATED ...",
            exit_code=0,
            resolved_key_fingerprint="00112233" + "44556677",
        )
        reparsed = SignResult.from_json(original.to_json())
        assert reparsed == original

    def test_omits_empty_fingerprint(self) -> None:
        body = SignResult(signature=b"x", status_text="", exit_code=0).to_json()
        assert "resolved_key_fingerprint" not in body


class TestVerifyRoundTrip:
    def test_request_round_trips(self) -> None:
        original = VerifyRequest(signature=b"sig", payload=b"data", keyid_format="short")
        reparsed = VerifyRequest.from_json(original.to_json())
        assert reparsed == original

    def test_result_round_trips(self) -> None:
        original = VerifyResult(status_text="[GNUPG:] GOODSIG ABC", exit_code=0)
        reparsed = VerifyResult.from_json(original.to_json())
        assert reparsed == original
