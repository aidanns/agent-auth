<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0025 — Optional in-process TLS listener on agent-auth and things-bridge

## Status

Accepted — 2026-04-22.

## Context

Both HTTP servers bind `127.0.0.1` by default, so on a single host
every call is on the loopback interface and NIST SP 800-53 SC-8
(Transmission Confidentiality and Integrity) is satisfied without
cryptographic protection.

Devcontainer usage breaks that assumption. When `things-cli` runs
inside a devcontainer and talks to an agent-auth / things-bridge
running on the host (via `host.docker.internal`, a port forward, or a
slirp4netns-style NAT), the socket crosses a virtual network interface
between two UNIX namespaces. A privileged workload on the host, or any
bridge-networked sibling container, can see the plaintext bearer
tokens and audit payloads in transit. SC-8 is not satisfied for that
path; `SECURITY.md` and [#101](https://github.com/aidanns/agent-auth/issues/101)
tracked this as a known gap until now.

## Considered alternatives

### Require a reverse proxy (nginx / caddy) in front of both services

Keep the HTTP servers plaintext and tell operators to terminate TLS in
a separate process.

**Rejected** because:

- Adds an operational prerequisite for a devcontainer-to-host
  deployment that is otherwise self-contained. Devcontainer users
  would need to install and configure a reverse proxy alongside the
  tools they actually want.
- Adds a CI dependency. Testing the TLS path end-to-end from Python
  would require spinning up the proxy, which is easy to forget and
  expensive to run.
- The Python `ssl` module already exposes exactly the posture we
  need — wrapping the listening socket is a few lines of code.

### Always serve TLS, synthesising a self-signed cert on startup

Remove the plaintext path entirely.

**Rejected** because:

- Existing loopback-only usage on a single host satisfies SC-8
  without TLS; forcing TLS there would add friction (clients need a
  trust bundle, `curl` needs `--cacert`, `urllib` needs a custom
  context) for no real-world threat improvement.
- Auto-synthesised self-signed certs rotate silently on every
  restart, creating a persistent trust-bundle problem downstream.

### Client-authenticated mTLS

Require clients to present a certificate too.

**Rejected** because:

- Bearer-token validation already authenticates callers; mTLS would
  be orthogonal and require a second credential lifecycle (cert
  rotation, per-caller trust-store updates). Out of scope for 1.0.
- Not needed to satisfy SC-8, which is about transmission
  confidentiality and integrity, not peer identity beyond what the
  bearer tokens provide.

### `http.server` SSL wrap vs. using Python's built-in via a subclass

Two plausible places to attach the TLS context: (a) wrap
`server.socket` after `ThreadingHTTPServer.__init__`, or (b) override
`server_bind` in a subclass.

**Chose (a)** — fewer methods to override, keeps the change purely
additive, matches the standard-library recipe for TLS on
`BaseHTTPServer`.

## Decision

Add an optional, in-process TLS listener to both services:

1. `Config.tls_cert_path` and `Config.tls_key_path` — paths to a PEM
   certificate chain and private key. Both must be set together; a
   half-configured pair raises `ValueError` at `__post_init__` time
   so the service can't silently drop to plaintext when TLS was
   intended.
2. `AgentAuthServer.__init__` and `ThingsBridgeServer.__init__`, after
   their `super().__init__` bind, wrap `self.socket` with an
   `ssl.SSLContext(PROTOCOL_TLS_SERVER)` pinned to TLS 1.2+ and loaded
   with the configured chain. Protocol floor matches modern browser
   defaults; OpenSSL's curated cipher list carries forward.
3. `things_bridge.Config.auth_ca_cert_path` — optional PEM bundle used
   by the bridge's `AgentAuthClient` when `auth_url` is `https://`
   with a self-signed / private CA. Empty falls back to the system
   trust store.
4. `things-cli --ca-cert <path>` — same mechanism on the client side
   for developers who configure TLS in the devcontainer scenario.
5. Startup banner updated on both services to print
   `https://host:port` when TLS is enabled, so the operator can spot
   a misconfiguration in the logs.
6. SECURITY.md SC-8 row flips from *Partial* to *Implemented*. `#101`
   closes.

Plaintext stays the default. Nothing changes for the host-only
loopback deployment, which was already SC-8-compliant.

## Consequences

**Positive**:

- SC-8 closed: devcontainer-to-host traffic can now be encrypted
  without introducing a reverse-proxy dependency.
- A single code path covers both services — the TLS context builder
  lives once per service but follows the same pattern, so drift
  (protocol floor, cipher policy) is low-risk.
- New `tests/test_server_tls.py` and `tests/test_things_bridge_tls.py`
  drive a real TLS handshake with a `cryptography`-generated
  self-signed cert. They assert the positive path, reject plaintext
  HTTP, and reject clients without the pinned CA — giving us
  regression coverage against any future refactor that accidentally
  downgrades the listener.

**Negative / accepted trade-offs**:

- Operators must generate and rotate their own certs. A one-liner
  `openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"` suffices for single-user
  developer setups; the README documents it.
- No automatic cert rotation. A process holding the socket can't
  swap certs mid-run — operators must restart the service to pick
  up a rotated cert. Acceptable for a single-user system where
  restart is cheap; if this becomes a burden, `SSLContext` supports
  mutating the cert chain in place and a SIGHUP handler could be
  bolted on.
- CI runs pay the one-time cost of generating a 2048-bit RSA key in
  the TLS tests. Measured overhead is under a second per test file
  on local hardware.

## Follow-ups

- Document a devcontainer TLS recipe in README.md and the
  devcontainer install path.
- Consider an `agent-auth serve --tls-cert / --tls-key` CLI flag if
  config-file-only configuration proves inconvenient. Not needed for
  1.0.
- `SSLContext.check_hostname = True` is the default for
  `ssl.create_default_context`; no extra hardening needed on the
  client. Document this in any future operator guide.
