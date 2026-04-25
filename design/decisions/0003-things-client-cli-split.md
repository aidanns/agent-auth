<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0003 — Split Things clients into sibling CLIs

## Status

Accepted — 2026-04-18.

Supersedes the `--fake-things` in-process selection mechanism introduced
in ADR 0001; the underlying justification for a client-level fake (as
opposed to a runner-level fake) still stands and is not revisited here.

## Context

ADR 0001 introduced `FakeThingsClient` in `src/things_bridge/fake.py`
and selected it at startup via `things-bridge serve --fake-things[=PATH]`.
The bridge process therefore shipped both the production AppleScript
client and the test fake. The trust story weakened on two axes:

1. The same process that holds the authz delegation role (bearer
   tokens, agent-auth URL, a network listener) now loads a test-only
   fixture YAML parser and an in-memory fake Things store. A
   misconfiguration or an argv injection that set `--fake-things`
   could cause the bridge to serve synthetic data to a production
   caller without any wire-level diagnosis being possible.
2. `things_bridge` ended up with three unrelated responsibilities —
   HTTP + authz, AppleScript generation / parsing, and test-fake
   plumbing — that only shared a process because of historical
   accident. This made the bridge noticeably harder to change safely.

Issue #61 asked us to remove the fake from the bridge. The issue's
original proposal was a fake `osascript` binary on `$PATH`. We
considered it and chose a different path because `osascript` is not
the boundary we want to mock — the `ThingsClient` Protocol is. Mocking
the AppleScript-interpreter-level boundary would recreate the coupling
that ADR 0001 already rejected.

## Considered alternatives

### Fake `osascript` on `$PATH`

The bridge keeps its AppleScript generation and parsing. A shim binary
is placed earlier on `$PATH` in tests and returns canned TSV.

**Rejected** because:

- Same reasons ADR 0001 rejected a runner-level fake: couples the fake
  to the exact AppleScript strings the bridge emits today, and rewrites
  the fake every time the AppleScript is refactored.
- Relies on `$PATH` ordering, which is brittle in CI and hostile to
  parallel test runs that want distinct fixtures per test.

### Keep `--fake-things` but move it behind a strictly developer-only

build flag (e.g. an extras install, a separate package entry point)

The bridge still loads the fake in-process; the only change is making
it harder to activate accidentally.

**Rejected** because the fundamental issue is process-level trust
boundary, not activation ergonomics. Keeping the fake in-process means
every security-sensitive refactor of the bridge has to reason about
two client selection paths, and the bridge still needs YAML fixture
parsing inside the secret-holding process.

### Split Things client into sibling CLIs (chosen)

Move both the production client and the test fake out of `things_bridge`
entirely and into their own binaries. The bridge shells out to a
configured command per request. Two clients exist:

- `things-client-cli-applescript` — ships with the dist, talks to
  Things 3 via `osascript`. No authentication (trust boundary is that
  the local user ran it).
- `things-client-cli-fake` — test-only, reads a YAML fixture from
  disk. Lives under `tests/things_client_fake/` and is invoked as
  `python -m things_client_fake`. Not packaged into the sdist
  or wheel.

The bridge's `things_client_command: list[str]` config field (default
`["things-client-cli-applescript"]`) picks which argv prefix to spawn
per request. Integration/e2e tests override to the fake.

## Decision

Adopt the sibling-CLI split.

### Subprocess contract

- **argv** — `<things_client_command> <resource> <verb> [flags]`, e.g.
  `things-client-cli-applescript todos list --status open`.
- **stdout** — JSON, always, for both success and error:
  - success: `{"todos": [...]}`, `{"todo": {...}}`, `{"projects": [...]}`,
    etc.
  - error: `{"error": "<code>"}` where `<code>` is one of
    `not_found`, `things_permission_denied`, or `things_unavailable`.
    An optional `detail` string carries an operator-only message.
- **exit code** — 0 on success, non-zero on error. The JSON body is
  authoritative for the error *kind*; the exit code only
  distinguishes success from failure.
- **stderr** — operator diagnostics only. The bridge captures it and
  forwards it verbatim to its own stderr. HTTP response bodies never
  include stderr content.

The shared argparse parser (including choice constraints on `--status`)
lives in `src/things_client_common/cli.py` and is exercised by tests
against both CLIs, so the two implementations cannot drift.

### Code layout

- `src/things_models/` — dataclasses (`Todo`, `Project`, `Area` with
  `to_json` / `from_json`), the `ThingsClient` Protocol, the
  `ThingsError` hierarchy, and `VALID_STATUSES` / `validate_status`.
  Depended on by all three packages.
- `src/things_client_common/` — shared argparse surface and the
  `run_cli` dispatcher used by both client CLIs.
- `src/things_client_applescript/` — AppleScript runner, TSV parser,
  `ThingsApplescriptClient`, and its CLI entrypoint.
- `tests/things_client_fake/` — fixture loader, `FakeThingsClient`,
  `FakeThingsStore`, and its CLI entrypoint (not shipped).
- `src/things_bridge/things_client.py` — `ThingsSubprocessClient`, the
  only place the bridge reasons about the subprocess protocol.

### Configuration

`Config` gains `things_client_command: list[str]` (default
`["things-client-cli-applescript"]`) and retains
`request_timeout_seconds`, now used as the subprocess timeout. It
defaults to 35s — kept above the shipped AppleScript CLI's own 30s
osascript timeout so the child can surface a structured timeout
envelope on stdout before the bridge kills it. The old `osascript_path`
field is removed from the bridge's config — it belongs to the
AppleScript CLI and is read there from `--osascript-path` /
`THINGS_CLIENT_OSASCRIPT_PATH`. The developer-only `--fake-things`
flag is deleted along with the banner that announced it.

