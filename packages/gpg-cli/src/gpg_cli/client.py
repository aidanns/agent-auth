# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP client that talks to gpg-bridge."""

from __future__ import annotations

import json
import ssl
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlparse

from gpg_cli.errors import (
    BridgeBadSignatureError,
    BridgeForbiddenError,
    BridgeNotFoundError,
    BridgeRateLimitedError,
    BridgeSigningBackendUnavailableError,
    BridgeUnauthorizedError,
    BridgeUnavailableError,
)
from gpg_models.models import SignRequest, SignResult, VerifyRequest, VerifyResult


class BridgeClient:
    """Client for ``/gpg-bridge/v1/{sign,verify}`` endpoints."""

    def __init__(
        self,
        bridge_url: str,
        token: str,
        *,
        timeout_seconds: float = 30.0,
        ca_cert_path: str = "",
    ):
        parsed = urlparse(bridge_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"Invalid bridge_url: {bridge_url!r}")
        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._use_tls = parsed.scheme == "https"
        self._token = token
        self._timeout = timeout_seconds
        if self._use_tls:
            if ca_cert_path:
                self._ssl_context: ssl.SSLContext | None = ssl.create_default_context(
                    cafile=ca_cert_path
                )
            else:
                self._ssl_context = ssl.create_default_context()
        else:
            self._ssl_context = None

    def sign(self, request: SignRequest) -> SignResult:
        data = self._post("/gpg-bridge/v1/sign", request.to_json())
        return SignResult.from_json(data)

    def verify(self, request: VerifyRequest) -> VerifyResult:
        data = self._post("/gpg-bridge/v1/verify", request.to_json())
        return VerifyResult.from_json(data)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        if self._use_tls:
            conn: HTTPConnection = HTTPSConnection(
                self._host, self._port, timeout=self._timeout, context=self._ssl_context
            )
        else:
            conn = HTTPConnection(self._host, self._port, timeout=self._timeout)
        try:
            try:
                conn.request(
                    "POST",
                    path,
                    body=body,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),
                    },
                )
                response = conn.getresponse()
                raw = response.read()
                retry_after_header = response.getheader("Retry-After") or ""
            except (ConnectionError, TimeoutError, OSError) as exc:
                raise BridgeUnavailableError(f"gpg-bridge unreachable: {exc}") from exc
        finally:
            conn.close()

        try:
            data: dict[str, Any] = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise BridgeUnavailableError(
                f"gpg-bridge returned non-JSON response (status {response.status})"
            ) from exc

        if 200 <= response.status < 300:
            return data

        error_code = str(data.get("error") or "")
        error_detail = str(data.get("detail") or "")
        if response.status == 401:
            raise BridgeUnauthorizedError(error_code or "unauthorized")
        if response.status == 403:
            raise BridgeForbiddenError(error_code or "forbidden")
        if response.status == 404:
            raise BridgeNotFoundError(error_code or "not_found")
        if response.status == 400 and error_code == "bad_signature":
            raise BridgeBadSignatureError(error_code)
        if response.status == 503 and error_code == "signing_backend_unavailable":
            raise BridgeSigningBackendUnavailableError(
                error_detail or "signing backend is unavailable"
            )
        if response.status == 429:
            try:
                retry_after = max(1, int(retry_after_header)) if retry_after_header else 1
            except ValueError:
                retry_after = 1
            raise BridgeRateLimitedError(
                error_code or "rate_limited", retry_after_seconds=retry_after
            )
        raise BridgeUnavailableError(
            f"unexpected gpg-bridge response {response.status}: {error_code or '<no body>'}"
        )


__all__ = ["BridgeClient"]
