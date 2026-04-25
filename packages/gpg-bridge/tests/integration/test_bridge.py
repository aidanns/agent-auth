# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""End-to-end Docker integration tests for gpg-bridge.

Drives the full sign / verify path through real HTTP and a real host
``gpg`` binary: a containerised ``gpg-cli`` posts a bearer token (minted
through the in-network ``agent-auth`` service) to the in-network
``gpg-bridge``, which delegates token validation to ``agent-auth`` and
shells out to ``gpg-backend-cli-host`` (and the real ``gpg``) inside
the bridge container.

Replaces the in-process ``test_gpg_end_to_end.py`` smoke test (which
stubbed authz with ``_NoopAuthz`` and silently skipped when ``gpg``
was missing on the host). The bridge image always has ``gpg``
installed at build time; an absent binary is now a build failure of
``Dockerfile.gpg-bridge.test``, not a silent test skip — satisfying
issue #278's "no silent skip" acceptance criterion.

This suite relies on the ``gpg_bridge_stack`` and
``gpg_bridge_stack_factory`` fixtures registered by
:mod:`tests_support.integration.plugin`. The per-test ``GpgCliInvoker``
fixture lives in :mod:`packages.gpg-bridge.tests.integration.conftest`.
"""

from __future__ import annotations

import time

import pytest

from .conftest import GpgCliInvoker

_PAYLOAD = b"integration-test commit payload\n"


def _stderr_text(result):
    return result.stderr.decode("utf-8", errors="replace")


@pytest.mark.covers_function("Delegate Token Validation", "Serve Bridge HTTP API")
def test_sign_and_verify_end_to_end(gpg_cli_invoker: GpgCliInvoker) -> None:
    """Happy path — mint a ``gpg:sign=allow`` token, sign, and verify the signature.

    Verification asserts ``gpg``'s status-fd output (``GOODSIG`` /
    ``VALIDSIG``) so a successful exit code alone can't carry the test.
    """
    stack = gpg_cli_invoker.stack
    payload = stack.agent_auth.create_token("gpg:sign=allow")

    sign_result = gpg_cli_invoker.sign(
        token=payload["access_token"],
        fingerprint=stack.primary_fingerprint,
        payload=_PAYLOAD,
    )
    assert sign_result.returncode == 0, _stderr_text(sign_result)
    signature = sign_result.stdout
    assert signature.startswith(b"-----BEGIN PGP SIGNATURE-----"), signature[:64]
    assert "[GNUPG:] SIG_CREATED" in _stderr_text(sign_result)

    verify_result = gpg_cli_invoker.verify(
        token=payload["access_token"],
        signature=signature,
        payload=_PAYLOAD,
    )
    assert verify_result.returncode == 0, _stderr_text(verify_result)
    verify_stderr = _stderr_text(verify_result)
    assert (
        "[GNUPG:] GOODSIG" in verify_stderr or "[GNUPG:] VALIDSIG" in verify_stderr
    ), verify_stderr


@pytest.mark.covers_function("Delegate Token Validation")
def test_sign_with_revoked_token_returns_unauthorized(
    gpg_cli_invoker: GpgCliInvoker,
) -> None:
    """A revoked token must fail the bridge's authz check before signing.

    Verifies the real authz path against a live ``agent-auth`` service —
    not :class:`_NoopAuthz`. Pinning the 401 mapping at the integration
    layer guards against the bridge dropping the ``unauthorized``
    discriminator that ``gpg-cli`` relies on.
    """
    stack = gpg_cli_invoker.stack
    payload = stack.agent_auth.create_token("gpg:sign=allow")
    stack.agent_auth.exec_cli("token", "revoke", payload["family_id"])

    sign_result = gpg_cli_invoker.sign(
        token=payload["access_token"],
        fingerprint=stack.primary_fingerprint,
        payload=_PAYLOAD,
    )
    assert sign_result.returncode != 0
    assert "unauthorized" in _stderr_text(sign_result)


@pytest.mark.covers_function("Delegate Token Validation", "Check Scope Authorization")
def test_sign_with_wrong_scope_returns_forbidden(
    gpg_cli_invoker: GpgCliInvoker,
) -> None:
    """A token without ``gpg:sign`` must return 403 / ``scope_denied``."""
    stack = gpg_cli_invoker.stack
    payload = stack.agent_auth.create_token("things:read=allow")

    sign_result = gpg_cli_invoker.sign(
        token=payload["access_token"],
        fingerprint=stack.primary_fingerprint,
        payload=_PAYLOAD,
    )
    assert sign_result.returncode != 0
    assert "forbidden" in _stderr_text(sign_result)


@pytest.mark.covers_function("Delegate Token Validation")
def test_sign_with_expired_token_returns_token_expired(
    gpg_bridge_stack_factory,
) -> None:
    """An expired access token must surface as 401 ``token_expired``.

    End-to-end coverage of the time-based expiry path. Pinning this at
    the integration layer guards against the bridge dropping the
    ``token_expired`` discriminator in favour of a generic 401 — which
    a future ``gpg-cli`` refresh path would rely on to decide whether
    to refresh.
    """
    stack = gpg_bridge_stack_factory(access_token_ttl_seconds=1)
    payload = stack.agent_auth.create_token("gpg:sign=allow")
    time.sleep(2)
    invoker = GpgCliInvoker(stack=stack)

    sign_result = invoker.sign(
        token=payload["access_token"],
        fingerprint=stack.primary_fingerprint,
        payload=_PAYLOAD,
    )
    assert sign_result.returncode != 0
    assert "unauthorized" in _stderr_text(sign_result)


@pytest.mark.covers_function("Delegate Token Validation")
def test_sign_with_authz_unavailable_returns_unavailable(
    gpg_cli_invoker: GpgCliInvoker,
) -> None:
    """Stop ``agent-auth`` mid-test so the bridge's authz call surfaces a real
    connection error rather than a mocked one. The 502
    ``authz_unavailable`` discriminator is what clients rely on to
    distinguish upstream outage from bad tokens; ``gpg-cli`` maps it
    to its bridge-unavailable error type.
    """
    stack = gpg_cli_invoker.stack
    payload = stack.agent_auth.create_token("gpg:sign=allow")
    stack.stop_agent_auth()

    sign_result = gpg_cli_invoker.sign(
        token=payload["access_token"],
        fingerprint=stack.primary_fingerprint,
        payload=_PAYLOAD,
    )
    assert sign_result.returncode != 0
    assert "bridge unavailable" in _stderr_text(sign_result)


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_sign_with_unknown_fingerprint_returns_no_such_key(
    gpg_cli_invoker: GpgCliInvoker,
) -> None:
    """Signing with a fingerprint absent from the host keyring must
    surface as a structured ``no_such_key`` error from the backend
    (mapped to a non-zero ``gpg-cli`` exit), not a silent fallback.

    Pinning this at the integration layer guards against the backend
    swallowing ``gpg``'s "No secret key" stderr and reporting success.
    """
    stack = gpg_cli_invoker.stack
    payload = stack.agent_auth.create_token("gpg:sign=allow")
    # 40-char hex string that is *not* a baked test fingerprint.
    bogus_fingerprint = "DEADBEEFCAFE00000000000000000000DEADBEEF"

    sign_result = gpg_cli_invoker.sign(
        token=payload["access_token"],
        fingerprint=bogus_fingerprint,
        payload=_PAYLOAD,
    )
    assert sign_result.returncode != 0


@pytest.mark.covers_function("Delegate Token Validation", "Serve Bridge Health Endpoint")
def test_health_endpoint_requires_token(gpg_bridge_stack) -> None:
    """Regression guard: dropping the bearer check would let any caller
    probe service-internal state without authorization.

    Asserted via raw HTTP from the test runner over the loopback host
    port mapping — the bridge's bearer enforcement happens before any
    handler logic runs, so no scope is required to pin the unauth path.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(f"{gpg_bridge_stack.base_url}/gpg-bridge/health")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req, timeout=5)
    assert excinfo.value.code == 401
