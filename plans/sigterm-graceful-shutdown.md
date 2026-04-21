<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Implementation Plan: SIGTERM Graceful Shutdown

## Context

Closes #154.

Both `agent-auth serve` and `things-bridge serve` currently only catch
`KeyboardInterrupt`. Docker sends `SIGTERM` when stopping a container,
which the Python process does not handle, so every container teardown
waits out the full `stop_grace_period` before Docker resorts to
`SIGKILL`. PR #152's integration-harness instrumentation measured this
at ~10.4s per `compose.stop` in the `things-bridge` suite.

Beyond test wall-time, graceful shutdown is a production-hardening
property: it lets existing requests complete cleanly on rollouts,
ensures pending audit log entries flush before exit, and keeps the
sqlite token store from relying on journal recovery.

## Functional decomposition updates

Add one leaf function under each service's HTTP API group:

- Under `HTTP API` (agent-auth): **Handle Graceful Shutdown** —
  install a SIGTERM handler that stops accepting new connections,
  drains in-flight requests within a bounded deadline, and closes
  audit/store handles before exit.
- Under `Things Bridge`: **Handle Bridge Graceful Shutdown** — same,
  for the bridge's HTTP API.

These names follow the existing `Serve <X> Endpoint` / `Handle <X> Command` verb-phrase pattern.

## Design and verification

- **Verify against design doc** — `design/DESIGN.md` does not currently
  document shutdown behaviour. Add a short *Graceful shutdown*
  subsection under each service's *Runtime* section describing the
  SIGTERM handling, the deadline, and what gets flushed/closed.
- **Threat model (`SECURITY.md`)** — not a new threat surface. The
  handler does not accept external input and only affects shutdown
  sequencing. Add a one-line note under the resilience/availability
  section if one exists, otherwise skip.
