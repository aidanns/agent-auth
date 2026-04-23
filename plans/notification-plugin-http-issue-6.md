<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Notification plugin → out-of-process HTTP endpoint (#6)

Closes #6.

## Summary

Replace the in-process `NotificationPlugin` + `importlib.import_module`
loader with an HTTP client. Config names the plugin by URL; the plugin
is an independent process with its own trust boundary.

## Wire protocol

```
POST ${notification_plugin_url}
Content-Type: application/json
{
  "family_id": "fam-abc123",
  "scope":     "things:write",
  "description": "Add todo 'ship PR'"
}
```

Response body (JSON):

```
{
  "approved": true,
  "grant_type": "timed",         // "once" | "timed"
  "duration_minutes": 60         // omitted or null unless grant_type == "timed"
}
```

- A non-2xx response is treated as deny with no grant.
- A connect / read error past the configured timeout is treated as
  deny (fail-closed — a broken notifier cannot silently approve).
- The client sends no authentication; the plugin is expected to be
  127.0.0.1-bound. Adding mutual auth is follow-up if the plugin
  ever moves off-host.

## Decisions

- **No in-process fallback.** `notification_plugin_url = ""` means
  every `prompt`-tier scope is denied; the server emits a warning
  at startup. This is explicit and secure; silently accepting
  prompt requests would defeat the trust-boundary goal.
- **No dynamic module loading.** `importlib.import_module` leaves
  the server-side code base entirely. The verify-standards gate
  asserts the absence.
- **Reference notifier ships as a CLI** under
  `src/agent_auth_notifier/`. `agent-auth-notifier terminal` runs a
  loopback HTTP server and prompts the operator on stderr. This
  replaces the deleted `src/agent_auth/plugins/terminal.py`.
- **Test-only approve / deny notifiers** live under
  `src/tests_support/notifier/` as runnable modules
  (`python -m tests_support.notifier approve`). Docker integration
  tests launch one as a sidecar inside the container.
- **Test helper.** A tiny `tests/_notifier_fake.py` spins up an
  in-process threading HTTP server that returns a configurable
  response. Every test that used `NotificationPlugin` subclasses
  switches to this helper.

## Files

### New

- `src/agent_auth/approval_client.py` — `ApprovalResult` dataclass,
  `ApprovalClient` HTTP client with timeout + fail-closed semantics.
- `src/agent_auth_notifier/__init__.py`, `cli.py`, `terminal.py` —
  reference notifier package with `terminal` subcommand.
- `src/tests_support/notifier/__init__.py`, `__main__.py` — approve
  / deny HTTP servers.
- `tests/_notifier_fake.py` — in-process HTTP fake for unit tests.
- `tests/test_approval_client.py` — unit tests for the client.

### Modified

- `src/agent_auth/plugins/__init__.py` → delete (the package goes
  away entirely).
- `src/agent_auth/plugins/terminal.py` → delete.
- `src/tests_support/always_approve.py`, `always_deny.py` → delete
  (superseded by `tests_support.notifier`).
- `src/agent_auth/approval.py` — take `ApprovalClient` instead of
  `NotificationPlugin`.
- `src/agent_auth/config.py` — replace
  `notification_plugin` / `notification_plugin_config` with
  `notification_plugin_url` (default `""`) +
  `notification_plugin_timeout_seconds` (default `30.0`).
- `src/agent_auth/server.py` — drop `load_plugin` import; build an
  `ApprovalClient` from config and pass it to `ApprovalManager`.
- `pyproject.toml` — add `agent-auth-notifier` script entry.
- `docker/config.test.yaml` — use URL-based config.
- `docker/docker-compose*.yaml`, `docker/Dockerfile*` — launch
  `tests_support.notifier` sidecar in the integration container.
- `tests/integration/conftest.py` — switch `APPROVAL_PLUGINS` to
  URLs.
- `tests/test_*` touching `NotificationPlugin` — switch to the fake.
- `design/DESIGN.md` — new "Notification plugin wire protocol"
  section; update trust-boundary prose.
- `design/error-codes.md` — note that unavailable notifier → deny.
- `scripts/verify-standards.sh` — new gate (no
  `importlib.import_module` for plugin loading; config rejects
  dotted-module names where a URL is expected).

## Regression gate

Two checks in `scripts/verify-standards.sh`:

1. `src/agent_auth/server.py` must not call `importlib.import_module`
   (grep, stripped of comments).
2. `src/agent_auth/config.py` must carry `notification_plugin_url`
   (i.e. the URL-based field) and not the legacy
   `notification_plugin:` name. This catches a revert of the config
   schema.

## Post-implementation review

Per `.claude/instructions/plan-template.md`:

- Coding standards (new module / dataclass naming, error surfaces).
- Service design (trust boundary, fail-closed semantics, timeout).
- Release / hygiene (CHANGELOG driven by commit, DESIGN section).
- Testing (public API only — tests hit the HTTP surface via the
  fake, not internal classes).
- Tooling / CI (new entry point in pyproject.toml).

## Out of scope

- Plugin-to-server auth (follow-up if plugin ever moves off-host).
- Notifier discovery / health endpoints on the plugin itself.
- GUI notifier (the terminal CLI is the reference; a native Mac
  notifier is a separate project).
