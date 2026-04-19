# Plan: Token Management HTTP API (Issue #3)

## Goal

Expose the five CLI token-management operations as HTTP endpoints so that
programmatic clients can manage token lifecycle without SSH/local CLI access.

## New endpoints

| Method | Path                     | CLI equivalent          |
| ------ | ------------------------ | ----------------------- |
| POST   | /agent-auth/token/create | agent-auth token create |
| GET    | /agent-auth/token/list   | agent-auth token list   |
| POST   | /agent-auth/token/modify | agent-auth token modify |
| POST   | /agent-auth/token/revoke | agent-auth token revoke |
| POST   | /agent-auth/token/rotate | agent-auth token rotate |

## Request/response schemas

### POST /agent-auth/token/create

Request: `{"scopes": {"<name>": "<tier>", ...}}`
Response 200: `{"family_id": "...", "access_token": "...", "refresh_token": "...", "scopes": {...}, "expires_in": N}`
Errors: 400 `malformed_request`, 400 `no_scopes`

### GET /agent-auth/token/list

No body. Response 200: array of family objects (same shape as CLI JSON output).

### POST /agent-auth/token/modify

Request: `{"family_id": "...", "add_scopes": {...}, "remove_scopes": [...], "set_tiers": {...}}`
(All modification fields optional; at least one must be non-empty.)
Response 200: `{"family_id": "...", "scopes": {...}}`
Errors: 400 `malformed_request`, 400 `no_modifications`, 404 `family_not_found`, 409 `family_revoked`

### POST /agent-auth/token/revoke

Request: `{"family_id": "..."}`
Response 200: `{"family_id": "...", "revoked": true}` (idempotent for already-revoked families)
Errors: 400 `malformed_request`, 404 `family_not_found`

### POST /agent-auth/token/rotate

Request: `{"family_id": "..."}`
Response 200: `{"old_family_id": "...", "new_family_id": "...", "access_token": "...", "refresh_token": "...", "scopes": {...}, "expires_in": N}`
Errors: 400 `malformed_request`, 404 `family_not_found`, 409 `family_revoked`

## Security decision

Management endpoints (create, modify, revoke, rotate) carry no additional
authentication beyond the existing runtime endpoints. The trust boundary is
the localhost binding (127.0.0.1 by default). Adding a management token would
create a chicken-and-egg problem: you need a token to create the first token.
Document in ADR 0006.

## Files to change

1. `src/agent_auth/server.py` — add 5 handler methods + route entries
2. `design/functional_decomposition.yaml` — add 5 leaf functions under HTTP API
3. `tests/test_server.py` — unit tests for each new endpoint (happy path + errors)
4. `tests/integration/test_token_management.py` — Docker integration tests
5. `scripts/verify-standards.sh` — CLI→HTTP route mapping regression check
6. `design/decisions/0006-management-endpoint-no-auth.md` — ADR for auth decision
7. `design/DESIGN.md` — document new endpoints

## Regression check design (verify-standards.sh)

Inline Python script that:

- Imports `COMMAND_HANDLERS` from `agent_auth.cli` to enumerate token subcommands
- Inspects `AgentAuthHandler.do_POST` / `do_GET` source to find `/agent-auth/token/<cmd>` routes
- Fails if any subcommand has no matching route

## Post-implementation checklist (from plan-template.md)

- [ ] Verify implementation against DESIGN.md; reconcile drift
- [ ] Refresh threat model in SECURITY.md (new unauthenticated write surface)
- [ ] Write ADR 0006 (management endpoint auth decision)
- [ ] Apply coding-standards.md review
- [ ] Apply service-design.md review (stable error taxonomy, API versioning)
- [ ] Apply testing-standards.md review
- [ ] Apply tooling-and-ci.md review
