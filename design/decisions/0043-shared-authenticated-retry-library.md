<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0043 — Share the refresh + reissue retry loop across CLIs

## Status

Accepted — 2026-04-26.

## Context

Once [#327](https://github.com/aidanns/agent-auth/issues/327) landed,
two CLIs owned near-identical token-lifecycle orchestration:

- `packages/things-cli/src/things_cli/client.py` —
  `_with_retry`, `_refresh_access_token`, `_reissue_tokens`.
- `packages/gpg-cli/src/gpg_cli/client.py` — the same control flow
  against the gpg-bridge surface.

Both share the upstream
[`AgentAuthClient`](../../packages/agent-auth-common/src/agent_auth_client/client.py)
and the same contract from
[ADR 0011](0011-refresh-token-reuse-family-revocation.md): single-use
refresh tokens, family revocation on reuse, JIT-approved reissue once
the refresh token has expired. They differ only in:

- the per-endpoint downstream client (`ThingsBridgeClient` vs the
  inline gpg-bridge wire calls);
- the credential-storage backend (keyring + YAML for things-cli, a
  single YAML config file for gpg-cli);
- the typed exception classes raised when the retry budget is
  exhausted (`ThingsBridge*` vs `Bridge*`).

[Issue #328](https://github.com/aidanns/agent-auth/issues/328) flagged
that as duplication ripe for consolidation: the orchestration is
uniform, the inputs are pluggable, and any future change to the retry
contract (exponential backoff on 429, structured logging of refresh
outcomes for the audit log, a new `family_revoked` discriminator)
would otherwise have to land twice and stay in sync.

The same shape was the rationale for
[ADR 0030](0030-per-service-http-client-libraries.md), which carved
the per-service HTTP clients out of duplicated call sites; this ADR
applies the same logic one level up — to the
authentication-orchestration layer that wraps those clients.

## Considered alternatives

### Keep the orchestration duplicated

Leave the two `_with_retry` / `_refresh_access_token` /
`_reissue_tokens` ladders in place. Document the convention that any
change has to land in both files.

**Rejected** because:

- The two implementations are line-for-line identical apart from
  three exception names; convention alone does not prevent silent
  drift, and the next change to the retry contract has no incentive
  to land twice in lockstep.
- The same drift-by-duplication failure mode is what ADR 0030 already
  rejected for the per-service HTTP surface — applying the same
  argument here is consistent.

### Lift the credential store too into a shared module

Option B in #328: move `KeyringStore` / `FileStore` (and the gpg-cli
YAML store) behind a single `agent_auth_credentials/` module, and
adopt it from both CLIs as part of this change.

**Rejected (for now)** because:

- The two stores' on-disk schemas differ (separate keyring entries
  per field for things-cli, single YAML file co-located with gpg-cli
  config). Lifting them requires picking a unified schema, which
  forces a decision on whether gpg-cli should also be promoted to
  keyring-backed storage.
- The blast radius is larger: every gpg-cli operator has to migrate
  their on-disk file. The orchestration extraction has zero on-disk
  impact and the two changes are independently valuable.
- Per the issue body's recommendation, ship Option A first and open
  a follow-up for Option B if the storage-side duplication starts to
  matter.

### Extract a per-CLI base class

Have each CLI's `BridgeClient` inherit from a shared `_RetryMixin`
that owns the retry methods.

**Rejected** because:

- The two CLIs' constructors take different arguments, raise
  different exceptions, and depend on different downstream clients;
  a base class forces every difference to be expressed via
  abstract-method overrides. A composition seam is simpler — see
  the `AuthenticatedRetry` shape below.
- Inheritance hides the orchestration behind the consumer's class
  name, making the shared contract less discoverable.

## Decision

Introduce `AuthenticatedRetry` in
`packages/agent-auth-common/src/agent_auth_client/auth_retry.py`,
exported from the existing `agent_auth_client` package. The class
owns the refresh + reissue retry ladder verbatim from the previous
per-CLI implementations; each CLI's `BridgeClient` collapses to a
thin adapter that constructs an `AuthenticatedRetry` with its own
exception classes and credential record.

Shape:

```python
class AuthenticatedRetry(Generic[T, C]):
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
    ): ...

    def with_retry(self, call: Callable[[str], T]) -> T: ...
```

