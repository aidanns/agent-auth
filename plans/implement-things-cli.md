# Implementation Plan: things-cli and things-bridge (read-only)

## Context

`agent-auth` (server + CLI) is implemented (`src/agent_auth/`). `design/DESIGN.md` calls for
a thin CLI (`example-app-cli`) talking to an HTTP bridge (`example-app-bridge`) that interacts
with the target application. `design/THINGS.md` documents the AppleScript surface of Things 3.

This plan implements the first concrete instantiation of that pattern: `things-bridge` (HTTP
server on the macOS host that invokes AppleScript against Things 3) and `things-cli` (CLI
client that calls the bridge with an `agent-auth` bearer token, refreshing automatically when
expired). Scope is **read-only** commands against todos, projects, and areas. Write and JIT
paths are deferred to a follow-up.

## Scope

### In scope

- Two new packages in the existing repo, installed alongside `agent_auth`:
  - `src/things_bridge/`
  - `src/things_cli/`
- Bridge read-only endpoints (scope: `things:read`):
  - `GET /things-bridge/todos?list=&project=&area=&tag=&status=`
  - `GET /things-bridge/todos/{id}`
  - `GET /things-bridge/projects?area=`
  - `GET /things-bridge/projects/{id}`
  - `GET /things-bridge/areas`
  - `GET /things-bridge/areas/{id}`
- CLI commands:
  - `things-cli login` / `things-cli logout` / `things-cli status`
  - `things-cli todos list` / `things-cli todos show <id>`
  - `things-cli projects list` / `things-cli projects show <id>`
  - `things-cli areas list` / `things-cli areas show <id>`
  - `--json` flag for machine-readable output
- AppleScript runner abstraction so the bridge is testable on Linux without `osascript`.
- Unit tests for both packages (following existing `tests/` layout).
- README, DESIGN.md, and decomposition/product-breakdown updates.

### Out of scope (deferred)

- Write/mutation operations (`complete`, `create`, `move`, `schedule`, `delete`).
- JIT approval flow (the bridge still calls `/agent-auth/validate`, but only with `allow` tier
  for read-only).
- Things URL scheme integration.
- Non-Things bridges (`outlook`, etc.).

## Directory layout

```
src/
  agent_auth/                          (existing, unchanged)
  things_bridge/
    __init__.py
    cli.py                             # `things-bridge serve` entrypoint
    server.py                          # ThreadingHTTPServer with read-only routes
    config.py                          # Config dataclass + loader
    authz.py                           # agent-auth /validate HTTP client
    things.py                          # AppleScriptRunner + ThingsClient
    models.py                          # Todo/Project/Area dataclasses and serializers
    applescripts/                      # AppleScript source strings as Python constants
      __init__.py
      read.py
  things_cli/
    __init__.py
    cli.py                             # `things-cli ...` argparse entrypoint
    client.py                          # Bridge HTTP client with auto-refresh / reissue
    credentials.py                     # keyring + file credential store
    config.py                          # Config dataclass + loader
    output.py                          # Text + JSON formatters
tests/
  test_things_bridge_models.py
  test_things_bridge_authz.py
  test_things_bridge_server.py
  test_things_bridge_things.py
  test_things_cli_credentials.py
  test_things_cli_client.py
  test_things_cli_cli.py
plans/
  implement-things-cli.md              (this file)
```

`pyproject.toml` grows two extra `[project.scripts]` entries and no new runtime deps (stdlib
HTTP + existing `keyring`).

## Component design

### things_bridge

**Config (`config.py`)**
- Config dir: `~/.config/things-bridge/` (override via `--config-dir`).
- Fields: `host` (`127.0.0.1`), `port` (`9200`), `auth_url` (`http://127.0.0.1:9100`),
  `osascript_path` (`/usr/bin/osascript`), `log_path`.
- Same load/write pattern as `agent_auth.config`.

**AppleScript runner (`things.py`)**
- `class AppleScriptRunner`: single method `run(script: str) -> str` — shells out to
  `osascript -s s -l AppleScript -` reading the script from stdin, returns stdout. `-s s`
  forces "script-style" output (strings quoted, `missing value` as literal) so results are
  parseable. Raises `ThingsError` on non-zero exit or `-1743` Automation permission errors.
- `class ThingsClient(runner)`: high-level read-only methods:
  - `list_todos(*, list_id=None, project_id=None, area_id=None, tag=None, status=None)`
  - `get_todo(id)`
  - `list_projects(*, area_id=None)`
  - `get_project(id)`
  - `list_areas()`
  - `get_area(id)`