### Error taxonomy (HTTP-facing)

The JSON envelope is authoritative: if stdout contains `{"error": ...}`
the bridge raises that error regardless of the exit code (a buggy CLI
reporting rc=0 with an error body still fails closed). The exit code
only disambiguates success from failure when the envelope is absent.

| Subprocess signal                          | Raised as               | HTTP status |
| ------------------------------------------ | ----------------------- | ----------- |
| `error=not_found` on stdout                | `ThingsNotFoundError`   | 404         |
| `error=things_permission_denied` on stdout | `ThingsPermissionError` | 503         |
| `error=things_unavailable` on stdout       | `ThingsError`           | 502         |
| non-zero exit, no error body               | `ThingsError`           | 502         |
| empty/non-JSON/non-object stdout           | `ThingsError`           | 502         |
| subprocess timeout                         | `ThingsError`           | 502         |
| `FileNotFoundError` (binary missing)       | `ThingsError`           | 502         |
| argparse misuse (exit 2, empty stdout)     | `ThingsError`           | 502         |

## Consequences

### Security

- **Trust boundary reduction (positive).** The bridge process no
  longer contains AppleScript generation, TSV parsing, YAML fixture
  loading, or an in-memory fake store. A vulnerability in the YAML
  loader or fixture schema can no longer affect the process that
  holds authz-delegation state.
- **New subprocess trust relationship.** The bridge now trusts the
  stdout of a process it spawned from a command line it controls. The
  `things_client_command` is validated at config load time and cannot
  be set from HTTP. The subprocess runs as the same local user, so no
  privilege boundary is crossed.
- **Subprocess environment is allowlisted.** The client CLI is spawned
  with an explicit `env=` built from `SUBPROCESS_ENV_EXACT_ALLOWLIST`
  (`PATH`, `HOME`, `LANG`, `TZ`) and `SUBPROCESS_ENV_PREFIX_ALLOWLIST`
  (`LC_*`, `THINGS_CLIENT_*`). Secrets the operator has in the bridge
  env — agent-auth bearer tokens, unrelated API keys, future
  signing-key env fallbacks — therefore never reach the child. The
  allowlist is tested in `test_things_subprocess_client.py`; extending
  it (e.g. `TMPDIR`, `__CFPREFERENCES_*`) requires evidence that an
  osascript execution path actually needs the variable, not
  speculative inclusion. Tracked in #68.
- **Information disclosure.** Subprocess stderr continues to be
  scrubbed from HTTP response bodies and only forwarded to the
  bridge's own stderr for operator diagnostics. The bridge never
  reads subprocess stderr into a response body.
- **Bounded stderr capture.** Stderr is forwarded to the bridge's
  own stderr line-by-line as the child writes it, and only a fixed
  tail (64 KiB) is retained for the timeout-diagnostic line. A
  misbehaving or compromised client CLI that streams multi-megabyte
  diagnostics therefore cannot pin bridge memory across the live
  subprocess, even under the `ThreadingHTTPServer`'s per-thread
  request model. Stdout remains unbounded because the JSON envelope
  must be parsed in full; envelopes are small by construction and
  malformed/oversize bodies still fail closed through the existing
  error-taxonomy entries.
- **STRIDE deltas.** Spoofing / Tampering: mitigated by the bridge
  controlling the argv and validating `things_client_command` at
  config load. Repudiation: subprocess invocations are logged at
  operator-diagnostic level on stderr. Info disclosure: unchanged
  (stderr scrubbing). DoS: a hung subprocess is bounded by
  `request_timeout_seconds`; stderr capture is bounded to a fixed
  tail. Elevation: no privilege boundary crossed.

### Performance

- `osascript` invocations now cost one additional Python interpreter
  startup per request (on the order of ~50–100 ms). This is
  measurable but acceptable for a local developer tool and is
  dominated by `osascript`'s own startup in practice. If this ever
  matters for sustained workloads, a persistent AppleScript host
  (JXA daemon, `py-appscript`) can replace the one-shot CLI without
  changing the bridge's subprocess contract.
- For the fake CLI, per-call Python startup is the dominant cost,
  but the fake path is only exercised in integration/e2e tests, not
  in production.

### Testability

- The bridge's subprocess protocol has two orthogonal layers of
  coverage: unit tests in `test_things_subprocess_client.py` stub
  `subprocess.run` to assert argv construction and error mapping;
  integration tests in `test_things_bridge_e2e.py` run the fake CLI
  as a real subprocess and assert end-to-end behaviour including
  authz delegation.
- CLI-contract tests in `test_things_client_cli_contract.py` run
  the fake CLI as a real subprocess and assert the JSON envelope,
  exit code, and error body shape for every supported command.
- Parallel test runs can point each bridge at a per-test fixture
  file without contention, because the fixture path is a command-line
  argument rather than an environment variable or `$PATH` entry.

### Operational

- Operators diagnosing a stuck bridge see subprocess stderr on the
  bridge's stderr, prefixed with `things-client-cli-applescript:`
  (production path) or similar. Bridge-level logs carry the
  subprocess exit code, so the two layers are distinguishable.
- The CLIs are runnable directly for debugging without going through
  agent-auth or the bridge, e.g.
  `things-client-cli-applescript todos list --status open`.

## Follow-ups

- GitHub issue: **persistent AppleScript host** — a long-running
  `py-appscript` or JXA daemon that speaks the same JSON subprocess
  contract but avoids per-request `osascript` startup. Blocked on
  measuring whether the current setup is fast enough for the
  expected workload.
- GitHub issue: **non-macOS Things client** — if a future Linux
  Things client ever exists (Web-based or otherwise), it slots in
  as a third `things-client-cli-*` implementation without touching
  the bridge.
