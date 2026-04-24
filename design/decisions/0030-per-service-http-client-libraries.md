<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0030 — Extract per-service HTTP client libraries

## Status

Accepted — 2026-04-23.

## Context

Before this ADR the HTTP surface of each in-tree service was re-implemented
three times:

- `src/things_bridge/authz.py::AgentAuthClient` — a validate-only client the
  bridge used to delegate token checks to agent-auth.
- `src/things_cli/client.py::BridgeClient` — a fairly complete client for
  things-bridge endpoints that also knew the token refresh/reissue dance
  against agent-auth.
- `tests/_http.py` — minimal `urllib` wrappers used directly in every
  integration test and e2e test.

Each place owned a slightly different view of the same HTTP surface:
endpoint shape, status-code-to-error mapping, URL-and-header assembly, and
TLS context management. Adding a new endpoint meant touching every caller,
and the integration tests' `tests._http.post` / `tests._http.get`
assertions drifted from the typed-error taxonomy the production code
already had. See issue #94 for the catalogue.

## Considered alternatives

### Keep the three views in sync by convention

Leave the split. Document the convention that the same URL / status
mapping lives in three places and require reviewers to keep them
aligned.

**Rejected** because:

- The three views already disagreed in subtle ways (e.g. `tests._http.post`
  treats every non-2xx as `(status, body)`; the production clients raise
  typed errors). Convention alone does not catch drift.
- Adding a new endpoint is a three-place edit, which is the opposite of
  the code-owning-the-surface pattern the rest of this repo uses.

### One combined `agent_auth_http` package

Bundle both services behind a single importable client surface.

**Rejected** because:

- It couples the two services' release cadence and target users. The
  forthcoming per-subproject split (#105) separates their deployable
  lifecycles; a single client package would need to be unwound at that
  boundary.
- Production callers of `agent-auth` (the bridge) do not want the
  `things-bridge` endpoints at all, and vice-versa. Keeping them
  separate keeps the import graph honest.

## Decision

Introduce two first-class `src/` packages, one per service, each covering
the full public HTTP surface of that service:

- `src/agent_auth_client/` — `AgentAuthClient` with one method per
  `/agent-auth/*` endpoint (`validate`, `refresh`, `reissue`, `get_status`,
  `check_health`, `get_metrics_text`, and the management `create_token`
  / `list_tokens` / `modify_token` / `revoke_token` / `rotate_token`).
  Non-2xx responses map to a typed error hierarchy (`AuthzError` and
  specific subclasses). Typed `@dataclass` return values (`TokenPair`,
  `RefreshedTokens`, …) replace raw `dict[str, Any]` shapes for the
  responses whose structure is stable.
- `src/things_bridge_client/` — `ThingsBridgeClient` with one method per
  `/things-bridge/*` endpoint (`list_todos`, `get_todo`, `list_projects`,
  `get_project`, `list_areas`, `get_area`, `check_health`,
  `get_metrics_text`). Non-2xx responses map to a
  `ThingsBridgeClientError` hierarchy.

The refresh/reissue orchestration that previously lived inside
`things_cli.client.BridgeClient` is kept in `things_cli.client` as a thin
wrapper around `ThingsBridgeClient` and `AgentAuthClient`; the wrapper
owns the credential-store side-effects and the "one retry on 401
token_expired" policy, but every individual HTTP round-trip goes through
the library clients.

### Naming

`AuthzError` and its subclasses keep their pre-split names
(`AuthzTokenInvalidError`, `AuthzScopeDeniedError`, `AuthzUnavailableError`,
…). The bridge server's validation handler already except-branches on
those classes, and there are no readability wins that justify churning
~80 call sites.

### Tests

`tests/integration/agent_auth/test_*.py` and
`tests/integration/things_bridge/test_bridge.py` drive the services
through the new client libraries instead of
`tests._http.{get,post,get_text}`. `tests/integration/things_cli/test_cli.py`
is unchanged (it drives the CLI subprocess). Dedicated unit suites
(`tests/test_agent_auth_client.py`, `tests/test_things_bridge_client.py`)
pin the status-code-to-exception contract against stub HTTP servers so a
regression is caught without a Docker run.

`tests/_http.py` is kept in-tree for now: the unit tests under
`tests/test_server*.py`, `tests/test_perf_budget.py`, and
`tests/test_error_taxonomy.py` still drive in-process bound servers
through it, which is outside the scope of issue #94.

## Consequences

Positive:

- Integration tests exercise the same client code real callers use,
  closing the gap between what is tested and what ships.
- Adding a new endpoint to either service is a one-place edit in the
  corresponding `*_client` package; every caller, including every test,
  picks it up for free.
- Typed return values and typed errors tighten call-site assertions and
  make refactors safer than they were against `dict[str, Any]`.
- The packages are independently importable, which lines up with #105's
  per-subproject split — each service package can depend on its own
  client library without pulling in the other service's transitive deps.

Negative:

- Adds two new in-tree packages, which slightly increases the import
  graph and the test matrix. Mitigated: each package is small (~100-350
  lines), shares no runtime dependencies beyond the standard library,
  and ships with dedicated unit tests.
- `tests/_http.py` survives this PR. A future follow-up can migrate the
  remaining unit-test callers and delete the module.

## Follow-ups

- Migrate the remaining `tests/_http.py` callers (unit tests under
  `tests/test_server*.py`, `tests/test_perf_budget.py`,
  `tests/test_error_taxonomy.py`) to the client libraries and delete
  `tests/_http.py`.
- Under #105 (service split), each subproject declares its own
  dependency on `agent_auth_client` or `things_bridge_client` and the
  library packages stop living inside `agent-auth`'s distribution.
