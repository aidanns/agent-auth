# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared refresh + reissue retry orchestration for credential-rotating CLIs.

Both ``things-cli`` and ``gpg-cli`` wrap their downstream HTTP client in
the same control flow: attach the bearer access token, catch a single
``token_expired`` 401, refresh (and on ``refresh_token_expired`` reissue
via host-side JIT approval), persist the rotated pair, retry once, then
surface a typed unauthorized error if the second attempt also fails.

This module centralises that orchestration. The downstream HTTP plumbing
(per-endpoint methods, status-to-error mapping, TLS context management)
stays in each CLI's :class:`BridgeClient`; only the retry / refresh /
reissue ladder is shared. The persistence-before-retry ordering is the
load-bearing safety property from
:doc:`ADR 0011 </design/decisions/0011-refresh-token-reuse-family-revocation>`:
refresh tokens are single-use, so the rotated pair must reach the
credential store *before* the retried downstream call runs — otherwise a
crash between the refresh response and the retry leaves a consumed
refresh token on disk and the next bootstrap revokes the family on
reuse-detection.

The seam is intentionally narrow:

- :class:`CredentialsLike` — the credential record (mutable
  ``access_token`` / ``refresh_token`` plus an optional ``family_id``).
- :class:`CredentialStoreLike` — a one-method protocol with ``save``.
- The three caller-domain exception classes injected at construction:
  the downstream-client's ``token_expired`` discriminator, the
  ``unauthorized`` error to raise on a failed retry, and the
  ``unavailable`` error to raise when agent-auth is unreachable.

The shared library deliberately knows nothing about the credential
storage layout (keyring vs YAML vs JSON), the downstream endpoint shape,
or the CLI's exit-code mapping. Per Option A in the design discussion
on issue #328, lifting the credential store too is left as a follow-up.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, Protocol, TypeVar

from agent_auth_client.client import AgentAuthClient
from agent_auth_client.errors import AuthzError, AuthzUnavailableError, RefreshTokenExpiredError

T = TypeVar("T")


class CredentialsLike(Protocol):
    """Mutable credential record consumed by :class:`AuthenticatedRetry`.

    The retry loop reads ``access_token`` to attach the bearer header,
    reads ``refresh_token`` to drive the refresh exchange, reads
    ``family_id`` to drive the reissue exchange when the refresh token
    is itself expired, and rewrites ``access_token`` / ``refresh_token``
    in-place after each successful rotation.

    Both ``things_cli.credentials.Credentials`` and
    ``gpg_cli.config.Credentials`` satisfy this shape structurally; the
    protocol exists so the orchestration layer can see them through one
    type.
    """

    access_token: str
    refresh_token: str
    family_id: str | None


# Contravariant: a store that knows how to persist the narrow
# :class:`CredentialsLike` shape can substitute for one that handles a
# concrete subtype. The two CLIs' concrete stores
# (``things_cli.credentials.CredentialStore`` and
# ``gpg_cli.config.FileStore``) declare ``save`` against their own
# specific ``Credentials`` dataclass; the contravariant ``C_contra``
# is what lets a ``def save(creds: ConcreteCredentials)`` satisfy
# ``CredentialStoreLike[ConcreteCredentials]``.
C_contra = TypeVar("C_contra", bound=CredentialsLike, contravariant=True)
# Invariant credential type for :class:`AuthenticatedRetry`. ``C`` is
# the concrete credential dataclass each CLI passes in (e.g.
# ``things_cli.credentials.Credentials`` or
# ``gpg_cli.config.Credentials``); the store must accept the same
# concrete type via :class:`CredentialStoreLike`.
C = TypeVar("C", bound=CredentialsLike)


class CredentialStoreLike(Protocol[C_contra]):
    """Single-method protocol for persisting a rotated credential pair.

    Parameterised on the concrete credential type so a store that
    accepts a specific ``Credentials`` dataclass (rather than the
    wider :class:`CredentialsLike`) still satisfies the protocol.
    The store is invoked once per rotation, *before* the retried
    downstream call runs, so a crash between the refresh response and
    the retry cannot leave a consumed refresh token on disk.
    """

    def save(self, credentials: C_contra, /) -> None: ...


