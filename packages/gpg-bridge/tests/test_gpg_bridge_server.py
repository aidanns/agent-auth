# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the gpg-bridge HTTP server."""

from __future__ import annotations

import base64
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import yaml

from gpg_bridge.authz import AgentAuthClient
from gpg_bridge.config import Config
from gpg_bridge.errors import (
    AuthzRateLimitedError,
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
)
from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_bridge.metrics import build_registry
from gpg_bridge.server import GpgBridgeServer

FIXTURE = {
    "keys": [
        {
            "fingerprint": "D7A2B4C0E8F11234567890ABCDEF1234567890AB",
            "user_ids": ["Test Key <test@example.invalid>"],
            "aliases": ["0xCDEF1234567890AB", "test@example.invalid"],
        }
    ],
}


class FakeAuthz(AgentAuthClient):
    def __init__(self, *, raise_on_validate: Exception | None = None):
        super().__init__("http://test-fake")
        self.raise_on_validate = raise_on_validate
        self.last_token: str | None = None
        self.last_scope: str | None = None
        self.last_description: str | None = None

    def validate(self, token: str, required_scope: str, *, description: str | None = None) -> None:
        self.last_token = token
        self.last_scope = required_scope
        self.last_description = description
        if self.raise_on_validate is not None:
            raise self.raise_on_validate


class _ServerHandle:
    def __init__(self, server: GpgBridgeServer, thread: threading.Thread, port: int):
        self.server = server
        self.thread = thread
        self.port = port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5.0)


@pytest.fixture
def fixture_path(tmp_path: Path) -> str:
    path = tmp_path / "fixture.yaml"
    path.write_text(yaml.safe_dump(FIXTURE))
    return str(path)


@pytest.fixture
def gpg_client(fixture_path: str) -> GpgSubprocessClient:
    return GpgSubprocessClient(
        command=[sys.executable, "-m", "gpg_backend_fake", "--fixtures", fixture_path],
        timeout_seconds=15.0,
    )


