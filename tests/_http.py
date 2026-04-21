# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Minimal urllib-based HTTP helpers shared across the test suite."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def get(url: str, headers: dict[str, str] | None = None) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get_text(url: str, headers: dict[str, str] | None = None) -> tuple[int, str, str]:
    """GET a text/plain endpoint; return (status, content_type, body)."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        resp = urllib.request.urlopen(req)
        return (
            resp.status,
            resp.headers.get("Content-Type", ""),
            resp.read().decode("utf-8"),
        )
    except urllib.error.HTTPError as e:
        return (
            e.code,
            e.headers.get("Content-Type", "") if e.headers else "",
            e.read().decode("utf-8"),
        )


def post(
    url: str,
    data: dict[str, Any] | None = None,
    raw: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    body = raw if raw is not None else json.dumps(data or {}).encode("utf-8")
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=req_headers)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
