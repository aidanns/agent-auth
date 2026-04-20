# ADR 0013 — AppleScript-based Things bridge

## Status

Accepted — 2026-04-19.

Backfilled ADR. Pairs with ADR 0001 / 0003 for the in-process-vs-
subprocess client layout.

## Context

Cultured Code Things 3 has no public HTTP API, no database export, no
native Python bindings. The only supported programmatic interface is
Apple Events — i.e. AppleScript talking to the Things 3 application
via `osascript`. A Things-bridge has to go through this interface or
it doesn't talk to Things 3 at all.

AppleScript access raises two tensions against
`.claude/instructions/service-design.md`:

1. **Plugin / subprocess trust** — `service-design.md` prefers
   out-of-process execution of third-party code reachable by a
   network-facing service. The bridge's Things-client used to live
   in-process (in `src/things_bridge/things.py`), violating that
   preference.
2. **Ambient macOS coupling** — the AppleScript path only works on
   macOS hosts with Things 3 installed and granted TCC automation
   permission. CI and devcontainer workflows can't exercise the real
   path directly.

## Considered alternatives

### Read the Things 3 SQLite database directly

Things 3 stores data in a SQLite database under
`~/Library/Group Containers/…`. Reading it doesn't require Apple
Events or TCC approval.

**Rejected** because:

- Undocumented schema. Things 3 updates have rewritten tables in
  the past; the bridge would silently break on a Things 3 update.
- Read-only only. We explicitly want writes (completing todos,
  adding new items) as a future capability, and AppleScript is the
  only supported write path.
- Bypasses the user's TCC prompt, which is part of the intended
  consent UX — the user should be able to revoke automation
  permission to cut off the bridge.

### Browser automation / a Things-web companion

Doesn't exist — Things 3 is native macOS only.

**Rejected.**

## Decision

Accept AppleScript as the production Things-3 transport and
compensate for the trust concerns at the *boundary*, not the
transport:

1. The bridge itself contains no Things 3 logic. It treats its
   configured `things_client_command` as a black box: fork a
   subprocess per request, pass the call arguments on the command
   line (`stdin` is closed), parse a JSON envelope on stdout (see
   ADR 0003 — Split Things clients into sibling CLIs, which
   supersedes ADR 0001's in-process fake).
2. The production client is `things-client-cli-applescript`
   (`src/things_client_applescript/`). It emits AppleScript to
   `osascript`, parses the TSV output, and prints JSON on stdout.
   It runs in its own process with no knowledge of agent-auth
   tokens, HTTP, or the bridge's configuration.
3. The test-only client is `python -m tests.things_client_fake`
   (under `tests/things_client_fake/`). It reads fixtures from YAML
   and emits the same JSON envelope. Used for Linux devcontainer
   e2e and per-test Docker integration tests (ADR 0005).
4. The shared argparse / JSON envelope plumbing lives in
   `src/things_client_common/cli.py` so both clients stay wire-
   compatible.

The bridge is configured to point `things_client_command` at
whichever client fits the host. Operators on macOS leave it at the
default; Linux dev environments point it at the fake.

## Consequences

- The bridge's trust surface shrinks: a Things-3 API change, a TCC
  prompt, or a misbehaving AppleScript runner stays confined to the
  client subprocess. The bridge sees only a stdout JSON envelope
  and an exit code.
- The AppleScript client carries the macOS-only dependency. It
  doesn't ship with the `agent-auth` wheel on Linux (it's a
  separate entry point, guarded by platform checks at import time).
- Subprocess overhead per request is acceptable for a tool running
  at human-driven rates. Latency-sensitive batched reads (e.g.
  `list_todos` on a large Things database) are mitigated at the
  AppleScript layer via batching (see ADR 0002 — Batch AppleScript
  property reads in `list_todos`).
- Client swap-outs are a config change, not a code change: a future
  "persistent AppleScript host" (to amortise the per-request
  `osascript` startup) can ship as a sibling CLI without touching
  the bridge.
- The bridge never leaks subprocess stderr to HTTP callers —
  stderr goes to the bridge's own logs (DESIGN.md error-response
  table), so local paths and usernames don't cross the HTTP
  boundary.
- Real-Things-3 coverage via GitHub Actions' macOS runner is a
  follow-up (tracked in ADR 0001's follow-ups list). Until then,
  the AppleScript generator is covered by unit tests stubbing
  `AppleScriptRunner.run()` with sample TSV; the HTTP/authz/config
  chain is covered by the Docker integration suite against the
  fake client.