- Each method emits a single AppleScript block that returns a newline-separated,
  tab-separated record stream (per THINGS.md recipe §4), then parses it into model
  dataclasses. Using TSV keeps parsing simple without a JSON dependency on the Things side;
  we sanitise tabs/newlines via AppleScript `my encodeField()` helper (replace with `\t`/`\n`
  placeholders on the way out, restore on the way in).
- Runner is injected so tests can substitute a deterministic fake that returns canned TSV
  for a given script.

**Models (`models.py`)**
- `Todo`, `Project`, `Area` dataclasses. JSON-serializable. ISO 8601 for dates (converted
  from AppleScript date literals inside `things.py`). `missing value` becomes `None`.

**Authz client (`authz.py`)**
- `validate_token(token, scope, *, description=None) -> None` using `http.client` against
  the configured `auth_url`. Raises `TokenInvalidError` / `ScopeDeniedError` / `TokenExpiredError`
  mapped from the auth-server response codes (401/403/404) so the handler can translate them
  into the right HTTP status for the CLI.

**Server (`server.py`)**
- `ThingsBridgeHandler` subclasses `BaseHTTPRequestHandler` (mirrors `agent_auth.server`).
- `do_GET` dispatches to handlers by path. Each handler:
  1. Reads `Authorization: Bearer <token>` header.
  2. Calls `authz.validate_token(token, "things:read", description=<op>)`.
  3. Calls the matching `ThingsClient` method, serialises the result as JSON.
  4. Returns 200 with `{"todos": [...]}` / `{"projects": [...]}` / `{"areas": [...]}` /
     `{"todo": {...}}` etc.
- Errors:
  - No/invalid Bearer → 401 `{"error": "unauthorized"}`
  - Scope denied → 403 `{"error": "scope_denied"}`
  - Token expired → 401 `{"error": "token_expired"}` (CLI treats this as the refresh trigger)
  - `ThingsError` → 502 `{"error": "things_unavailable", "detail": "..."}`
  - Unknown path → 404.
- `ThreadingHTTPServer` carries `config`, `things_client`, `authz`.

**CLI (`cli.py`)**
- `things-bridge serve [--host H] [--port P] [--auth-url URL]`.
- Wires up `AppleScriptRunner` (real one when serving) → `ThingsClient`, authz client, and
  the HTTP server; then calls `serve_forever`.

### things_cli

**Credential store (`credentials.py`)**
- Backends: `KeyringStore` (default) and `FileStore` (enabled via `--credential-store=file`).
- `KeyringStore` uses `keyring` with service `things-cli` and usernames
  `access_token`/`refresh_token`/`family_id`/`bridge_url`/`auth_url` (values stored as
  individual keyring entries to match the design table).
- `FileStore` writes `~/.config/things-cli/credentials.json` with mode `0600`.
- `detect_store(flag)` returns the right backend; if `--credential-store=file` is not set
  and no keyring backend is available, exits with a clear error message.
- `Credentials` dataclass with `save(store)` / `load(store)` / `clear(store)`.

**Bridge client (`client.py`)**
- `BridgeClient(credentials, store)`:
  - `get(path, params=None)` / `request(method, path, body=None)` — attaches
    `Authorization: Bearer <access_token>` and sends via `http.client`.
  - On 401 with `token_expired`: POST `<auth_url>/agent-auth/token/refresh`, update stored
    credentials, retry the original request once.
  - On 401 with `refresh_token_expired`: POST `<auth_url>/agent-auth/token/reissue`
    (blocks on server-side JIT approval), then retry. On 403 `reissue_denied` or
    `family_revoked`, bail with a friendly error.
  - Returns parsed JSON payload.
- HTTP errors map to typed exceptions (`BridgeUnauthorized`, `BridgeForbidden`,
  `BridgeUnavailable`) consumed by the CLI to produce clean exits.

**Config (`config.py`)**
- Minimal; mostly just paths. Most runtime config lives in the credential store (bridge
  URL, auth URL). `--config-dir` override for tests.

**CLI (`cli.py`)**
- argparse with subcommands described above. Each command calls `BridgeClient.get(...)` and
  passes the JSON payload through `output.py` to render either a human-readable table or
  raw JSON.
- `things-cli login` takes `--bridge-url`, `--auth-url`, `--access-token`, `--refresh-token`,
  `--family-id` (all required except `--family-id`, which is optional and displayed by
  `status`). Writes to the selected credential store.
- `things-cli logout` clears all keys from the selected store.
- `things-cli status` prints currently stored metadata (never the secret values themselves —
  prints a `<set>` indicator instead).

**Output (`output.py`)**
- `print_todos(todos, json_flag)` / `print_projects(...)` / `print_areas(...)`.
- Text format: compact tabular output to match `agent-auth token list`.

## Scope allocation

All bridge reads require `things:read`, which is already listed in `design/DESIGN.md`. No new
scopes are introduced.

## Testing strategy

