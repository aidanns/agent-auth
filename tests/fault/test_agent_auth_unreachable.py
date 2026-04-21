# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: agent-auth unreachable from things-bridge.

If things-bridge cannot reach agent-auth (server down, network
partition, wrong URL) the authz client must raise
``AuthzUnavailableError`` rather than any raw socket error — the
bridge handler translates that specific exception into a 503
response.
"""

import pytest

from things_bridge.authz import AgentAuthClient
from things_bridge.errors import AuthzUnavailableError


def test_connection_refused_raises_unavailable() -> None:
    """Pointing the client at a dead port surfaces AuthzUnavailableError.

    Port 1 is reserved and should never answer; connect returns
    ECONNREFUSED which the client must wrap.
    """
    client = AgentAuthClient("http://127.0.0.1:1", timeout_seconds=1.0)
    with pytest.raises(AuthzUnavailableError, match="unreachable"):
        client.validate("aa_test_sig", "things:read")


def test_connect_timeout_raises_unavailable() -> None:
    """A timeout on connect also surfaces as AuthzUnavailableError.

    192.0.2.0/24 is the TEST-NET-1 block reserved for documentation —
    nothing should answer, and the connect call either times out or
    returns ENETUNREACH. Either way the authz layer's job is to wrap
    it as ``AuthzUnavailableError``.
    """
    client = AgentAuthClient("http://192.0.2.1:80", timeout_seconds=0.5)
    with pytest.raises(AuthzUnavailableError):
        client.validate("aa_test_sig", "things:read")
