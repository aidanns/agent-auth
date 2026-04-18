# Implementation Plan: Client-level fake for things-bridge

## Context

`things-bridge` shells out to macOS `osascript` to talk to Things 3. That
makes the whole stack (bridge + things-cli + agent-auth) impossible to
exercise end-to-end inside a Linux devcontainer: the bridge fails at the
first request because `/usr/bin/osascript` is absent and there is no Things
app to talk to.

We want a drop-in fake that lets the real `things-bridge` binary serve
traffic in Linux against a synthetic Things-like store, so we can stand up
and exercise the full HTTP stack (agent-auth + things-bridge + things-cli)
in CI and in local Linux devcontainers.

A runner-level fake (faking `osascript` execution) was considered but
rejected: we can't write a real AppleScript interpreter for Linux (no such
thing exists open-source — BushelScript is macOS-only because Apple Events
are macOS-only), so the runner-level "fake" would be hand-rolled regex
matching on script shapes. That pins the fake to the exact script strings
`ThingsApplescriptClient` emits, and couples two layers that have no other
reason to be coupled. Going client-level is simpler, less brittle, and the
AppleScript-generation / TSV-parsing it bypasses is already well covered
by unit tests in `tests/test_things_bridge_things.py`.

The tradeoff is that real AppleScript-driven end-to-end coverage requires
a macOS runner. That's tracked as a follow-up GitHub issue (see below),
not part of this change.

## Approach

### Where the fake plugs in

`ThingsBridgeServer.__init__` already accepts a duck-typed `things`
argument — the server only calls `list_todos`, `get_todo`, `list_projects`,
`get_project`, `list_areas`, `get_area`. We introduce a `ThingsClient`
Protocol in `src/things_bridge/things.py` that captures that surface, mark
`ThingsApplescriptClient` as an implementation, and add a second
implementation `FakeThingsClient` backed by an in-memory store.

The existing `FakeThings` in `tests/test_things_bridge_server.py` is
structurally the same idea but lives in the test tree. The production
`FakeThingsClient` replaces it; unit tests are migrated to import from
`src/things_bridge/fake.py` so behaviour stays consistent.

### Public surface

New module `src/things_bridge/fake.py`:

- `FakeThingsStore` — dataclass with `todos: list[Todo]`,
  `projects: list[Project]`, `areas: list[Area]` plus a `list_memberships: dict[str, set[str]]` sidecar (list_id -> set of todo ids) for modelling
  Things' built-in smart lists. `__post_init__` builds id→object indexes.
- `FakeThingsClient(store: FakeThingsStore)` — implements the
  `ThingsClient` protocol:
  - `list_todos(*, list_id=None, project_id=None, area_id=None, tag=None, status=None)` — apply the same filter semantics the real client
    applies in AppleScript: `list_id` consults `list_memberships`;
    `project_id` / `area_id` filter by field equality; `tag` filters by
    `tag in tag_names`; `status` is validated against
    `{open, completed, canceled}` and applied last. Invalid status raises
    `ThingsError` (match real client).
  - `get_todo(todo_id)` / `get_project(project_id)` / `get_area(area_id)`
    — look up by id, raise `ThingsNotFoundError` on miss (match real
    client).
  - `list_projects(*, area_id=None)` / `list_areas()` — straightforward.
- `load_fake_store(path: str | os.PathLike) -> FakeThingsStore` — reads
  a YAML fixtures file (using the same `yaml.safe_load` the config
  module already uses) and builds the store. Tolerates missing optional
  dataclass fields.

Fixtures YAML (`examples/fake-things.yaml`):

```yaml
areas:
  - id: a1
    name: Personal
    tag_names: []
projects:
  - id: p1
    name: Q2 Planning
    area_id: a1
    area_name: Personal
    status: open
    tag_names: [P1]
todos:
  - id: t1
    name: Buy milk
    status: open
    project_id: p1
    project_name: Q2 Planning
    tag_names: [Errand]
list_memberships:
  TMTodayListSource: [t1]
```

### CLI wiring

`things-bridge serve --fake-things[=<path>]` in `src/things_bridge/cli.py`:

- Flag absent -> current behaviour (real `AppleScriptRunner` +
  `ThingsApplescriptClient`).
- Flag present, no value -> `FakeThingsClient(FakeThingsStore())` (empty
  store).
- Flag present, value -> `load_fake_store(path)` → `FakeThingsClient(...)`.

CLI flag only — no env var fallback and no config-file entry. The fake
is a developer tool, per `service-design.md` "defaults live in code".

On startup, emit a prominent stderr warning banner when the fake is
active so nobody accidentally runs the server against real traffic with
it on.

