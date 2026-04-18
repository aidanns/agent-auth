# Implementation Plan: Split Things clients into sibling CLIs

## Context

PR #53 introduced an in-process fake (`FakeThingsClient` in
`src/things_bridge/fake.py`) selected at startup via `things-bridge serve
--fake-things[=PATH]`. The bridge process now ships both the production
AppleScript client and the test fake, plus a YAML fixture loader and a
stderr banner whose only job is to flag that the fake is live. The trust
story weakens: the same process that holds authz delegation can, if
started with the wrong flag, serve synthetic data.

Issue #61 asks us to move the fake out of the bridge so the bridge has
no knowledge of test fakes. Its original proposal was a fake
`osascript` binary. We are taking a different route: move the Things
interaction itself out of the bridge. The bridge becomes an HTTP +
authz shim that shells out to a configured "things-client" CLI. Two
client CLIs exist:

- `things-client-cli-applescript` — ships with the dist, talks to
  Things 3 via `osascript`. No authentication (the trust boundary is
  that the user ran it locally).
- `things-client-cli-fake` — test-only, reads a YAML fixture from
  disk. No authentication. Lives under `tests/` so it is not shipped
  in the sdist/wheel.

The bridge's `things_client_command` config knob picks which command
line to spawn per request. Default points at
`things-client-cli-applescript`; integration/e2e tests override to the
fake.

## Approach

### Subprocess contract

The bridge spawns the configured command for each read request,
appending the sub-command and arguments that match the request:

```
<things_client_command> todos list [--list X] [--project X] [--area X] [--tag X] [--status X]
<things_client_command> todos show <id>
<things_client_command> projects list [--area X]
<things_client_command> projects show <id>
<things_client_command> areas list
<things_client_command> areas show <id>
```

The sub-command surface intentionally mirrors `things-cli`'s read
commands (minus login/logout/status and minus the `--json` flag —
machine-to-machine clients always emit JSON).

Output is JSON on stdout, always, for both success and error:

```json
# success
{"todos": [ {...}, {...} ]}
{"todo": {...}}
{"projects": [...]}
{"project": {...}}
{"areas": [...]}
{"area": {...}}

# error
{"error": "not_found"}
{"error": "things_permission_denied"}
{"error": "things_unavailable", "detail": "<stderr excerpt>"}
```

Exit code mirrors success/failure (0 on success, non-zero on error)
but the JSON body is authoritative — the bridge maps `error` strings
to the existing `ThingsError` / `ThingsNotFoundError` /
`ThingsPermissionError` taxonomy. Stderr is captured and forwarded to
the bridge's own stderr for operator diagnostics (mirrors today's
`AppleScriptRunner` stderr forwarding behaviour for non-zero exits).

Subprocess timeout is enforced by the bridge via
`subprocess.run(..., timeout=...)`; the same `request_timeout_seconds`
config field used today is reused for the subprocess timeout.

### New packages

- `src/things_client_applescript/`
  - `cli.py` — argparse entrypoint with `todos` / `projects` / `areas`
    subcommands.
  - `things.py` — the existing AppleScript runner, helpers, and
    `ThingsApplescriptClient` moved here verbatim. Bridge no longer
    imports it.
  - `models.py` — shared `Todo` / `Project` / `Area` dataclasses.
    (Discussed below — shared between all three packages.)
  - `errors.py` — `ThingsError` / `ThingsNotFoundError` /
    `ThingsPermissionError` moved here; bridge re-exports thin wrappers
    as needed for HTTP mapping.
  - Reads `osascript_path` from `--osascript-path` or
    `THINGS_CLIENT_OSASCRIPT_PATH` env var (default `/usr/bin/osascript`).
    The timeout is not set here — it is enforced by the parent (bridge).

- `tests/things_client_fake/` — test-only package (not under `src/`).
  - `cli.py` — argparse entrypoint with the same surface.
  - `store.py` — `FakeThingsStore`, `FakeThingsClient`,
    `load_fake_store` moved here.
  - Reads the fixture path from `--fixtures` or `THINGS_CLIENT_FIXTURES`
    env var. `--fixtures` omitted → empty store.
  - Invoked in tests as `[sys.executable, "-m",
    "tests.things_client_fake", ...]`.

### Model / error placement

`Todo`, `Project`, `Area` dataclasses and the `ThingsError` hierarchy
are currently in `src/things_bridge/{models,errors}.py`. They're used
by all three packages (applescript CLI, fake CLI, bridge). Extract
them into a small shared package — `src/things_models/` — with:

- `things_models/models.py` — dataclasses + `to_json` + a `from_json`
  loader used by the bridge to parse subprocess output back into
  dataclasses before JSON-ing them into HTTP responses.
- `things_models/errors.py` — `ThingsError`,
  `ThingsNotFoundError`, `ThingsPermissionError`.
- `things_models/status.py` — `VALID_STATUSES` and `validate_status`.

This keeps the bridge's authz-only errors (`AuthzError` and
subclasses) in `things_bridge.errors`, and leaves `things_bridge` with
nothing Things-specific beyond the subprocess runner.

### Bridge changes

- New `ThingsSubprocessClient` in `src/things_bridge/things_client.py`
  implementing the existing `ThingsClient` Protocol (kept for HTTP
  handler typing). It runs the configured command, parses JSON,
  rehydrates dataclasses from the shared `things_models`, and
  maps `error` strings to the corresponding exceptions.
- `Config` loses `osascript_path`, gains
  `things_client_command: list[str]` with default
  `["things-client-cli-applescript"]`.
- `request_timeout_seconds` is re-purposed as the subprocess timeout.
- `cli.py` loses `--fake-things` and everything that imports
  `things_bridge.fake`.