class AuthenticatedRetry(Generic[T, C]):
    """Refresh / reissue retry loop around a downstream HTTP call.

    Construct one per :class:`BridgeClient` (the cost is ``O(1)`` —
    the constructor only stores references). The same instance is
    re-entrant across requests because :meth:`with_retry` reads and
    rewrites the shared :attr:`credentials` record exactly the way
    the per-CLI implementations did before the consolidation.

    The three injected exception classes adapt the orchestration to
    each CLI's downstream-error taxonomy without coupling this module
    to either:

    - ``token_expired_exc`` is the exception the downstream client
      raises on ``401 {"error": "token_expired"}``; catching it drives
      the refresh path.
    - ``unauthorized_exc`` is the exception this module raises when
      the retry budget is exhausted (a second ``token_expired`` after
      a successful refresh, or any terminal 4xx from refresh / reissue
      that isn't already an unavailability signal).
    - ``unavailable_exc`` is the exception this module raises when
      agent-auth itself is unreachable (refresh / reissue raises
      :class:`AuthzUnavailableError`).
    """

    def __init__(
        self,
        credentials: C,
        store: CredentialStoreLike[C],
        auth: AgentAuthClient,
        *,
        token_expired_exc: type[Exception],
        unauthorized_exc: type[Exception],
        unavailable_exc: type[Exception],
        no_family_id_message: str,
    ):
        self._credentials = credentials
        self._store = store
        self._auth = auth
        self._token_expired_exc = token_expired_exc
        self._unauthorized_exc = unauthorized_exc
        self._unavailable_exc = unavailable_exc
        self._no_family_id_message = no_family_id_message

    def with_retry(self, call: Callable[[str], T]) -> T:
        """Invoke ``call`` with the current access token; refresh once on ``token_expired``.

        ``call`` receives the bearer access token verbatim and returns
        the downstream client's parsed response. A first invocation that
        raises ``token_expired_exc`` triggers exactly one refresh-then-
        retry cycle; the rotated credential pair is persisted *before*
        the retried call runs (ADR 0011). A second ``token_expired`` —
        which shouldn't happen in practice but might if the refresh
        path returns a token the bridge then rejects — is collapsed to
        ``unauthorized_exc`` so the CLI maps it to a non-zero exit like
        any other terminal 401, rather than leaking the internal retry
        contract to callers.
        """
        try:
            return call(self._credentials.access_token)
        except self._token_expired_exc:
            pass
        self._refresh_access_token()
        try:
            return call(self._credentials.access_token)
        except self._token_expired_exc as exc:
            raise self._unauthorized_exc(str(exc) or "token_expired") from exc

    def _refresh_access_token(self) -> None:
        """Exchange the stored refresh token, falling back to reissue on expiry.

        Persists the new pair *before* returning so a crash between the
        refresh response and the next retry attempt cannot leave a
        consumed (single-use) refresh token on disk — see ADR 0011.
        Any 4xx from refresh other than ``refresh_token_expired`` (for
        example ``refresh_token_reuse_detected`` or ``family_revoked``)
        is terminal and surfaces as ``unauthorized_exc`` with the
        server-supplied error code preserved verbatim, so the operator
        sees the specific reason.
        """
        try:
            refreshed = self._auth.refresh(self._credentials.refresh_token)
        except RefreshTokenExpiredError:
            self._reissue_tokens()
            return
        except AuthzUnavailableError as exc:
            raise self._unavailable_exc(str(exc)) from exc
        except AuthzError as exc:
            raise self._unauthorized_exc(str(exc)) from exc
        self._credentials.access_token = refreshed.access_token
        self._credentials.refresh_token = refreshed.refresh_token
        self._store.save(self._credentials)

    def _reissue_tokens(self) -> None:
        """Call the agent-auth reissue endpoint and persist the new pair.

        ``family_id`` is required: reissue identifies the family to
        rebuild from, so a credential record without one is terminal
        and cannot be repaired by retry. The CLI-specific recovery
        message (``things-cli login`` vs
        ``setup-devcontainer-signing.sh``) is injected at construction
        because the choice belongs to the CLI, not the orchestration.
        """
        if not self._credentials.family_id:
            raise self._unauthorized_exc(self._no_family_id_message)
        try:
            reissued = self._auth.reissue(self._credentials.family_id)
        except AuthzUnavailableError as exc:
            raise self._unavailable_exc(str(exc)) from exc
        except AuthzError as exc:
            raise self._unauthorized_exc(str(exc)) from exc
        self._credentials.access_token = reissued.access_token
        self._credentials.refresh_token = reissued.refresh_token
        self._store.save(self._credentials)


__all__ = [
    "AuthenticatedRetry",
    "CredentialStoreLike",
    "CredentialsLike",
]