Flag name is `--fake-things` (not `--fake-applescript`) because the fake
is at the Things-client layer; the AppleScript layer is bypassed entirely.

### End-to-end test

The point of the e2e test is to exercise the **full** stack, including
the agent-auth / things-bridge interaction. A stubbed-out `FakeAuthz`
would make the bridge's token-validation path untested in e2e and is
exactly the regression surface this test needs to cover. The e2e test
therefore stands up a real `agent-auth` server in-process and points
things-bridge at it via the real `AgentAuthClient`.

Reuses the existing agent-auth test fixtures (`tmp_dir`, `signing_key`,
`encryption_key` — see `tests/test_server.py`) and the helpers
`_start_server` / `_create_test_tokens` / `_post` / `_get`. Extract
those into `tests/conftest.py` (or a shared module) so both the
existing agent-auth integration tests and the new things-bridge e2e
can share them without duplication.

New file `tests/test_things_bridge_e2e.py`:

- Pytest fixture spins up the full stack in-process:
  1. Start `AgentAuthServer` on port 0 with an isolated `tmp_dir` data
     dir, test signing/encryption keys, and the existing
     `AutoApprovePlugin` stub (prompt-tier scopes not exercised here;
     everything is allow-tier).
  2. Create a real `things:read=allow` token family directly against
     the in-memory store via `_create_test_tokens`.
  3. Start `ThingsBridgeServer` on port 0 with a real
     `AgentAuthClient(auth_url=<agent-auth URL>)` and a
     `FakeThingsClient(store_from_fixture)`.
- Drives real HTTP via `urllib` against the things-bridge endpoints
  with the real access token in the `Authorization: Bearer …` header.
  This proves the full validation path (signature verify, expiry
  check, scope check, agent-auth round-trip) executes end-to-end.
- Coverage:
  - Happy path: list/get for todos/projects/areas,
    `project`/`area`/`tag`/`status` filters, `list_id` filter against
    `list_memberships`, free-form `\t` / `\n` in `notes` round-trips
    through the JSON response, 404 for missing Things ids.
  - Authz path: missing token -> 401, wrong-scope token
    (`outlook:read=allow`) -> 403, expired access token -> 401,
    revoked family -> 401, agent-auth server unreachable ->
    502 (`authz_unavailable`).

Also `tests/test_things_bridge_fake.py` — unit tests on
`FakeThingsClient` in isolation: filter semantics, status validation,
not-found behaviour.

The existing `FakeThings` in `tests/test_things_bridge_server.py` is
replaced by the production `FakeThingsClient` (via an import change in
that test file — no behaviour change expected). The existing `FakeAuthz`
in that same file stays — it's still the right tool for the bridge's
*unit* tests, which shouldn't depend on agent-auth internals. Only the
e2e test uses the real authz stack.

### Follow-up GitHub issues

Two issues will be opened immediately after this change lands.

**Issue 1 — e2e tests with real Things 3 via a macOS runner**

> **Title:** e2e tests with real Things 3 via GitHub Actions macOS runner
>
> **Body:** The client-level fake introduced in #<this PR> lets us
> exercise the full HTTP stack in Linux, but doesn't cover real
> AppleScript generation, `osascript` execution, or real Things.app
> behaviour.
>
> Add a CI workflow that runs on `macos-latest` (or a self-hosted Mac
> runner), installs Things 3 from a pre-provisioned `.dmg`, grants
> Automation permission to the runner's `osascript` process, seeds a
> known dataset, and runs the same `tests/test_things_bridge_e2e.py`
> suite against the *real* `ThingsApplescriptClient`. Gate the workflow
> on a label (`e2e-things`) or a nightly schedule so we don't burn
> macOS-runner minutes on every PR.
>
> Blockers to investigate first:
>
> - Things 3 distribution: can we install a licensed copy on a GH
>   runner? (May need a self-hosted runner on a Mac mini.)
> - Automation permission: TCC DB pre-seeding vs interactive prompt.
> - Dataset seeding: `make new to do` before the test runs; tear down
>   via `empty trash` + `log completed now` after.

**Issue 2 — move logic out of AppleScript into Python**

