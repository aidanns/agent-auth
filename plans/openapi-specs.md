<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: OpenAPI specs for agent-auth and things-bridge

Closes #117 (`1.0/api-stability`).

## Summary

`#27` / `#28` locked down the HTTP surface (URL versioning, error
taxonomy) in human-readable form. OpenAPI makes the same surface
machine-checkable: request / response schemas, error codes,
versioning, and client generation all derive from a single source.
The deterministic regression check is a Python contract test that
imports both server handlers, extracts every registered route, and
asserts parity with the spec.

## Deliverables

1. `openapi/agent-auth.v1.yaml` — OAS 3.1 spec covering every
   endpoint on `/agent-auth/v1/*` and `/agent-auth/health`.
2. `openapi/things-bridge.v1.yaml` — OAS 3.1 spec covering every
   endpoint on `/things-bridge/v1/*` and `/things-bridge/health`.
3. `openapi/README.md` — short README describing the files, the
   Redocly-hosted rendered view (linked from `README.md`), and the
   stability guarantees (inherits from `design/DESIGN.md` versioning
   policy and `design/error-codes.md`).
4. `tests/test_openapi_spec.py` — contract tests that:
   - load both specs via `openapi-spec-validator`,
   - reflect on the server handlers to extract every registered
     route, and assert the spec has a matching operation,
   - walk the spec's paths and assert every operation maps to a
     registered server route (catches stale spec entries),
   - assert every error code the server emits appears in the spec's
     `components.responses` error-envelope enum (ties to #28).
5. `scripts/verify-standards.sh` — new gate: `openapi/*.v1.yaml`
   exist and `tests/test_openapi_spec.py` exists and references
   both spec filenames.
6. `README.md` — link to the rendered specs from the API section.
7. `CHANGELOG.md` — record the new specs and CI gate.
8. `openapi-spec-validator` added to dev dependencies (Python
   tool, fits the uv-managed stack; no Node dependency required).

## Route matrix (agent-auth)

| Method | Path                           | Auth                      | Notes                                                                  |
| ------ | ------------------------------ | ------------------------- | ---------------------------------------------------------------------- |
| POST   | `/agent-auth/v1/validate`      | token in body             | JIT approval when tier is prompt.                                      |
| POST   | `/agent-auth/v1/token/refresh` | refresh in body           | Reuse detection revokes the family.                                    |
| POST   | `/agent-auth/v1/token/reissue` | approval required         | Only available after refresh token expires.                            |
| POST   | `/agent-auth/v1/token/create`  | management bearer         | Admin scopes required.                                                 |
| POST   | `/agent-auth/v1/token/modify`  | management bearer         | Add/remove/set-tier on an existing family.                             |
| POST   | `/agent-auth/v1/token/revoke`  | management bearer         | Idempotent.                                                            |
| POST   | `/agent-auth/v1/token/rotate`  | management bearer         | Creates new family with same scopes; revokes old.                      |
| GET    | `/agent-auth/v1/token/list`    | management bearer         | Never lists families holding `agent-auth:manage`.                      |
| GET    | `/agent-auth/v1/token/status`  | any valid token           | Self-introspection; used by `things-cli` to decide refresh vs reissue. |
| GET    | `/agent-auth/health`           | `agent-auth:health` scope | Unversioned by convention (see DESIGN.md API versioning policy).       |

## Route matrix (things-bridge)

| Method | Path                              | Auth                         | Notes                                                             |
| ------ | --------------------------------- | ---------------------------- | ----------------------------------------------------------------- |
| GET    | `/things-bridge/v1/todos`         | `things:read` scope          | Optional `list`, `project`, `area`, `tag`, `status` query params. |
| GET    | `/things-bridge/v1/todos/{id}`    | `things:read` scope          |                                                                   |
| GET    | `/things-bridge/v1/projects`      | `things:read` scope          | Optional `area` query param.                                      |
| GET    | `/things-bridge/v1/projects/{id}` | `things:read` scope          |                                                                   |
| GET    | `/things-bridge/v1/areas`         | `things:read` scope          |                                                                   |
| GET    | `/things-bridge/v1/areas/{id}`    | `things:read` scope          |                                                                   |
| GET    | `/things-bridge/health`           | `things-bridge:health` scope | Unversioned by convention.                                        |

## Design verification

No design changes. The specs are a machine-readable view of
`design/DESIGN.md` and `design/error-codes.md`. No ADR is required.
Threat model unchanged — the specs do not introduce new surface.

## Post-implementation standards review

- coding-standards: n/a (no new code apart from tests).
- service-design: specs reinforce the versioning + taxonomy standards.
- release-and-hygiene: CHANGELOG updated; spec files tracked.
- testing-standards: contract tests exercise the public handler
  surface (no internal reflection into private state).
- tooling-and-ci: the verify-standards gate + pytest contract test
  cover both spec existence and route parity.
