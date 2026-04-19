# ADR 0009 — CLI / server split with a single trust boundary

## Status

Accepted — 2026-04-19.

Backfilled ADR.

## Context

agent-auth performs two classes of operation:

1. **Administrative writes** — creating, revoking, rotating tokens,
   modifying scopes. These happen on the host, driven by the user
   explicitly at the keyboard. They need direct access to the token
   store and the signing key.
2. **Online validation** — bridges (`things-bridge` today, more to
   come) forward bearer tokens to `POST /agent-auth/validate` on
   every request. This runs constantly, exposed over HTTP on
   loopback, and must neither block on human input for allow-tier
   scopes nor miss the JIT approval plugin for prompt-tier scopes.

Shipping both behind a single process simplifies the trust story:
one thing owns the keyring, one thing owns the SQLite file, one
thing logs audit events, and an attacker who compromises a bridge
gets no ambient access to key material.

## Considered alternatives

### Single CLI with a subcommand that forks a daemon

Have `agent-auth` operate both as an admin CLI and, via a
`daemon`-style subcommand, fork itself into a background validation
server. Avoids the "two binaries" feel but complicates signal
handling, foregrounding, and log plumbing.

**Rejected** because the forking dance adds complexity without
removing the split — we'd still have a process-boundary between
admin and online paths, just obscured behind a fork(2). Users would
still need an obvious mental model for "is the server running"; an
explicit `agent-auth serve` expresses that directly.

### Library-mode validation (no server)

Have bridges statically link an in-process validator that reads the
same DB.

**Rejected** because:

- Each bridge would need the signing/encryption keys in its own
  address space, multiplying the blast radius of a bridge
  compromise by the number of bridges.
- JIT approval would require every bridge to own its own
  notification UI, violating the "one approval plugin, configured
  once" property (see ADR 0010).
- Concurrent writers to the token store (CLI `revoke` racing with a
  bridge's validate) would need a distributed-lock story the server
  already provides.

## Decision

Ship agent-auth as a single Python package exposing two
entrypoints, both in `src/agent_auth/cli.py`:

- `agent-auth serve` — long-running HTTP server on `127.0.0.1:9100`.
  Owns the token store, the keyring, the audit log, and the
  notification plugin. This is the *only* process that reads the
  signing or encryption keys.
- `agent-auth token <create|list|revoke|rotate|modify> …` — admin
  subcommands that read/write the same SQLite file directly. Invoked
  interactively by the user; no long-lived state. (There is a
  `GET /agent-auth/token/status` HTTP endpoint for introspection — see
  DESIGN.md — but no `token status` CLI verb.)

Both entrypoints live in the same package and share the same config
loader, the same XDG paths, and the same keyring wrapper — but the
server is the only process that runs under a network listener. The
CLI never opens a socket.

Bridges (see DESIGN.md) talk to the server over HTTP. They never
hold the signing key, never read the SQLite file, and can only
validate / request approval.

## Consequences

- Single trust boundary: any attacker who wants signing-key access
  must compromise the `agent-auth serve` process. Bridges and CLIs
  live outside that boundary.
- The CLI and the server can race on SQLite — mitigated by SQLite's
  built-in WAL / transaction locking. Admin operations are low-rate
  and the server's hot path is short (single transaction per
  validate), so the race window is small.
- `agent-auth serve` running as a user-session process is the
  intended deployment — no systemd unit, no launchd plist yet. A
  production-style install story is a follow-up.
- Health and diagnostic HTTP endpoints
  (`GET /agent-auth/health`, `GET /agent-auth/token/status`) expose
  just enough to run readiness probes and debug tokens without
  leaking secrets (see DESIGN.md).
- Expanding to more bridges (future outlook bridge, etc.) is a
  pure-addition operation: each new bridge ships independently, talks
  only to agent-auth over HTTP, and inherits the same trust story.