- **ADR** — write `design/decisions/0018-graceful-shutdown.md`
  capturing: signal set handled (`SIGTERM` + `SIGINT`), shutdown
  sequence, why we spawn a watchdog thread that `os._exit(1)`s after
  the deadline (versus `signal.alarm` or a blocking join with timeout),
  and the `shutdown_deadline_seconds` config knob with default 5s
  (matches Docker's `stop_grace_period: 5s` in the test compose).
- **Cybersecurity standard compliance** — project follows NIST SSDF
  (ADR 0015). Shutdown correctness is adjacent to PS.3 (protect
  software integrity) — a forced kill mid-transaction could corrupt
  the WAL. Document this rationale in the ADR.
- **QM / SIL compliance** — no SIL claim; QM applies. Adding unit and
  integration-level tests covering the shutdown path meets
  `design/ASSURANCE.md` coverage obligations.

## File structure

No new source modules. Changes are confined to:

```
src/agent_auth/
    cli.py              # handle_serve — install signal handler
    server.py           # run_server — drain loop + resource close
    config.py           # add shutdown_deadline_seconds: int = 5
    store.py            # add close() that checkpoints + closes conns

src/things_bridge/
    cli.py              # serve path — install signal handler
    server.py           # run_server — drain loop
    config.py           # add shutdown_deadline_seconds: float = 5.0

tests/
    test_server_shutdown.py          # agent-auth handler tests
    test_things_bridge_shutdown.py   # bridge handler tests

design/
    DESIGN.md                               # Graceful shutdown subsection
    functional_decomposition.yaml           # add 2 leaf functions
    decisions/0018-graceful-shutdown.md     # ADR

plans/
    sigterm-graceful-shutdown.md            # this file
```

## Implementation

### 1. `TokenStore.close()`

Add a `close()` method that iterates every per-thread sqlite
connection, runs `PRAGMA wal_checkpoint(TRUNCATE)`, and closes the
connection. The store currently stashes one `sqlite3.Connection` per
thread in `threading.local()`, which is not iterable; switch to a
`weakref.WeakSet` of connections guarded by a lock so `close()` can
reach them all.

### 2. `run_server` — shutdown sequence

For both services the sequence is the same. Build a small helper
`_install_shutdown_handler(server, deadline_seconds, on_drain_timeout)`
that:

1. Registers a handler for `SIGTERM` and `SIGINT` on the main thread.
2. On signal: starts a daemon watchdog thread that `os._exit(1)`s
   after `deadline_seconds`, then spawns a second daemon thread
   calling `server.shutdown()` (can't run from the serving thread or
   `shutdown()` deadlocks).

`run_server` then:

1. Installs the handler.
2. Calls `server.serve_forever()`.
3. After it returns, calls `server.server_close()`. `ThreadingHTTPServer`
   with `daemon_threads=False` (default) and `block_on_close=True`
   (default) joins every active request thread inside `server_close()`.
   The watchdog cap guarantees a bounded overall wall-time.
4. Closes service-owned resources:
   - agent-auth: `store.close()`. (`AuditLogger` opens and closes the
     file per write with an `fsync` semantic already implied by
     `open('a').write().close()` on POSIX; no separate close is
     needed.)
   - things-bridge: nothing to close (no persistent handles).
5. Returns normally; `main()` falls through to a clean `exit(0)`.

### 3. Config

Add `shutdown_deadline_seconds` to both `Config` dataclasses. Name
carries the unit per `coding-standards.md`. Default 5; the test
compose's `stop_grace_period: 5s` is the budget the handler must fit
inside.

### 4. CLI entrypoints

No signal plumbing in `cli.py`; the handlers live in `run_server` so
in-process tests (which construct `AgentAuthServer` directly and call
`serve_forever` on a thread) do not see stray signal handlers. `cli.py`
stays unchanged beyond passing the config through.

## Test plan

Both suites are unit-level (in-process, no Docker). Issue
acceptance-criterion #3 (integration timing) is verified separately by
watching the `phase=compose_stop` log line added in #152 once both that
PR and this one have merged.

`tests/test_server_shutdown.py` — agent-auth:

- **`test_sigterm_stops_accepting_new_connections`** — start server
  on `port=0` in a subprocess, wait until it answers `/health`, send
  `SIGTERM`, assert a follow-up connection attempt fails within the
  deadline.
- **`test_in_flight_request_completes_on_sigterm`** — install a
  monkey-patched handler that `sleep`s for 1s before responding; issue
  the request from a background thread; once the server is mid-request
  send `SIGTERM`; assert the in-flight response arrives with status
  200 *and* a fresh connection attempt is refused.
- **`test_sigterm_flushes_pending_audit_log_entries`** — have a
  request write an audit entry just before `SIGTERM`; assert the entry
  is on disk after the process exits.
- **`test_sigterm_exits_zero`** — assert subprocess exit status is 0.
- **`test_shutdown_deadline_force_kills_hung_request`** — request
  handler sleeps > deadline; assert the subprocess exits within
  `deadline + 1s` with status 1 and that an in-flight connection is
  severed.

`tests/test_things_bridge_shutdown.py` — mirror the first four tests
for things-bridge (it has no audit writer, so swap that test for an
assertion that the configured `things_client_command` subprocess is
not left orphaned).

The tests use `subprocess.Popen` + `os.kill(proc.pid, SIGTERM)` rather
than `signal.signal` inside the pytest process, because installing
SIGTERM handlers inside the pytest worker would race with pytest's
own process group management.

## Docker compose

Once this change merges, `docker/docker-compose.yaml` can keep its
current `stop_grace_period: 5s` unchanged — the new handler fits
comfortably inside the budget and the tests above are the authoritative
pin for the behaviour. PR #152's `stop_grace_period: 0s` line (if it
lands before this PR) should be reverted back to 5s as part of this
work so compose teardown exercises the real shutdown path.

## Post-implementation standards review

- **Coding standards** — `shutdown_deadline_seconds` (unit in name);
  new function names start with verbs (`close`, `install_shutdown_handler`);
  no raw tuples introduced; `SanitizedString`-style newtypes not needed
  (no trust boundary changes).
- **Service design** — addresses the *Graceful shutdown* bullet in
  `service-design.md` directly; no config defaults written to disk;
  single source of truth for the deadline (config field); no XDG path
  changes.
- **Release and hygiene** — no new required files; no version surface
  change.
- **Testing standards** — all new tests exercise public surfaces
  (subprocess + HTTP); each test names the unit (`run_server` shutdown
  sequence); integration-test isolation intact (each test gets a fresh
  subprocess on port 0).
- **Tooling and CI** — no new check scripts; the existing
  `scripts/test.sh --unit` path runs the new suites.
