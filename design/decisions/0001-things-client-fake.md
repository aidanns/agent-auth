# ADR 0001 — Client-level fake for things-bridge

## Status

Accepted — 2026-04-18.

## Context

`things-bridge` serves the Things 3 read API by emitting AppleScript to
`osascript` and parsing its TSV output (see `src/things_bridge/things.py`
and `design/THINGS.md`). The whole chain (bridge + things-cli +
agent-auth) is therefore impossible to exercise end-to-end on Linux: the
bridge fails at the first request because `/usr/bin/osascript` is absent
and there is no Things 3 app to talk to.

We need the stack exercisable in CI and in local Linux devcontainers so
that:

1. Regressions in HTTP behaviour, authz delegation, and JSON shapes are
   caught without access to a Mac.
2. A Linux devcontainer can run `things-bridge` against seeded fixtures
   while developing `things-cli` against the real HTTP surface.

## Considered alternatives

### Runner-level fake (faking `osascript` execution)

Intercept `AppleScriptRunner.run()` (or the subprocess call it makes) and
return hand-crafted TSV for each script shape the client emits. This
would exercise the AppleScript generation and the TSV parser in
addition to the HTTP layer.

**Rejected** because:

- An actual AppleScript interpreter for Linux does not exist as
  open-source. BushelScript (the closest candidate) is macOS-only — it
  depends on Apple Events, which aren't available on Linux.
- That leaves only hand-rolled regex matching on the emitted script
  text. The result is pinned to the exact string shapes
  `ThingsApplescriptClient` emits today; any refactor of the
  AppleScript generator forces rewriting the fake. Two layers that
  have no other reason to be coupled become coupled.
- The AppleScript-generation and TSV-parsing logic is already covered
  directly by `tests/test_things_bridge_things.py`, so the marginal
  value of running it against a synthetic TSV stream is low.

### Client-level fake (chosen)

Introduce a `ThingsClient` Protocol capturing the six methods the
bridge actually uses, implement a `FakeThingsClient` backed by a
`FakeThingsStore` (in-memory lists of `Todo` / `Project` / `Area`), and
select it from the CLI via `--fake-things[=<fixture-path>]`.

- Keeps coupling inside the Things 3 client boundary (where a fake
  already belongs).
- Works with the real `things-bridge` binary — the HTTP layer, authz
  delegation, and `things-cli` all run unchanged.
- Easy to seed: YAML fixtures express todos/projects/areas directly.

## Decision

Adopt the client-level fake. Introduce
`ThingsClient` as a `typing.Protocol` covering
`list_todos` / `get_todo` / `list_projects` / `get_project` /
`list_areas` / `get_area`. The existing
`ThingsApplescriptClient` becomes one implementation; the new
`FakeThingsClient` (in `src/things_bridge/fake.py`) is a second.
`things-bridge serve --fake-things[=PATH]` selects it and emits a
stderr banner at startup so the fake is never mistaken for the real
client.

### `list_id` handling

The real AppleScript client delegates list semantics (e.g.
`TMTodayListSource`) to Things 3 itself. We can't reproduce that
truthfully in Python. Options considered:

1. Ignore `list_id` and return every todo. Loses the ability to test
   list-scoped flows.
2. Match `list_id` against a sidecar membership map on the store.

Chose option 2: `FakeThingsStore` carries a
`list_memberships: dict[str, set[str]]` keyed by list id with values
of todo ids. Fixture YAML grows an optional `list_memberships`
top-level key. The real client is unaffected — the sidecar only
exists inside the fake.

## Consequences

- Linux devcontainer e2e becomes feasible: `tests/test_things_bridge_e2e.py`
  spins up real agent-auth + things-bridge pair over HTTP with
  `FakeThingsClient` seeded from fixtures and exercises the full read
  path including authz delegation, filter forwarding, and 4xx/5xx
  mapping.
- AppleScript generation and TSV parsing remain covered by the existing
  `tests/test_things_bridge_things.py` unit tests, which already stub
  `AppleScriptRunner.run()` with sample TSV strings — not by the
  end-to-end suite.
- Real-AppleScript coverage (Things 3 installed, `osascript` executing
  the generated scripts, TCC-approved automation permission) is
  deferred to a macOS-runner-based workflow — tracked as a follow-up
  issue, blocked on how to install / license Things 3 on a GitHub
  runner.
- `--fake-things` must never be mistaken for a "headless mode" fit for
  production traffic. The stderr banner and help text both warn; the
  flag is a developer-only tool and is not configurable via the config
  file (consistent with `service-design.md` "defaults live in code").

## Follow-ups

- GitHub issue: **e2e tests with real Things 3 via GitHub Actions macOS
  runner** — stand up a nightly/labelled workflow that runs
  `tests/test_things_bridge_e2e.py` against the real
  `ThingsApplescriptClient`, seeded via AppleScript "make new to do"
  and torn down afterwards.
- GitHub issue: **minimise AppleScript logic in things-bridge, push
  filtering and shaping into Python** — the less AppleScript shapes the
  data, the closer the fake and real paths become, and the smaller the
  macOS-specific surface we need to cover.