Unit tests in `tests/`:

- `test_things_bridge_models.py` — dataclass round-tripping, None handling.
- `test_things_bridge_things.py` — fake `AppleScriptRunner` asserts the emitted AppleScript
  contains the expected filters (list id, project id, area id, tag, status); canned TSV
  parses into expected dataclasses, including `missing value` → `None` and tabs/newlines
  escaping.
- `test_things_bridge_authz.py` — mock `http.client` to simulate auth responses and assert
  the mapped exceptions.
- `test_things_bridge_server.py` — spin up the server with a fake `ThingsClient` and fake
  authz, exercise each route via `http.client`, including 401/403/502 cases.
- `test_things_cli_credentials.py` — `FileStore` mode bits, `KeyringStore` via
  in-memory mock keyring fixture.
- `test_things_cli_client.py` — mock HTTP transport: happy path, 401→refresh→retry,
  refresh-expired→reissue→retry, reissue denied.
- `test_things_cli_cli.py` — argparse smoke tests for each subcommand, `--json` output shape.

`conftest.py` gains fixtures: `fake_applescript_runner`, `fake_bridge`, `tmp_credential_store`.
The existing `mock_keyring` fixture is generalised to also cover `things_cli.credentials`.

Function-coverage markers (`@pytest.mark.covers_function(...)`) are added for the new leaf
functions — deferred where the existing code has no markers either, but at minimum for:
`Send Bridge Request`, `Auto Refresh Token`, `Store CLI Credentials`, `Handle App Commands`,
`Display Results`, `Delegate Token Validation`, `Execute External System Interaction`,
`Serve Bridge HTTP API`.

## Documentation updates

- `README.md`: add Things-specific usage section under Usage showing the login +
  read-only commands.
- `design/DESIGN.md`: add a "Things bridge" subsection under "Components" naming the bridge
  port (9200), the read-only endpoints, and the scope mapping. Note that write ops are
  deferred.
- `design/functional_decomposition.yaml`: rename the generic `Example App Bridge` /
  `Example App CLI` branches to read `Things Bridge` / `Things CLI` (keeping the same
  leaf-function names so product allocation stays valid). Do NOT add new leaf functions —
  the existing ones (`Delegate Token Validation`, `Execute External System Interaction`,
  `Serve Bridge HTTP API`, `Send Bridge Request`, `Auto Refresh Token`, `Store CLI
  Credentials`, `Handle App Commands`, `Display Results`) already describe this work.
- `design/product_breakdown.yaml`: replace the `example-app-bridge` and `example-app-cli`
  component entries with `things-bridge` and `things-cli` respectively, keeping the same
  function allocation.
- Regenerate `design/*.csv`/`*.md`/`*.d2`/`*.png`/`*.svg` from the YAMLs as a follow-up
  step using `scripts/verify-design.sh` to confirm the allocation still balances.

## Risks and mitigations

- **macOS-only runtime** — bridge can only be *used* on macOS. Mitigation: the
  `AppleScriptRunner` abstraction means all tests run on Linux, and the bridge's server
  code is OS-agnostic. A one-line README note records the requirement.
- **Localisation** — list names differ on non-English Things installs. Mitigation: use
  stable `list id` values (per THINGS.md §4), never localised names.
- **`missing value` everywhere** — AppleScript returns `"missing value"` for unset optional
  properties. Mitigation: the TSV parser treats that exact literal as `None`. Unit tests
  cover each model.
- **Tab / newline in todo notes** — would break the TSV framing. Mitigation: AppleScript
  helper replaces `\t` with `\u241e` and `\n` with `\u241f` before emitting; parser
  reverses.
- **Auto-refresh loops** — CLI must only retry once per request to avoid infinite loops
  (e.g. clock skew). Explicit single-retry flag in the client.
- **Token leakage via logs** — the bridge must never log the raw bearer token. The server
  logger is already silenced (`log_message = pass`), same pattern applied here.

## Implementation order

1. Plan committed (this document).
2. Fetch `main` (already up to date).
3. `things_bridge` models + things client + authz + server (test per module as we go).
4. `things_bridge` CLI entrypoint.
5. `things_cli` credentials + client (test per module).
6. `things_cli` CLI entrypoint + output formatters.
7. `pyproject.toml` script entries.
8. Full test run.
9. Documentation + design updates.
10. Wire `scripts/test.sh` into GitHub Actions so the new tests run in CI.
11. Post-implementation verification: diff shipped bridge/CLI behaviour against
    `design/DESIGN.md`, reconcile any drift.
12. Remove the completed "Example app bridge (deferred)" and "Example app CLI
    (deferred)" entries from `TODO.md`.
13. `/simplify` pass, subagent review pass.
14. Commit, push, open PR.
