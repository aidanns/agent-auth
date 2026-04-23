# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP client for out-of-process approval notifier.

agent-auth holds the signing and encryption keys. Loading arbitrary
third-party Python code (the pre-#6 ``importlib.import_module``
pattern) inside the same process widened the trust boundary to
include every plugin author. This module replaces that with an HTTP
client: the notifier is an independent process with its own
identity, can be written in any language, and is free to shell out
or block for interactive input without wrestling agent-auth's
thread model.

Fail-closed semantics: every request-side failure (timeout, connect
error, non-2xx response, malformed JSON, invalid shape) is treated
as a deny with no grant. A broken or unreachable notifier cannot
silently approve.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, cast

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApprovalResult:
    """Outcome of a JIT approval request.

    ``grant_type`` is ``"once"`` (no caching; this request only) or
    ``"timed"`` (cached for ``duration_minutes`` against the
    ``(family_id, scope)`` pair). A ``"timed"`` result with no
    duration is treated as ``"once"`` by ``ApprovalManager`` — the
    notifier must supply ``duration_minutes`` for timed grants to
    take effect.
    """

    approved: bool
    grant_type: str = "once"
    duration_minutes: int | None = None


_GRANT_TYPES = frozenset({"once", "timed"})


def _parse_response_body(body: bytes) -> ApprovalResult:
    """Parse the notifier's JSON response body into an ApprovalResult.

    Raises ``ValueError`` on any shape violation. Callers convert
    that into a deny under the fail-closed policy.
    """
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("notifier response is not a JSON object")
    data: dict[str, Any] = cast(dict[str, Any], parsed)
    approved = data.get("approved")
    if not isinstance(approved, bool):
        raise ValueError("notifier response missing boolean 'approved'")
    grant_type = data.get("grant_type", "once")
    if grant_type not in _GRANT_TYPES:
        raise ValueError(f"notifier response 'grant_type' must be one of {sorted(_GRANT_TYPES)}")
    duration = data.get("duration_minutes")
    if duration is not None and not isinstance(duration, int):
        raise ValueError("notifier response 'duration_minutes' must be an integer when set")
    return ApprovalResult(
        approved=approved,
        grant_type=grant_type,
        duration_minutes=duration,
    )


class ApprovalClient:
    """POST a JIT approval request to the configured notifier URL.

    Constructed once per server process and shared across request
    threads. ``request_approval`` is thread-safe because
    ``urllib.request`` per-call sockets are not shared.
    """

    def __init__(self, url: str, timeout_seconds: float = 30.0):
        self._url = url
        self._timeout = timeout_seconds

    @property
    def configured(self) -> bool:
        """``True`` iff a notifier URL was provided in config.

        ``ApprovalManager`` fails closed on prompt-tier scopes when
        this is ``False`` — silently approving would re-introduce the
        trust-boundary hole #6 is closing.
        """
        return bool(self._url)

    def request_approval(
        self,
        family_id: str,
        scope: str,
        description: str | None,
    ) -> ApprovalResult:
        if not self._url:
            _LOGGER.warning(
                "notification_plugin_url is empty; denying prompt-tier request for scope=%s",
                scope,
            )
            return ApprovalResult(approved=False)

        payload = json.dumps(
            {"family_id": family_id, "scope": scope, "description": description}
        ).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status < 200 or resp.status >= 300:
                    _LOGGER.warning(
                        "notifier at %s returned non-2xx status=%d; denying",
                        self._url,
                        resp.status,
                    )
                    return ApprovalResult(approved=False)
                body = resp.read()
        except urllib.error.HTTPError as exc:
            _LOGGER.warning(
                "notifier at %s returned HTTPError status=%d; denying", self._url, exc.code
            )
            return ApprovalResult(approved=False)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _LOGGER.warning("notifier at %s unreachable (%s); denying", self._url, exc)
            return ApprovalResult(approved=False)

        try:
            return _parse_response_body(body)
        except (ValueError, json.JSONDecodeError) as exc:
            _LOGGER.warning(
                "notifier at %s returned malformed response (%s); denying", self._url, exc
            )
            return ApprovalResult(approved=False)