> **Title:** minimise AppleScript logic in things-bridge, push filtering
> and shaping into Python
>
> **Body:** `ThingsApplescriptClient` currently pushes filtering
> (`whose status is open`, `to dos of tag "X"`, status-text branching)
> and row-shaping (TSV framing, escape sequences, ISO-date
> conversion) into the AppleScript it emits. AppleScript is hard to
> unit-test, can't be run on the CI Linux workers, and has a very
> limited standard library.
>
> Refactor the client so the AppleScript side is as close to a dumb
> data dump as possible: return every field of every requested object
> as raw AppleScript values (or JSON via `_private_experimental_ json` where available), and do filtering, tag-splitting, date
> parsing, and missing-value handling in Python on the parsed result.
>
> Benefits:
>
> - Shrinks the attack/injection surface (fewer caller-supplied
>   strings end up inside AppleScript).
> - Makes unit tests of the filter and shape logic trivial — they
>   run on whatever data-shape the fake/real AppleScript returns.
> - Reduces the lock-step coupling between the AppleScript emitter
>   and any future fake runner (should we ever revisit that).
>
> Out of scope for the fake-ThingsClient change; tracked so it doesn't
> get lost.

### ADR

`design/decisions/0001-things-client-fake.md` — records:

- Runner-level vs client-level fake (and why we didn't try to interpret
  AppleScript on Linux).
- `list_id` sidecar membership model.
- Deferred coverage (real-Things e2e) tracked in the follow-up issue.

## Files to add / modify

**Add:**

- `src/things_bridge/fake.py` — `FakeThingsStore`, `FakeThingsClient`,
  `load_fake_store`.
- `examples/fake-things.yaml` — seed fixtures for devcontainer use.
- `tests/test_things_bridge_fake.py` — unit tests for the fake client.
- `tests/test_things_bridge_e2e.py` — end-to-end through HTTP.
- `design/decisions/0001-things-client-fake.md` — ADR.
- `plans/things-client-fake.md` — this plan.

**Modify:**

- `src/things_bridge/things.py` — add `ThingsClient` Protocol (covers
  the six methods the server consumes); no change to
  `ThingsApplescriptClient` behaviour.
- `src/things_bridge/server.py` — annotate `things: ThingsClient`
  (Protocol), no behaviour change.
- `src/things_bridge/cli.py` — add `--fake-things[=<path>]` and the
  startup banner.
- `tests/test_things_bridge_server.py` — replace local `FakeThings` with
  `from things_bridge.fake import FakeThingsClient, FakeThingsStore`.
- `README.md` — new subsection under `things-bridge` documenting the
  Linux-devcontainer workflow.
- `CLAUDE.md` — one-line mention of the flag under "Project-specific
  notes".
- `design/DESIGN.md` — note the test-only fake and its scope.
- `design/functional_decomposition.yaml` / `.md` / `.d2` — add a leaf
  under `things-bridge` for `Fake Things Client` so function-to-test
  traceability holds.
- `tests/conftest.py` — promote agent-auth's existing `tmp_dir` /
  `signing_key` / `encryption_key` fixtures and the `_start_server`
  / `_create_test_tokens` helpers here so the new e2e test can reuse
  them without depending on `tests/test_server.py` as a sibling
  import. The existing `FakeAuthz` stays in
  `tests/test_things_bridge_server.py` (it's for unit tests, not e2e).

**GitHub issues to open (separately from the PR):**

1. "e2e tests with real Things 3 via GitHub Actions macOS runner" —
   body as drafted above.
2. "minimise AppleScript logic in things-bridge, push filtering and
   shaping into Python" — body as drafted above.

## Post-implementation review (per plan-template.md)

- **Verify against design docs** — confirm `DESIGN.md` / functional
  decomposition reflect the fake and that it's scoped to testing only.
- **Coding standards** — Protocol defined with explicit verb-named
  methods; `FakeThingsStore` fields typed; no raw tuples.
- **Service design** — defaults remain in code, XDG untouched, plugin
  trust boundary not crossed (fake is first-party code in-process).
- **Testing standards** — e2e drives full HTTP lifecycle; bind to port 0;
  function-to-test allocation refreshed via
  `scripts/verify-function-tests.sh`.
- **Release and hygiene** — no public API surface change beyond the new
  `fake` module (documented as test/dev-only in its docstring).
- **Tooling and CI** — tests run under existing `pytest`; no new
  runners.

## Verification

Inside the Linux devcontainer:

```bash
source ".venv-$(uname -s)-$(uname -m)/bin/activate"
pip install -e ".[dev]"

# Unit + e2e tests pass
pytest tests/test_things_bridge_fake.py tests/test_things_bridge_e2e.py -v

# Full stack runs manually
agent-auth serve &
things-bridge serve --fake-things=examples/fake-things.yaml &
things-cli login --bridge-url http://127.0.0.1:9200 \
    --auth-url http://127.0.0.1:9100 --family-id <id>
things-cli todos list
things-cli todos list --list TMTodayListSource
things-cli todos show t1
things-cli projects list
things-cli areas list
```

Each of the last five commands returns JSON/TTY output seeded from
`examples/fake-things.yaml`, with no `osascript: command not found` or
`ThingsPermissionError` anywhere in the logs.
