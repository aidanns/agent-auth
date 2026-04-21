<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
SPDX-License-Identifier: MIT
-->

# ADR 0018 — Handle SIGTERM gracefully in `agent-auth` and `things-bridge`

## Status

Accepted — 2026-04-21.

## Context

Issue [#154](https://github.com/aidanns/agent-auth/issues/154). Neither
serve entrypoint installed a SIGTERM handler, so Docker's default
stop path always waited out `stop_grace_period` before falling back to
SIGKILL. The integration-harness timing added in PR #152 measured
~10.4s per `compose.stop` in the `things-bridge` suite, turning a
15-test run into a 3-minute exercise whose wall time was ~84%
container teardown.

Beyond CI throughput, a SIGKILL-on-shutdown posture costs the
production runtime three properties:

- **Clean rollouts.** In-flight requests get their TCP peer closed
  mid-response instead of completing.
- **Audit-log integrity.** `AuditLogger.log()` opens, writes, and
  closes the file per entry, but if the handler is interrupted
  between composing the record and writing it the event is lost.
- **Token-store consistency.** SQLite WAL is crash-safe but paying
  journal-recovery on every boot is avoidable friction; clean
  checkpointing on exit keeps the `-wal` file trimmed.

The project's `.claude/instructions/service-design.md` calls out
*Graceful shutdown* explicitly as a resilience requirement
("design and test shutdown behaviour so in-flight requests complete
cleanly on SIGTERM"), and NIST SSDF PS.3 (*Protect Software
Integrity*) covers the adjacent concern that a forced kill mid-DB
transaction must not corrupt state.

## Considered alternatives

### `signal.alarm(deadline_seconds)` watchdog

UNIX `SIGALRM` would let the kernel deliver the deadline and we would
skip the watchdog thread entirely.

**Rejected** because:

- `signal.alarm` is not available on Windows. The CLI layer is
  host-portable; we would need a second path for non-POSIX anyway.
- Re-entering Python's signal machinery from inside a SIGTERM handler
  is delicate; a watchdog thread is easier to reason about.

### Blocking join with timeout

`Thread.join(timeout=deadline)` on the server thread from the main
thread, followed by `sys.exit(1)` if the join times out.

**Rejected** because:

- `sys.exit` unwinds through registered finalisers, which includes
  any request threads still running. That races with the audit/store
  handles we are trying to close, and can deadlock if an atexit
  handler touches the same lock a request thread is holding.
- `os._exit(1)` is the correct "the shutdown deadline is firm"
  semantics — it's what we want the watchdog to do anyway.

### Per-service implementations diverging

Let each service own its own shutdown helper with different
deadlines and different signal sets.

**Rejected** because the behaviour should be identical: the shape
of the problem — SIGTERM → drain → bounded exit — does not depend
on whether the service owns a SQLite file or not. The cleanup step
(close the store, or don't) is the only variable, and that lives
in the service's `run_server`, not in the handler.

## Decision

Install a shared-shape shutdown handler in each of
`src/agent_auth/server.py::run_server` and
`src/things_bridge/server.py::run_server`. On the first delivery of
SIGTERM or SIGINT the handler:

1. Spawns a daemon drain thread that calls `server.shutdown()`. The
   drain cannot run on the `serve_forever` thread or
   `BaseServer.shutdown()` deadlocks waiting for its own loop to
   exit.
2. Spawns a daemon watchdog thread that waits on a `drain_complete`
   event with a `shutdown_deadline_seconds` timeout. On drain
   completion the event fires and the watchdog returns without
   acting. On timeout it calls `os._exit(1)` — bypassing finalisers
   so a hung request handler cannot hold the process past its
   container's `stop_grace_period`.

Subsequent signals are ignored (idempotent; one shutdown at a time).

After `serve_forever()` returns, `run_server` calls `server_close()`
(which joins in-flight request threads because both server classes
now set `daemon_threads = False`) and, for agent-auth, calls
`store.close()` to run `PRAGMA wal_checkpoint(TRUNCATE)` on a
fresh connection before exit.

`shutdown_deadline_seconds` defaults to `5.0` on both services to
match the existing `docker/docker-compose.yaml` `stop_grace_period: 5s` budget. It lives on the service `Config` dataclasses so
operators can tune it per deployment.

## Consequences

Positive:

- Container teardown in integration tests drops from ~10s/test to
  sub-second for services with no outstanding in-flight requests.
- Production rollouts no longer truncate in-flight responses.
- The token-store WAL is checkpointed cleanly, so cold-start reads
  skip journal recovery.
- SSDF PS.3 evidence: shutdown cannot leave a half-written
  transaction window open past the bounded deadline.

Negative:

- `ThreadingHTTPServer.daemon_threads` now defaults to `False` on
  both server subclasses. A crashed test that leaks a long-running
  request thread would hold the pytest process open until the
  request returns; mitigated by the watchdog when SIGTERM is sent,
  but irrelevant inside pytest (tests do not signal themselves).
- `os._exit(1)` skips `atexit` handlers and buffered stream flushes.
  Accepted: the deadline is an escape hatch for the slow-handler
  case; the normal drain path does the cleanup.

## Follow-ups

- Run the PR #152 `phase=compose_stop` timing against the merged
  fix to confirm criterion #3 of issue #154 (drop to \<2s per test).
