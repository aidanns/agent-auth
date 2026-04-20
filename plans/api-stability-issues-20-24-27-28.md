<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: API Stability Issues #20, #24, #27, #28

Closes #20, #24, #27, #28 (all `1.0/api-stability`).

## Summary

Four inter-related API stability improvements:

- **#24**: Migrate agent-auth config from JSON → YAML
- **#27**: Version all HTTP endpoints under `/v1/`
- **#20**: Pin audit-log schema with contract tests
- **#28**: Document error taxonomy as public API with contract tests

## Design verification

All changes are additive hardening (tests + documentation) or mechanical
migrations with no semantics change. No new ADR is needed; the versioning
policy goes into `design/DESIGN.md`. The threat model is unaffected.

## #24 — Config format migration

**Files changed:**

- `src/agent_auth/config.py`: switch to `yaml.safe_load("config.yaml")`, drop `import json`
- `docker/config.test.json` → `docker/config.test.yaml`: rename + convert to YAML
- `tests/integration/conftest.py`: update `BASELINE_CONFIG`, `_write_test_config` to read/write YAML
- `docker/docker-compose.yaml`: fix comment
- `tests/test_config.py`: ensure tests remain green
- `README.md`, `CLAUDE.md`: update references from `config.json` → `config.yaml`

**verify-standards.sh addition:**
Assert no `config.json` reference and no `json.load`/`json.loads` on a config
file path appears in `src/`.

## #27 — URL-versioned API namespace

**Route changes (server files):**

| Old                                | New                                       |
| ---------------------------------- | ----------------------------------------- |
| `POST /agent-auth/validate`        | `POST /agent-auth/v1/validate`            |
| `POST /agent-auth/token/refresh`   | `POST /agent-auth/v1/token/refresh`       |
| `POST /agent-auth/token/reissue`   | `POST /agent-auth/v1/token/reissue`       |
| `GET /agent-auth/token/status`     | `GET /agent-auth/v1/token/status`         |
| `GET /agent-auth/health`           | **unchanged** (unversioned by convention) |
| `GET /things-bridge/todos`         | `GET /things-bridge/v1/todos`             |
| `GET /things-bridge/todos/{id}`    | `GET /things-bridge/v1/todos/{id}`        |
| `GET /things-bridge/projects`      | `GET /things-bridge/v1/projects`          |
| `GET /things-bridge/projects/{id}` | `GET /things-bridge/v1/projects/{id}`     |
| `GET /things-bridge/areas`         | `GET /things-bridge/v1/areas`             |
| `GET /things-bridge/areas/{id}`    | `GET /things-bridge/v1/areas/{id}`        |
| `GET /things-bridge/health`        | **unchanged** (unversioned by convention) |

**Files changed:**

- `src/agent_auth/server.py`: update all route strings
- `src/things_bridge/server.py`: update all route strings + prefix-strip logic
- `src/things_cli/client.py`: update paths in `list_todos`, `get_todo`, etc.
  and in `_refresh_access_token`/`_reissue_tokens`
- `tests/test_server.py`: update path strings
- `tests/test_things_bridge_server.py`: update path strings
- `tests/test_things_cli_client.py`: update mock handler path checks
- `tests/integration/conftest.py`: update `url()` to prepend `/agent-auth/v1/`,
  add `health_url()` returning `/agent-auth/health`, update wait probe
- `tests/integration/things_bridge/conftest.py`: same pattern for things-bridge
- `design/DESIGN.md`: add versioning policy section

**Versioning policy:**

- Breaking changes (field removal, semantic change) bump to `/v2/`
- Additive changes (new optional fields, new endpoints) stay on current version
- `/health` and `/metrics` are always unversioned
- One major version supported at a time; old version deprecated 30 days before removal

**verify-standards.sh addition:**
Assert every registered route (excluding `/health`) matches
`^/(agent-auth|things-bridge)/v\d+/`.

## #20 — Audit schema contract tests

**New file: `tests/test_audit_schema.py`**

For each of the 13 audit event kinds, assert:

- Required fields present (`timestamp`, `event`, plus event-specific fields)
- `timestamp` is ISO 8601 UTC (ends with `+00:00`)
- `event` string matches exactly

Event kinds:

- Token operations: `token_created`, `token_refreshed`, `token_reissued`,
  `token_revoked`, `token_rotated`, `scopes_modified`, `reissue_denied`
- Auth decisions: `validation_allowed`, `validation_denied`,
  `approval_granted`, `approval_denied`

Tests call `AuditLogger.log_token_operation` / `log_authorization_decision`
directly (the audit logger is public API), capture the JSON line, and validate
field presence and types.

**verify-standards.sh addition:**
Assert `tests/test_audit_schema.py` exists and references each documented
event kind as a string literal.

## #28 — Error taxonomy contract tests

**New file: `design/error-codes.md`**

Enumerate every error code per endpoint: HTTP status, meaning, stability guarantee.

**New file: `tests/test_error_taxonomy.py`**

For each endpoint/error-code pair, start a minimal in-process server and assert
the response body contains `{"error": "<code>"}` (and optionally `"valid": False`
for validate errors). Uses the same lightweight HTTP-over-loopback fixture style
as `tests/test_server.py`.

**verify-standards.sh addition:**
Assert `tests/test_error_taxonomy.py` exists and references each documented
error code.

## Post-implementation standards review

- coding-standards: no new types or naming changes; n/a
- service-design: verify config YAML path, health endpoints remain unversioned
- release-and-hygiene: no new outputs
- testing-standards: new tests exercise public API only; no mock leakage
- tooling-and-ci: verify-standards.sh additions wired in
