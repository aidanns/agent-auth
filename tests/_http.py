"""Minimal urllib-based HTTP helpers shared across the test suite."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def get(url: str, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def post(
    url: str,
    data: dict | None = None,
    raw: bytes | None = None,
) -> tuple[int, dict]:
    body = raw if raw is not None else json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