- `things_bridge/fake.py` is deleted.
- `things_bridge/things.py` is deleted (AppleScript code moves to the
  applescript CLI).
- `things_bridge/models.py` is deleted (moves to `things_models`).
- `things_bridge/errors.py` keeps only the `Authz*` hierarchy and
  re-exports `ThingsError` from `things_models` for backwards-compat
  with server.py's mapping code, or server.py is updated to import
  from `things_models` directly. (Will pick one during implementation
  — the simpler of the two.)

### Packaging

`pyproject.toml`:

- New console script `things-client-cli-applescript =
  "things_client_applescript.cli:main"`.
- Fake CLI is NOT registered as a console script (lives under
  `tests/`, invoked via `python -m tests.things_client_fake`).
- `things_models` package added to find.
- Bridge keeps its `things-bridge` console script but its source is
  slimmed down.

`scripts/`:

- New `scripts/things-client-applescript.sh` mirroring the pattern of
  the existing wrapper scripts. This gives users a simple way to run
  the client CLI directly without going through the bridge.

### Error taxonomy (HTTP-facing)

Unchanged from today:
- `not_found` → 404
- `things_permission_denied` → 503
- `things_unavailable` → 502

The bridge continues to scrub subprocess stderr from the HTTP response
body (host-info leak risk) while forwarding it verbatim to the
bridge's own stderr. That behaviour lives in
`ThingsSubprocessClient`, replacing the equivalent code in the old
`AppleScriptRunner`.

### Tests

- `tests/test_things_bridge_fake.py` — port the in-process-fake unit
  tests to `tests/test_things_client_fake.py`, testing
  `FakeThingsClient` / `load_fake_store` via their Python APIs in
  `tests.things_client_fake`. Add a thin subprocess test that exercises
  the `python -m tests.things_client_fake` entry to confirm the JSON
  contract.
- `tests/test_things_bridge_things.py` — move to
  `tests/test_things_client_applescript_things.py`; same `osascript`
  stub pattern, just under the new package path. Keep its `covers_function`
  assignments — they now cover the applescript CLI's AppleScript
  generation.
- `tests/test_things_bridge_e2e.py` — keep, but switch from
  constructing `FakeThingsClient` in-process to building a
  `ThingsSubprocessClient` pointed at `python -m tests.things_client_fake`
  with a fixture path. The bridge under test spins a real subprocess
  per request.
- New `tests/test_things_client_cli_contract.py` — exercises the
  JSON contract directly by running both CLIs as subprocesses and
  asserting output shape.
- `tests/test_things_bridge_things_client.py` — unit-test
  `ThingsSubprocessClient` against a stub subprocess runner (inject
  a fake `subprocess.run` via dependency injection, same pattern
  as today's `AppleScriptRunner` tests).

### Function decomposition updates

- Rename "Execute External System Interaction" → keep; it now
  describes what `things-client-cli-applescript` does.
- Rename "Serve Fake Things Client" → "Serve Fake Things Client CLI"
  (or equivalent) and re-scope to the out-of-process fake CLI.
- Add a new function "Spawn Things Client Subprocess" under Things
  Bridge covering the new bridge behaviour.

### Product breakdown updates

- Add a new component `things-client-cli-applescript`.
- Move "Execute External System Interaction" from `things-bridge` to
  `things-client-cli-applescript`.
- Add a new component `things-client-cli-fake` marked test-only.
- `things-bridge` keeps "Delegate Token Validation", "Serve Bridge
  HTTP API", and gains "Spawn Things Client Subprocess".

## Design and verification

- **Verify implementation against design doc** — diff the new subprocess
  behaviour and config surface against `design/DESIGN.md` and
  `design/THINGS.md`. Update both to describe the three-CLI topology.
- **Threat model** — the change reduces the bridge's attack surface
  (fake no longer loaded in the secret-holding process). Update
  `SECURITY.md` if it exists, or add a short note in the new ADR
  enumerating STRIDE deltas: Spoofing (the bridge now trusts subprocess
  stdout — mitigated by the bridge's control of argv and the
  `things_client_command` config). Tampering (same). Information
  disclosure (subprocess stderr continues to be scrubbed from HTTP
  responses).
- **Architecture Decision Records** — write ADR 0003 superseding the
  client-level-fake portion of ADR 0001 and the runner-level-fake
  rejection. Capture the new trade-off: coupling to the CLI argv
  surface instead of script text, in exchange for zero test-mode code
  in the bridge.
- **Cybersecurity standard compliance** — no new secret handling; the
  bridge's role under the chosen standard is unchanged.
- **Verify QM / SIL compliance** — unchanged; documentation updates
  only.

## Post-implementation standards review

- **coding-standards.md** — newtype the subprocess command
  (`ThingsClientCommand`), give all new procedures verb names, encode
  units (`subprocess_timeout_seconds`).
- **service-design.md** — verify the new config field follows the
  "defaults live in code, not on disk" rule, that file paths stay XDG
  compliant, and that the bridge's plugin-surface posture is better
  (not worse) than before.
- **release-and-hygiene.md** — confirm the README, CHANGELOG, and
  any SECURITY.md are updated; pin the new JSON contract as a public
  API.
- **testing-standards.md** — verify the new tests exercise public
  surfaces only (JSON contract, argv surface), not private
  internals.
- **tooling-and-ci.md** — confirm `scripts/test.sh`, `scripts/lint.sh`,
  and the Taskfile still cover the new packages without changes
  (pytest discovery is unchanged; lint picks up `src/**`).

## Rollout

Single PR. The change is atomic — the old `--fake-things` path and
`things_bridge.fake` module disappear in the same commit that adds the
new CLIs, so there is no intermediate state where both exist.
