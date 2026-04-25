<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0033 — Host-delegated GPG signing via gpg-cli / gpg-bridge split

## Status

Accepted — 2026-04-23. Amended 2026-04-25 (issue
[#316](https://github.com/aidanns/agent-auth/issues/316)) — the
backend-CLI hop is collapsed into `gpg-bridge`. See
[Update — 2026-04-25: collapse the backend hop](#update--2026-04-25-collapse-the-backend-hop)
below; sections that the amendment replaces are kept verbatim above
the update so the original tradeoff stays readable as history.

## Context

Git commits authored inside the devcontainer cannot use the host's
GPG keys directly. Copying private keys into the container is
rejected on security grounds, so every devcontainer-authored PR has
either merged unsigned or been signed out-of-band. Issue
[#217](https://github.com/aidanns/agent-auth/issues/217) is the
operational consequence: on 2026-04-23 the `required_signatures`
rule on the `main` branch ruleset was removed so the devcontainer
could land PRs at all. That gap must close without weakening the
trust boundary between container and host.

The existing Things integration already solves the same shape of
problem for read-only data: `things-cli` runs in the container,
`things-bridge` runs on the host, and authz is delegated to
agent-auth. [ADR
0003](0003-things-client-cli-split.md) further split the host side
into a small HTTP service and a per-request subprocess client so the
bridge process no longer contains Things 3 logic. This ADR applies
the same structural pattern to GPG signing: the private key never
leaves the host, every signing request is mediated by agent-auth,
and the host-side HTTP service shells out to the real `gpg` per
request.

Issue [#242](https://github.com/aidanns/agent-auth/issues/242)
tracks the feature.

## Considered alternatives

### Copy private keys into the devcontainer

Synchronise the user's `~/.gnupg` into the container at start.

**Rejected** because:

- Expands the private-key blast radius to every process inside the
  container, including any dev tooling the user installs for a
  given task. Container images are assumed compromised by a
  supply-chain dependency far more readily than the host.
- Inverts the trust boundary this project has spent eleven ADRs
  establishing. Signing keys are the highest-sensitivity material
  in the user's environment; moving them to honour a convenience
  workflow undoes the premise that the container is a cheaper,
  more-replaceable execution environment than the host.

### SSH-forward `gpg-agent` via a Unix socket bind-mount

Bind-mount the host's `gpg-agent` socket into the container so the
container's `gpg` frontend drives the host's agent. This is what
VS Code Dev Containers' GPG support does.

**Rejected** because:

- Bind-mounting the agent socket exposes the full `gpg-agent`
  IPC surface — signing, decryption, key generation, secret export
  requests — not just signing. The scoping this project wants
  (`gpg:sign=allow`, per-key allowlist, audit log) cannot be
  enforced at that boundary because `gpg-agent` has no concept of
  the requester's identity beyond the Unix uid.
- The socket path differs across macOS and Linux hosts and breaks
  under rootless Docker / colima / orbstack / devcontainer-features
  path rewrites. The project already has working HTTP trust-boundary
  plumbing; adding a second boundary type for this one tool is more
  infra for less control.
- Cannot produce an audit record the project controls. The host
  `gpg-agent` logs are per-user; there is no HMAC-chained
  per-request record like
  [ADR 0028](0028-audit-log-hmac-chain.md).

### Use `S.gpg-agent.extra` over SSH remote forwarding

The documented `gpg-agent` mode for exactly this problem on SSH
sessions. Would require turning the devcontainer's network into
an SSH-to-host flow.

**Rejected** because:

- The devcontainer does not currently run an SSH server, and the
  auth plumbing is not SSH-shaped. Adding an SSH hop for a single
  binary is a large infra change for a small ergonomic win.
- Still inherits the scope-enforcement and audit problems of the
  raw-socket option: the host `gpg-agent` is the authorizer, not
  agent-auth.

### Extend `things-bridge` to handle signing

Single host HTTP service covering both Things and GPG signing.

**Rejected** because:

- Co-locates data-read operations (`things:read`) with signing
  operations (`gpg:sign`) inside one process, broadening its
  blast radius. A vulnerability in AppleScript dispatch would
  gain access to the signing code path in the same process.
- The bridges' transport, authz, and subprocess shapes are
  similar but not identical (streaming signing payloads, larger
  verify inputs), and forcing them into one service either means
  two subsystems in one process or a leaky shared HTTP handler.
  Two processes are simpler to reason about and can be scoped
  and restarted independently.

## Decision

Build two new components that mirror the Things split:

- **`gpg-cli`** — a small CLI installed inside the devcontainer.
  Git invokes it directly via `gpg.program`. It implements the
  subset of the `gpg` command line that `git` drives (sign and
  verify) and forwards the request over HTTPS to `gpg-bridge` on
  the host. It holds no private key material.
- **`gpg-bridge`** — an HTTP service running on the host. Validates
  every request with agent-auth, enforces the `gpg:sign` scope
  (and a configurable per-key allowlist), then spawns a host-side
  backend CLI per request.
- **`gpg-backend-cli-host`** — a host-side CLI that shells out to
  the real `gpg` binary using the user's configured keys. Plays
  the same role as `things-client-cli-applescript`: a narrow
  subprocess with no HTTP or authz surface, substitutable in
  tests by a fixture-driven fake (`gpg-backend-cli-fake`) that
  never touches private keys.

The bridge contains no GPG-protocol logic of its own; it shells out
to the configured backend the same way `things-bridge` shells out
to a configured `things_client_command`.

### Component parallels

| Things                          | GPG                         |
| ------------------------------- | --------------------------- |
| `things-cli` (in container)     | `gpg-cli` (in devcontainer) |
| `things-bridge` (host HTTP)     | `gpg-bridge` (host HTTP)    |
| `things-client-cli-applescript` | `gpg-backend-cli-host`      |
| `tests/things_client_fake/`     | `tests/gpg_backend_fake/`   |
| `src/things_client_common/`     | `src/gpg_backend_common/`   |
| `src/things_models/`            | `src/gpg_models/`           |

### Supported gpg CLI surface in `gpg-cli`

`gpg-cli` implements only what `git` invokes for signed-commit
workflows. Encryption, decryption, keyring management, and
interactive use are explicit non-goals and return a structured
error on stderr with exit code 2.

| git operation                     | gpg argv (canonical form)                                       |
| --------------------------------- | --------------------------------------------------------------- |
| Startup probe                     | `gpg --version`                                                 |
| `git commit -S`, `git tag -s`     | `gpg --status-fd <N> --keyid-format <fmt> -bsau <keyid>`        |
| `git log --show-signature`        | `gpg --status-fd <N> --keyid-format <fmt> --verify <sigfile> -` |
| `git verify-commit`, `verify-tag` | same as `--verify` above                                        |

The `-bsau <keyid>` short form expands to
`--detach-sign --sign --armor --local-user <keyid>`. The parser
accepts the expanded form interchangeably. Status output is
emitted to the file descriptor given by `--status-fd` so `git`'s
`gpg-interface.c` can read
`[GNUPG:] SIG_CREATED`, `[GNUPG:] GOODSIG`, `[GNUPG:] VALIDSIG`,
`[GNUPG:] BADSIG`, and `[GNUPG:] ERRSIG` markers verbatim from
the host `gpg`. SSH-format signing (`gpg.format=ssh`) is out of
scope; users who want SSH signing configure `gpg.program` away
from `gpg-cli`.

Any other argv shape (`--decrypt`, `--export`, `--gen-key`, `--edit-key`,
`--list-keys`, `--list-secret-keys`, …) exits 2 with a JSON envelope
`{"error": "unsupported_operation"}` on stderr. `git`-path scripts
that call these will see a clean failure mode rather than a silent
stub.

### HTTP API between `gpg-cli` and `gpg-bridge`

All requests require `Authorization: Bearer <token>` and are
validated against agent-auth per request (no bridge-side caching
beyond the standard `AgentAuthClient` socket reuse).

- `POST /gpg-bridge/v1/sign` — body:
  ```json
  {
    "local_user": "<keyid or fingerprint>",
    "armor": true,
    "status_fd_enabled": true,
    "keyid_format": "long",
    "payload_b64": "<base64 of stdin bytes>"
  }
  ```
  Response:
  ```json
  {
    "signature_b64": "<base64 of detached signature bytes>",
    "status_text": "[GNUPG:] SIG_CREATED ...\n",
    "exit_code": 0
  }
  ```
- `POST /gpg-bridge/v1/verify` — body includes `signature_b64`,
  `payload_b64`, optional `keyid_format`. Response returns
  `status_text` and `exit_code` only (no signature to echo).
- `GET /gpg-bridge/health` — standard project health endpoint.
- `GET /gpg-bridge/metrics` — Prometheus text format.

Payload bodies are base64 over JSON rather than a multipart upload
so the whole request is a single atomic document the audit log can
fingerprint. Payload bodies are capped at 1 MiB; anything larger
fails closed with HTTP 413 before the subprocess is spawned. Commit
payloads are at most a few kilobytes in practice; 1 MiB is ample and
bounds memory.

### Subprocess contract between `gpg-bridge` and the backend CLI

The bridge shells out to `gpg_backend_command` (default
`["gpg-backend-cli-host"]`) per request. Argv is:

```
gpg_backend_command sign   --local-user <keyid> [--armor] [--keyid-format <fmt>]
gpg_backend_command verify [--keyid-format <fmt>]
```

Stdin carries the payload (and, for verify, the signature — framed
as a length-prefixed pair; see below). Stdout is a single JSON
envelope, exactly as in [ADR 0003](0003-things-client-cli-split.md):

- success:
  ```json
  {
    "signature_b64": "...",
    "status_text": "...",
    "exit_code": 0
  }
  ```
- error:
  ```json
  {"error": "<code>", "detail": "<operator-only message>"}
  ```
  where `<code>` is one of `bad_signature`, `no_such_key`,
  `unsupported_operation`, `gpg_unavailable`, `gpg_permission_denied`,
  or `timeout`.

`verify` input framing: the backend reads a four-byte big-endian
length, then that many bytes of signature, then the payload to
end-of-stream. The bridge constructs this framing; `gpg-cli` does
not. Keeping the framing inside the bridge↔backend contract means
the HTTP API stays a clean JSON document.

Exit code 0 on success, non-zero on error. As in ADR 0003, the
JSON envelope is authoritative: `{"error": ...}` on stdout fails
the request regardless of exit code; a buggy backend that reports
rc=0 with an error body still fails closed.

Stderr is forwarded line-by-line to the bridge's own stderr and
capped at a 64 KiB tail retained for the timeout diagnostic,
matching `ThingsSubprocessClient`. The HTTP response body never
contains backend stderr.

### Configuration

`gpg-bridge` config (at `$XDG_CONFIG_HOME/gpg-bridge/config.yaml`):

```yaml
host: 127.0.0.1
port: 9300
auth_url: https://127.0.0.1:9100
ca_cert_path: /path/to/agent-auth-ca.pem
tls_cert_path: /path/to/gpg-bridge.pem
tls_key_path:  /path/to/gpg-bridge.key
gpg_backend_command: ["gpg-backend-cli-host"]
request_timeout_seconds: 35.0
allowed_signing_keys: []   # empty = allow any fingerprint the host has
audit_log_path: ~/.local/state/gpg-bridge/audit.log
```

`allowed_signing_keys` is a list of long key IDs or full
fingerprints (case-insensitive, whitespace-stripped). When the
list is non-empty, `--local-user` must match one of its entries
after normalisation or the bridge returns 403 without invoking the
backend. Empty list is a "trust whatever the host has" posture
that matches the current zero-config developer setup; operators
tightening their posture set the list explicitly.

`gpg-cli` reads configuration from (in precedence order): CLI
flags, environment variables, config file. Environment variables:

- `AGENT_AUTH_GPG_BRIDGE_URL` — e.g. `https://host.docker.internal:9300`
- `AGENT_AUTH_GPG_TOKEN` — bearer token
- `AGENT_AUTH_GPG_CA_CERT_PATH` — CA bundle for mutual TLS trust
- `AGENT_AUTH_GPG_TIMEOUT_SECONDS` — HTTP client timeout

Config file at `$XDG_CONFIG_HOME/gpg-cli/config.yaml` carries the
same fields. Env vars win per
[ADR 0012](0012-xdg-path-layout.md)'s layered-config pattern, matching
`things-cli`.

### Scopes and authorization

- **`gpg:sign`** — authorizes both `/v1/sign` and `/v1/verify`.
  Verification is lumped in with signing because a token that can
  drive the host `gpg` is the sensitive axis; carving
  `gpg:verify` into its own scope adds token-management surface
  without meaningful separation.
- **`gpg-bridge:health`** — authorizes the health endpoint.
- **`gpg-bridge:metrics`** — authorizes the metrics endpoint.

All three follow the existing naming convention (service name
prefix, colon separator, operation suffix). Scope tiers are
user-chosen at token-create time per
[ADR 0010](0010-three-tier-scope-model.md); the project
recommendation — and the default encoded in the devcontainer
provisioning docs — is `gpg:sign=allow`. `prompt` tier remains
available for users who want per-commit confirmation; `deny`
blocks signing without rotating the token.

Scope granularity is deliberately coarse — one `gpg:sign` scope,
not `gpg:sign:<fingerprint>`. Per-key authorization is enforced
by the bridge's `allowed_signing_keys` config, which is host-local
and changeable without re-issuing tokens. Carving per-key scopes
into the token would force operators to rotate tokens to change
key policy, and would put fingerprint strings on the wire every
time a token is modified.

### TLS posture

`gpg-cli` ↔ `gpg-bridge` traffic crosses the container-to-host
boundary, so TLS is required exactly as
[ADR 0025](0025-tls-for-devcontainer-host-traffic.md) specifies for
`things-cli` ↔ `things-bridge`. The bridge's `tls_cert_path` /
`tls_key_path` fields must be set for devcontainer deployments;
for a pure-host dev loop the bridge can bind loopback plaintext on
an operator-set-up config, mirroring the Things posture.

### Audit log

Every signing and verification request writes one entry to the
HMAC-chained audit log ([ADR 0028](0028-audit-log-hmac-chain.md))
regardless of outcome. Schema:

| Field             | Value                                           |
| ----------------- | ----------------------------------------------- |
| `ts`              | RFC 3339 timestamp                              |
| `event`           | `gpg.sign` or `gpg.verify`                      |
| `token_id`        | ID of the presented token                       |
| `requested_key`   | `--local-user` value as presented               |
| `resolved_key_fp` | full fingerprint of the key `gpg` actually used |
| `payload_sha256`  | SHA-256 of the payload bytes (hex)              |
| `outcome`         | `ok`, `denied`, `bad_signature`, `error`        |
| `error_code`      | present when `outcome != ok`                    |

Payload bytes themselves are never logged — commit contents can be
sensitive (internal URLs, PII in commit messages), and the
SHA-256 is sufficient to prove what was signed when the signature
is produced.

### Packaging

New packages under `src/` (mirroring the Things split):

- `src/gpg_models/` — dataclasses (`SignRequest`, `SignResult`,
  `VerifyRequest`, `VerifyResult`, `GpgError` hierarchy). Depended
  on by everyone.
- `src/gpg_backend_common/` — shared argparse surface used by both
  the host and fake backend CLIs, analogous to
  `things_client_common`.
- `src/gpg_backend_cli_host/` — host backend. Shells out to the
  real `gpg`.
- `src/gpg_bridge/` — HTTP service. Contains `GpgSubprocessClient`
  (the bridge's view of the subprocess contract), `AgentAuthClient`
  (shared pattern with `things_bridge/authz.py`), the request
  handler, and the Prometheus metrics registry.
- `src/gpg_cli/` — devcontainer-side CLI. Argparse frontend that
  maps git's gpg argv shape onto the HTTP API and writes
  status-fd output back to git.
- `tests/gpg_backend_fake/` — test-only fake with the same argparse
  surface as `gpg-backend-cli-host`, reading a YAML fixture from
  disk. Not shipped in the wheel; invoked as
  `python -m gpg_backend_fake --fixtures PATH`. Matches the
  precedent in ADR 0003.

Entry points in `pyproject.toml`:

```
gpg-bridge          = "gpg_bridge.cli:main"
gpg-backend-cli-host = "gpg_backend_cli_host.cli:main"
gpg-cli             = "gpg_cli.cli:main"
```

Taskfile wrappers: `task gpg-bridge -- <args...>`,
`task gpg-backend-host -- <args...>`, `task gpg-cli -- <args...>`,
matching the `things-*` shape.

## Consequences

### Security

- **Private-key locality preserved.** The private key never leaves
  the host `gpg` process. `gpg-bridge` sees payload bytes and
  signature bytes, nothing else. `gpg-cli` sees the same, plus the
  bearer token. This is strictly stronger than the alternatives
  that put keys in the container or bind-mount the agent socket.
- **Narrow trust boundary.** The bridge's trust axis is three
  inputs: the TLS-authenticated bearer token, the validated argv
  for the backend, and the backend's JSON envelope. Each is
  modelled on an existing pattern in the codebase (AuthzClient,
  AllowlistedArgvConfig, ThingsSubprocessClient).
- **Scope-and-allowlist split.** Coarse `gpg:sign` scope on the
  token, fine-grained `allowed_signing_keys` on the bridge. This
  keeps token ergonomics simple and moves the per-key policy to
  a host-local config the user can change without talking to
  agent-auth.
- **STRIDE deltas.**
  - *Spoofing:* bearer tokens, validated per-request against
    agent-auth; no bridge-side cache. TLS on the container-to-host
    path prevents token theft off the wire.
  - *Tampering:* payload bytes traverse TLS and are hashed into
    the audit log. A compromised backend CLI can produce a bad
    signature, but the caller verifying against the host
    keyring will detect it — the threat reduces to DoS.
  - *Repudiation:* HMAC-chained audit log (ADR 0028) covers every
    sign and verify request with `payload_sha256` and
    `resolved_key_fp`, so a past signing event cannot be denied
    without rewriting the chain.
  - *Information disclosure:* backend stderr is scrubbed from HTTP
    response bodies and only forwarded to the bridge's own stderr.
    Payload bytes are never audit-logged; the hash is.
  - *Denial of service:* backend subprocess timeout
    (`request_timeout_seconds`), bounded stderr tail, 1 MiB payload
    cap, and the existing rate limit posture
    ([ADR 0022](0022-rate-limiting-posture.md)) all apply. A
    commit-signing flood would be rate-limited by agent-auth
    before the bridge invokes `gpg`.
  - *Elevation of privilege:* no privilege boundary crossed.
    Host `gpg` runs as the same user as `gpg-bridge`.
- **#217 path to closure.** Once this ships and a devcontainer PR
  merges with a successful `gpg-cli`-authored signature, the
  `required_signatures` rule on the `main` ruleset can be
  re-enabled. That re-enablement is a separate follow-up PR, not
  part of this one — the design must land, bake, and be verified
  first.

### Performance

- Commit signing now traverses: container `git` →
  `gpg-cli` (Python startup ~50 ms) → HTTPS → `gpg-bridge` →
  `gpg-backend-cli-host` (Python startup ~50 ms) → host `gpg`.
  Expect ~150 ms of Python-startup overhead per commit on top of
  the host `gpg` cost. Acceptable for commit / tag signing, which
  is an interactive, human-frequency operation.
- As with ADR 0003, a persistent backend can replace the one-shot
  CLI if this ever matters. Deferred until measured need.

### Testability

- `gpg-backend-cli-fake` generates a predetermined signature blob
  from a fixture keyed by `(key_fp, payload_sha256)`. Unit tests of
  the bridge's HTTP handler never invoke `gpg`.
- E2E test in `tests/test_gpg_bridge_e2e.py` runs with a real
  `gpg-backend-cli-host`, a throwaway key generated into a
  per-test `GNUPGHOME`, and the Linux-container `gpg` binary. The
  test issues a token, signs a payload, verifies the signature
  against the test public key, revokes the token, and asserts
  signing fails with HTTP 401.
- Subprocess-contract tests mirror `test_things_client_cli_contract.py`
  — run the real host backend against a synthetic key and assert
  JSON envelope + exit code + status_text shape.
- CI: the e2e test runs Linux-only (the only platform with
  `gpg-backend-cli-host` exercised under ephemeral `GNUPGHOME` in
  GitHub Actions), consistent with how Docker-based tests run
  per [ADR 0005](0005-things-services-docker-tests.md).

### Operational

- Operators diagnosing a stuck bridge see backend stderr on the
  bridge's stderr, prefixed with `gpg-backend-cli-host:` (or
  whichever command is configured). Bridge-level logs carry the
  backend exit code.
- `gpg-cli` usage outside git remains possible for debugging:
  `echo "hello" | gpg-cli --status-fd 2 -bsau <keyid>` produces a
  detached signature to stdout exactly as `gpg` would.
- First-time devcontainer setup gains two steps: issue a token
  with `gpg:sign=allow` via `agent-auth token create`, write the
  token to the container's `AGENT_AUTH_GPG_TOKEN`, and
  `git config --global gpg.program gpg-cli`.

## Follow-ups

- GitHub issue: **re-enable `required_signatures` on main ruleset**
  after the first successful `gpg-cli`-signed PR merges. Closes
  [#217](https://github.com/aidanns/agent-auth/issues/217).
- GitHub issue: **persistent backend** — long-running host `gpg`
  wrapper speaking the same JSON subprocess contract, avoiding
  per-request Python + `gpg` startup. Deferred until measured.
- GitHub issue: **SSH-format signing** (`gpg.format=ssh`) — out of
  scope here. Tracked separately if it ever matters.
- GitHub issue: **per-fingerprint scopes** (`gpg:sign:<fp>`). The
  allowlist posture in this ADR covers the same policy question at
  the bridge boundary; per-fingerprint scopes only pay off if the
  token has to express that policy because the allowlist cannot.
  Defer until a concrete use case motivates it.

## Update — 2026-04-25: collapse the backend hop

### Context

Once `gpg-backend-cli-host` was implemented, the cost / benefit
balance fell out differently from the Things case the original
decision pattern-matched against:

- **`things-client-cli-applescript` exists because there is real
  per-version AppleScript dispatch logic to encapsulate** —
  a non-trivial backend with its own surface area, platform
  constraints, and substitution story.
- **`gpg-backend-cli-host` is a JSON-envelope ↔ `gpg` argv shim.**
  ~270 lines across `cli.py` (64) + `gpg.py` (194), most of which
  is framing the verify input and translating exit codes into
  envelope shapes. There is no domain logic the bridge couldn't
  carry directly.

Concrete costs the indirection paid for itself with:

- ~50 ms of extra Python startup per signing request (acknowledged
  in the original [§ Performance](#performance)).
- A whole package: `pyproject.toml`, install script, Taskfile entry,
  README, tests, release-pipeline coverage, dep-graph allowlist
  entry, `agent-auth-common.gpg_backend_common` module carrying the
  shared CLI dispatcher and the verify-input length-prefix protocol.
- Two subprocess contracts (HTTP ↔ bridge, bridge ↔ backend) instead
  of one (HTTP ↔ bridge), with the verify-input length-prefix
  framing existing only because of the backend hop — a shape that
  was always more about the per-process boundary than about the
  underlying gpg invocation.

The headline benefit named for the split — **substitutability under
test** — does not require a separate package. The bridge can shell
out to `gpg` directly while still letting tests inject a fake via
the same config knob: `gpg_command: ["python", "-m", "gpg_backend_fake"]`. The fake is reshaped to speak `gpg` argv
instead of the JSON-envelope contract; the YAML
fixture-keyed-by-`(key_fp, payload_sha256)` shape is preserved.

### Counter-argument considered and discarded

The split would earn its keep if a second backend implementation
landed soon — e.g. the deferred persistent-backend follow-up below,
or a non-`gpg` signer. There is no concrete consumer for either
today, no work in flight on either, and no measurement that says the
~50 ms backend-spawn cost matters at devcontainer human-frequency
commit cadence. Carrying the package indefinitely on the chance that
a future backend will repay it is the same shape of speculative
infrastructure that the project's
[ADR 0035](0035-workspace-release-model.md) judgment-call avoided
for per-package release trains: "the tooling cost is paid now for a
benefit deferred to an unknown future."

If a persistent backend ever lands it can re-introduce a backend
boundary on its own merits — with the persistent process / IPC
shape it actually needs — rather than inheriting one from the
original split.

### Decision

Move the `gpg` argv construction and exit-code handling into
`gpg-bridge`. The bridge keeps `GpgSubprocessClient`'s name and
shape, but its subprocess is now `gpg` directly rather than a
backend CLI speaking a JSON envelope.

- `gpg-bridge` config field is renamed `gpg_backend_command` →
  `gpg_command`. Default value `["gpg"]`. The substitution story
  for tests is unchanged — point `gpg_command` at the fake.
- `packages/gpg-backend-cli-host/` is deleted in full: source,
  install script, Taskfile entry, dep-graph allowlist entry, mutmut
  / mypy / pyright config, release-pipeline coverage, README and
  cross-references.
- `packages/gpg-bridge/tests/gpg_backend_fake/` is reshaped to
  speak `gpg` argv (the subset the bridge actually invokes:
  `--detach-sign`, `--verify`, `--local-user`, `--armor`,
  `--keyid-format`, `--batch`, `--no-tty`,
  `--pinentry-mode loopback`, `--status-fd`, `--version`). Its
  YAML fixture shape stays the same; only the on-the-wire
  protocol changes.
- The shared `agent-auth-common.gpg_backend_common` module
  (CLI dispatcher + verify-input length-prefix protocol) is
  removed; both halves of the JSON-envelope contract it served are
  gone after the collapse. `gpg_models` (request / result
  dataclasses, error hierarchy) is **kept** — the bridge and
  `gpg-cli` continue to use them on the HTTP API side.

The HTTP wire shape — `POST /gpg-bridge/v1/sign`,
`POST /gpg-bridge/v1/verify`, `GET /gpg-bridge/health`,
`GET /gpg-bridge/metrics` — is **unchanged**. Only the bridge's
internal dispatch changes, so `gpg-cli` (devcontainer side) and
existing token / config posture are untouched.

### Consequences

- **Component shape simplifies** to `gpg-cli` (devcontainer) +
  `gpg-bridge` (host). The "Component parallels" table now reads
  Things → GPG as `things-cli` → `gpg-cli`, `things-bridge` →
  `gpg-bridge`, with no third entry.
- **Performance** improves by ~50 ms per request: the backend
  Python startup tax disappears. The performance budget in
  [DESIGN.md § gpg-bridge](../DESIGN.md) keeps its existing
  numbers — they were set with headroom over the local baseline
  and are now further from the floor.
- **Subprocess contract surface shrinks** to one contract (HTTP ↔
  bridge), removing the verify-input length-prefix framing and the
  JSON envelope on stdout. The bridge invokes `gpg` directly via
  `subprocess.run(["gpg", ...], input=payload, capture_output=True)`
  in the sign path and via a tempdir-with-sigfile-and-datafile in
  the verify path (the shape `gpg --verify` requires anyway).
- **Migration cost for operators with an existing config** — the
  `gpg_backend_command` → `gpg_command` rename is a publicly
  observable break for anyone with a hand-edited
  `~/.config/gpg-bridge/config.yaml`. Captured in the changelog
  under the `improvement:` prefix per
  [ADR 0037](0037-palantir-commit-prefixes-and-commit-msg-block.md)'s
  user-visible-but-pre-stable scoping. The default is unchanged in
  spirit ("invoke the gpg I would normally find on PATH") so a
  zero-config bridge keeps working.
- **Threat model unchanged.** The bridge still talks to the host
  `gpg` binary, still constructs argv from a fixed set of typed
  fields (`--local-user`, `--armor`, `--keyid-format`, fixed
  operation tokens), still passes payload bytes via stdin not
  argv, still scrubs gpg's stderr from HTTP response bodies. The
  argv-injection mitigation in
  [SECURITY.md § GPG-bridge boundary](../../SECURITY.md) survives
  the collapse — the inputs the bridge interpolates into argv are
  the same shape they were before the backend hop.