def _start_server(
    config: Config, gpg_client: GpgSubprocessClient, authz: FakeAuthz
) -> _ServerHandle:
    registry, metrics = build_registry()
    server = GpgBridgeServer(config, gpg_client, authz, registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return _ServerHandle(server, thread, port)


def _post_json(
    url: str, body: dict[str, Any], token: str | None = "valid-token"
) -> tuple[int, dict[str, Any], dict[str, str]]:
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            status = response.status
            resp_headers = dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
        resp_headers = dict(exc.headers)
    return status, json.loads(raw) if raw else {}, resp_headers


def _get(url: str, token: str | None = "valid-token") -> tuple[int, dict[str, Any]]:
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    return status, json.loads(raw) if raw else {}


class TestSignEndpoint:
    @pytest.mark.covers_function("Serve GPG Bridge HTTP API")
    def test_sign_happy_path(self, gpg_client: GpgSubprocessClient, tmp_path: Path) -> None:
        authz = FakeAuthz()
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body, _ = _post_json(
                f"{handle.base_url}/gpg-bridge/v1/sign",
                {
                    "local_user": "test@example.invalid",
                    "payload_b64": base64.b64encode(b"commit").decode("ascii"),
                    "armor": True,
                },
            )
            assert status == 200
            assert body["exit_code"] == 0
            signature = base64.b64decode(body["signature_b64"])
            assert signature.startswith(b"-----BEGIN PGP SIGNATURE-----")
            assert authz.last_scope == "gpg:sign"
            assert "test@example.invalid" in (authz.last_description or "")
        finally:
            handle.close()

    @pytest.mark.covers_function("Serve GPG Bridge HTTP API")
    def test_sign_rejects_payload_too_large(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz()
        config = Config(port=0, max_request_bytes=128)
        handle = _start_server(config, gpg_client, authz)
        try:
            big = base64.b64encode(b"x" * 512).decode("ascii")
            status, body, _ = _post_json(
                f"{handle.base_url}/gpg-bridge/v1/sign",
                {"local_user": "k", "payload_b64": big},
            )
            assert status == 413
            assert body["error"] == "payload_too_large"
        finally:
            handle.close()

    @pytest.mark.covers_function("Authorize Sign Request")
    def test_sign_unknown_scope_returns_403(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz(raise_on_validate=AuthzScopeDeniedError("scope_denied"))
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body, _ = _post_json(
                f"{handle.base_url}/gpg-bridge/v1/sign",
                {
                    "local_user": "test@example.invalid",
                    "payload_b64": base64.b64encode(b"x").decode("ascii"),
                },
            )
            assert status == 403
            assert body["error"] == "scope_denied"
        finally:
            handle.close()

    @pytest.mark.covers_function("Authorize Sign Request")
    def test_sign_expired_token_returns_401(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz(raise_on_validate=AuthzTokenExpiredError("token_expired"))
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body, _ = _post_json(
                f"{handle.base_url}/gpg-bridge/v1/sign",
                {
                    "local_user": "test@example.invalid",
                    "payload_b64": base64.b64encode(b"x").decode("ascii"),
                },
            )
            assert status == 401
            assert body["error"] == "token_expired"
        finally:
            handle.close()

    @pytest.mark.covers_function("Authorize Sign Request")
    def test_sign_rate_limit_propagates_retry_after(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz(
            raise_on_validate=AuthzRateLimitedError("rate_limited", retry_after_seconds=11)
        )
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body, headers = _post_json(
                f"{handle.base_url}/gpg-bridge/v1/sign",
                {
                    "local_user": "test@example.invalid",
                    "payload_b64": base64.b64encode(b"x").decode("ascii"),
                },
            )
            assert status == 429
            assert body["error"] == "rate_limited"
            assert headers.get("Retry-After") == "11"
        finally:
            handle.close()

    @pytest.mark.covers_function("Authorize Sign Request")
    def test_sign_authz_unavailable_returns_502(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz(raise_on_validate=AuthzUnavailableError("unreachable"))
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body, _ = _post_json(
                f"{handle.base_url}/gpg-bridge/v1/sign",
                {
                    "local_user": "test@example.invalid",
                    "payload_b64": base64.b64encode(b"x").decode("ascii"),
                },
            )
            assert status == 502
            assert body["error"] == "authz_unavailable"
        finally:
            handle.close()

    @pytest.mark.covers_function("Authorize Sign Request")
    def test_sign_missing_bearer_returns_401(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz()
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body, _ = _post_json(
                f"{handle.base_url}/gpg-bridge/v1/sign",
                {
                    "local_user": "test@example.invalid",
                    "payload_b64": base64.b64encode(b"x").decode("ascii"),
                },
                token=None,
            )
            assert status == 401
            assert body["error"] == "unauthorized"
        finally:
            handle.close()

    @pytest.mark.covers_function("Apply Per-Key Allowlist")
    def test_sign_key_not_allowed_when_allowlist_rejects(
        self, gpg_client: GpgSubprocessClient
    ) -> None:
        authz = FakeAuthz()
        config = Config(port=0, allowed_signing_keys=["0000000000000000"])
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body, _ = _post_json(
                f"{handle.base_url}/gpg-bridge/v1/sign",
                {
                    "local_user": "test@example.invalid",
                    "payload_b64": base64.b64encode(b"x").decode("ascii"),
                },
            )
            assert status == 403
            assert body["error"] == "key_not_allowed"
        finally:
            handle.close()

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_sign_with_wrong_stored_passphrase_returns_signing_backend_unavailable(
        self, tmp_path: Path
    ) -> None:
        """Per ADR 0042: a wrong stored passphrase surfaces as 503 ``signing_backend_unavailable``.

        Drives a fixture that requires a passphrase, plumbs the wrong
        passphrase into the bridge via an in-memory keyring, and
        confirms the gpg-stderr-pattern classifier maps "Bad
        passphrase" onto the existing ``signing_backend_unavailable``
        wire discriminator (reused from issue #331 / PR #339).
        """
        from unittest.mock import patch

        from gpg_bridge.passphrase_store import KeyringPassphraseStore

        # Fixture with passphrase_required != stored.
        fp = "D7A2B4C0E8F11234567890ABCDEF1234567890AB"
        fixture = {
            "keys": [
                {
                    "fingerprint": fp,
                    "user_ids": ["Test Key <test@example.invalid>"],
                    "aliases": ["test@example.invalid"],
                }
            ],
            "behaviours": {"passphrase_required": "actually-this"},
        }
        path = tmp_path / "fx.yaml"
        path.write_text(yaml.safe_dump(fixture))

        backing: dict[tuple[str, str], str] = {}
        with (
            patch(
                "gpg_bridge.passphrase_store.keyring.get_password",
                side_effect=lambda s, u: backing.get((s, u)),
            ),
            patch(
                "gpg_bridge.passphrase_store.keyring.set_password",
                side_effect=lambda s, u, p: backing.update({(s, u): p}),
            ),
            patch(
                "gpg_bridge.passphrase_store.keyring.delete_password",
                side_effect=lambda s, u: backing.pop((s, u), None),
            ),
        ):
            store = KeyringPassphraseStore()
            store.set(fp, "but-store-has-this")
            client = GpgSubprocessClient(
                command=[sys.executable, "-m", "gpg_backend_fake", "--fixtures", str(path)],
                timeout_seconds=15.0,
                passphrase_store=store,
            )
            authz = FakeAuthz()
            config = Config(port=0)
            handle = _start_server(config, client, authz)
            try:
                status, body, _ = _post_json(
                    f"{handle.base_url}/gpg-bridge/v1/sign",
                    {
                        "local_user": "test@example.invalid",
                        "payload_b64": base64.b64encode(b"data").decode("ascii"),
                    },
                )
                assert status == 503
                assert body["error"] == "signing_backend_unavailable"
                # The bridge's response must not leak the stored passphrase.
                serialised = json.dumps(body)
                assert "but-store-has-this" not in serialised
            finally:
                handle.close()


class TestVerifyEndpoint:
    @pytest.mark.covers_function("Serve GPG Bridge HTTP API")
    def test_verify_happy_path(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz()
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            # Sign first, then verify the result.
            status, body, _ = _post_json(
                f"{handle.base_url}/gpg-bridge/v1/sign",
                {
                    "local_user": "test@example.invalid",
                    "payload_b64": base64.b64encode(b"data").decode("ascii"),
                    "armor": True,
                },
            )
            assert status == 200
            verify_body = {
                "signature_b64": body["signature_b64"],
                "payload_b64": base64.b64encode(b"data").decode("ascii"),
            }
            status, body, _ = _post_json(f"{handle.base_url}/gpg-bridge/v1/verify", verify_body)
            assert status == 200
            assert "GOODSIG" in body["status_text"]
        finally:
            handle.close()


class TestHealthEndpoint:
    @pytest.mark.covers_function("Serve GPG Bridge Health Endpoint")
    def test_health_ok_when_backend_resolvable(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz()
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body = _get(f"{handle.base_url}/gpg-bridge/health")
            assert status == 200
            assert body["status"] == "ok"
        finally:
            handle.close()

    @pytest.mark.covers_function("Serve GPG Bridge Health Endpoint")
    def test_health_unhealthy_when_gpg_missing(
        self, gpg_client: GpgSubprocessClient, tmp_path: Path
    ) -> None:
        authz = FakeAuthz()
        # Inject a config whose gpg_command points at a non-existent absolute path.
        config = Config(
            port=0,
            gpg_command=[str(tmp_path / "does-not-exist")],
        )
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body = _get(f"{handle.base_url}/gpg-bridge/health")
            assert status == 503
            assert body["status"] == "unhealthy"
        finally:
            handle.close()


class TestRejectsUnknownRoutes:
    @pytest.mark.covers_function("Serve GPG Bridge HTTP API")
    def test_unknown_post_returns_404(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz()
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body, _ = _post_json(f"{handle.base_url}/gpg-bridge/v1/nope", {})
            assert status == 404
            assert body["error"] == "not_found"
        finally:
            handle.close()

    @pytest.mark.covers_function("Serve GPG Bridge HTTP API")
    def test_unknown_get_returns_404(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz()
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            status, _ = _get(f"{handle.base_url}/gpg-bridge/v1/unknown")
            assert status == 404
        finally:
            handle.close()

    @pytest.mark.covers_function("Authorize Sign Request")
    def test_invalid_token_returns_401(self, gpg_client: GpgSubprocessClient) -> None:
        authz = FakeAuthz(raise_on_validate=AuthzTokenInvalidError("bad"))
        config = Config(port=0)
        handle = _start_server(config, gpg_client, authz)
        try:
            status, body, _ = _post_json(
                f"{handle.base_url}/gpg-bridge/v1/sign",
                {
                    "local_user": "test@example.invalid",
                    "payload_b64": base64.b64encode(b"x").decode("ascii"),
                },
            )
            assert status == 401
            assert body["error"] == "unauthorized"
        finally:
            handle.close()