`CredentialsLike` and `CredentialStoreLike` are
`typing.Protocol`s — typing seams only, not runtime gates — so both
CLIs' existing concrete classes (the
`things_cli.credentials.Credentials` dataclass with its keyring or
file-backed store, and the `gpg_cli.config.Credentials` dataclass
with its YAML-backed `FileStore`) satisfy them structurally with no
wrapping or adapter layer. `AuthenticatedRetry` is parameterised on
the concrete credential type `C` so the store contract stays
type-precise on each call site (mypy and pyright reject a mismatch).

The library deliberately stays Option A: it does not own the
credential-storage layout. The store seam is a one-method protocol,
which both CLIs already implement.

### Module placement and import-graph impact

The new module lives inside `agent_auth_client/` (not as a new
sibling package) because:

- The orchestration is intrinsically tied to agent-auth's refresh +
  reissue contract; the implementation imports `AgentAuthClient`,
  `RefreshTokenExpiredError`, `AuthzError`, and
  `AuthzUnavailableError` directly. Splitting it out would
  effectively re-export agent-auth's error taxonomy from a sibling
  package.
- Both CLIs already declare `agent-auth-common` as a workspace
  dependency for `agent_auth_client`; the new module ships in the
  same wheel with no additional cross-package edge.
- Consequently the [ADR 0036](0036-workspace-dep-graph-allowlist.md)
  allowlist requires no entries — the existing
  `things-cli → agent-auth-common` and `gpg-cli → agent-auth-common`
  edges already cover the new module. ADR 0036 is amended below to
  record that `auth_retry` is a sanctioned entry point in the
  shared library.

### Behaviour preserved verbatim, except for one wrapping difference

The retry budget (one), the persistence-before-retry ordering
(ADR 0011's load-bearing safety property), the
`no family_id` early-exit, and the typed-exception surface are all
unchanged. Each CLI's behavioural test suite
(`packages/things-cli/tests/test_things_cli_client.py` and
`packages/gpg-cli/tests/test_gpg_cli_client.py`) passes
unmodified.

The one observable difference: gpg-cli previously wrapped
`AuthzUnavailableError` messages with a second `agent-auth refresh unavailable: ` / `agent-auth reissue unavailable: ` prefix before
re-raising as `BridgeUnavailableError`. The shared library uses
`str(exc)` directly, so the message becomes `agent-auth unreachable: <root>` (the original `AuthzUnavailableError` text from
`AgentAuthClient`) instead of the doubled `agent-auth refresh unavailable: agent-auth unreachable: <root>`. The exception type is
unchanged, no test asserts on the string, and the new wording is
arguably clearer; not worth a per-CLI message-formatter argument.

## Consequences

Positive:

- The retry contract is a single edit instead of a two-place edit;
  future enhancements (exponential backoff on 429, refresh-outcome
  audit logging, a new server-side error discriminator) land once.
- The orchestration has its own dedicated unit test suite
  (`packages/agent-auth-common/tests/test_authenticated_retry.py`)
  driving the behaviour through the protocol seams against an
  in-process agent-auth fake. The per-CLI integration suites stay
  the regression net for the end-to-end HTTP plumbing.
- The seams (`CredentialsLike`, `CredentialStoreLike`, the three
  injected exception classes) document exactly what a future
  consumer needs to plug into the shared loop. The next CLI that
  needs refresh + reissue (none currently planned) won't have to
  copy the ladder a third time.

Negative:

- One extra module in `agent-auth-common`; the import graph gains a
  small re-export from `agent_auth_client.__init__`. Acceptable: the
  module is ~70 lines of orchestration plus two protocol shapes,
  and it ships in the same wheel that both CLIs already depend on.
- The exception-injection seam is unsigned (not bound by an ABC).
  A consumer could pass an exception class whose constructor doesn't
  accept a single positional `str` and only find out at runtime when
  the retry path fires. Mitigated: the test suite covers each
  raise-site, and there are only two consumers in-tree.

## Follow-ups

- Option B (lift the credential store too) is a separate issue if
  the storage-side duplication grows enough to matter.
- If a third refresh + reissue consumer ever lands, revisit whether
  `no_family_id_message` should become a more structured "recovery
  hint" type rather than a free-form string — currently each CLI
  knows its own bootstrap command, so a string is enough.
