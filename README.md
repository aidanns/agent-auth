<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# agent-auth

[![REUSE status](https://api.reuse.software/badge/github.com/aidanns/agent-auth)](https://api.reuse.software/info/github.com/aidanns/agent-auth)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/aidanns/agent-auth/badge)](https://scorecard.dev/viewer/?uri=github.com/aidanns/agent-auth)

Token-based authorization system for gating AI agent access to host applications.

## Scope

agent-auth provides a local authorization layer between AI agents (e.g. Claude Code) and host applications (Things3, Outlook, etc.). It issues scoped, HMAC-signed tokens that control which operations an agent can perform, with support for:

- **Fine-grained permission scopes** modeled after GitHub PAT scopes (e.g. `things:read`, `outlook:mail:send`)
- **Three-tier access control**: `allow` (immediate), `prompt` (requires JIT human approval), `deny` (blocked)
- **Just-in-time approval** via a pluggable notification backend for sensitive operations
- **Token families** with paired access/refresh tokens and automatic reuse detection
- **Field-level encryption** (AES-256-GCM) for sensitive data in the SQLite token store
- **CLI interface** for token lifecycle management (create, list, modify, revoke, rotate)
- **HTTP validation server** for runtime token and scope checks

## Packages

Each service in the monorepo ships as its own installable package
under [`packages/`](packages/). Click through for the package's own
README — public surface, configuration, and the ADRs that motivate
its design.

| Package                                                                             | Purpose                                                                                                 |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| [`agent-auth`](packages/agent-auth/README.md)                                       | Token authorization service — HMAC-signed access/refresh pairs, three-tier scope model, SQLite store.   |
| [`things-bridge`](packages/things-bridge/README.md)                                 | HTTP bridge from agent-auth-protected clients to the Things 3 to-do app.                                |
| [`things-cli`](packages/things-cli/README.md)                                       | Read-only command-line client for `things-bridge`.                                                      |
| [`things-client-cli-applescript`](packages/things-client-cli-applescript/README.md) | macOS-only AppleScript-backed implementation of the Things-client contract; invoked by `things-bridge`. |
| [`gpg-bridge`](packages/gpg-bridge/README.md)                                       | Host-side HTTP bridge that brokers GPG sign/verify on behalf of devcontainer-resident callers.          |
| [`gpg-cli`](packages/gpg-cli/README.md)                                             | Devcontainer `gpg.program` replacement that forwards git's sign/verify argv to `gpg-bridge`.            |
| [`gpg-backend-cli-host`](packages/gpg-backend-cli-host/README.md)                   | Host-side GPG backend invoked as a subprocess by `gpg-bridge`.                                          |
| [`agent-auth-common`](packages/agent-auth-common/README.md)                         | Library-only workspace package: shared types, HTTP clients, Prometheus metrics helper.                  |

## Installation

Each service in this repository ships as its own installable Python
package under [`packages/`](packages/). There is no top-level meta
installer — install only the pieces you need via the per-service
`install.sh` scripts below. Every installer is a `uv tool install`
wrapper, so it writes into a uv-managed environment and adds the CLI
to your PATH.

Requires [uv](https://docs.astral.sh/uv/) (`brew install uv` on macOS,
or `curl -LsSf https://astral.sh/uv/install.sh | sh`).

### Per-service installers

- [`agent-auth`](packages/agent-auth) — token server, token CLI, and
  out-of-process approval notifier:
  `curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/agent-auth/install.sh | bash`
- [`things-bridge`](packages/things-bridge) — HTTP bridge from
  agent-auth-protected clients to Things 3:
  `curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/things-bridge/install.sh | bash`
- [`things-cli`](packages/things-cli) — read-only Things 3 command-line
  client (talks to `things-bridge`):
  `curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/things-cli/install.sh | bash`
- [`things-client-cli-applescript`](packages/things-client-cli-applescript)
  — macOS-only AppleScript-backed Things 3 CLI (invoked by
  `things-bridge` as a subprocess):
  `curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/things-client-cli-applescript/install.sh | bash`
- [`gpg-bridge`](packages/gpg-bridge) — HTTP bridge delegating GPG
  signing to the host gpg binary for agent-auth-protected callers:
  `curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/gpg-bridge/install.sh | bash`
- [`gpg-cli`](packages/gpg-cli) — devcontainer-side `gpg.program`
  replacement that forwards git's sign / verify requests to
  `gpg-bridge`:
  `curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/gpg-cli/install.sh | bash`
- [`gpg-backend-cli-host`](packages/gpg-backend-cli-host) — host-side
  GPG backend invoked by `gpg-bridge` as a subprocess per request:
  `curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/gpg-backend-cli-host/install.sh | bash`

The [`agent-auth-common`](packages/agent-auth-common) workspace
package ships shared types (Things models, HTTP clients, Prometheus
metrics helper); it has no CLI of its own and is pulled in
transitively by every service installer.

### From source (development)

Requires:

- [uv](https://docs.astral.sh/uv/) — Python package and environment manager. Install via `brew install uv` (macOS) or `curl -LsSf https://astral.sh/uv/install.sh | sh` (Linux). uv reads `requires-python` from `pyproject.toml` and installs a matching CPython automatically, so Python 3.11+ does not need to be pre-installed.
- [go-task](https://taskfile.dev) — task runner (`brew install go-task` on macOS).

```bash
cd ~/Projects/agent-auth
task test        # bootstraps .venv-$(uname -s)-$(uname -m) via `uv sync` and runs the suite
```

Every repeatable operation is exposed through the task runner — run `task --list` to see the catalogue. Common commands:

```bash
task test                           # run the pytest suite
task build                          # build sdist and wheel into dist/
task verify-design                  # verify functional decomposition allocation
task verify-function-tests          # verify functional decomposition test coverage
task verify-standards               # verify the Taskfile matches the tooling standard
task agent-auth -- serve            # run the agent-auth CLI (any subcommand)
task things-bridge -- serve         # run the things-bridge CLI
task things-cli -- todos list       # run the things-cli client
task things-client-applescript -- todos list  # run the macOS-only things client CLI
```

Every tool invocation routes through `scripts/_bootstrap_venv.sh`, which creates the per-OS/arch virtualenv on first use and reinstalls in editable mode whenever `pyproject.toml` changes (hash-compared against a marker file inside the venv), so rerunning a task after a dependency or entry-point edit picks the change up automatically.

If you don't have `go-task` installed, every task dispatches to a script under `scripts/*.sh` that you can invoke directly (e.g. `scripts/test.sh`, `scripts/agent-auth.sh serve`).

For a bare install without the task runner:

```bash
export UV_PROJECT_ENVIRONMENT=".venv-$(uname -s)-$(uname -m)"
uv sync --extra dev
uv run agent-auth --help
```

## Usage

### Token management

```bash
# Create a token pair with specific scopes
agent-auth token create --scope things:read=allow --scope things:write=prompt

# Create a token and output as JSON
agent-auth --json token create --scope things:read=allow

# List all token families
agent-auth token list

# Modify scopes on an existing family
agent-auth token modify <family-id> --add-scope outlook:mail:read=allow --set-tier things:write=deny

# Revoke a token family
agent-auth token revoke <family-id>

# Rotate a token family (revoke old, create new with same scopes)
agent-auth token rotate <family-id>
```

### Validation server

```bash
# Start the HTTP server (default: 127.0.0.1:9100)
agent-auth serve

# Start on a custom address
agent-auth serve --host 127.0.0.1 --port 8080
```

### HTTP API

```bash
# Validate a token against a required scope
curl -X POST http://127.0.0.1:9100/agent-auth/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"token": "aa_<id>_<sig>", "required_scope": "things:read"}'

# Refresh a token pair
curl -X POST http://127.0.0.1:9100/agent-auth/v1/token/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "rt_<id>_<sig>"}'

# Check token status
curl -H "Authorization: Bearer aa_<id>_<sig>" \
  http://127.0.0.1:9100/agent-auth/v1/token/status
```

The complete wire contract for both servers is published as OpenAPI 3.1 alongside
the service that owns each surface:
[`packages/agent-auth/openapi/agent-auth.v1.yaml`](./packages/agent-auth/openapi/agent-auth.v1.yaml)
and
[`packages/things-bridge/openapi/things-bridge.v1.yaml`](./packages/things-bridge/openapi/things-bridge.v1.yaml).
Versioning guarantees are documented under "API Versioning Policy" in
[`design/DESIGN.md`](./design/DESIGN.md).

### things-bridge (macOS host)

`things-bridge` is an HTTP server that delegates token validation to `agent-auth` and exposes read-only Things 3 endpoints under `/things-bridge/`. It contains no Things 3 logic itself — every read-path request is translated into a subprocess invocation of a configured Things-client CLI (default `things-client-cli-applescript`, which shells to `osascript` on macOS). Run it alongside `agent-auth serve`:

```bash
# Start the bridge (default: 127.0.0.1:9200)
things-bridge serve
```

Host, port, agent-auth URL, and `things_client_command` are configured in `~/.config/things-bridge/config.yaml`.

#### things-client-cli-applescript

Standalone read-only CLI that talks to Things 3 via `osascript`. Useful for local debugging of the Things side independent of the bridge and agent-auth. Emits JSON on stdout.

```bash
things-client-cli-applescript todos list --status open
things-client-cli-applescript projects show <project-id>
```

#### Running on Linux with the fake Things client

The bridge is indifferent to which Things-client CLI is installed — it simply runs `things_client_command`. For Linux devcontainer development and CI, a test-only fake client (`tests/things_client_fake/`, invoked as `python -m things_client_fake --fixtures PATH`) reads an in-memory store from a YAML fixture so the full agent-auth + things-bridge + things-cli stack runs end-to-end without `osascript` or Things 3. Point the bridge at it via `config.yaml`:

```yaml
things_client_command:
  - python
  - -m
  - things_client_fake
  - --fixtures
  - tests/things_client_fake/fake-things.yaml
```

The fake CLI is not shipped in the sdist/wheel — it lives under `tests/` and is only reachable when running from a development checkout. It exists for integration and end-to-end testing only; never point production traffic at it.

### things-cli

`things-cli` is a thin client for `things-bridge` that auto-refreshes/reissues tokens via `agent-auth`. Credentials are kept in the system keyring by default; when no keyring backend is available (e.g. inside a devcontainer), the CLI automatically falls back to a `0600` YAML file at `~/.config/things-cli/credentials.yaml`.

```bash
# Save credentials — the CLI prompts interactively for tokens so they
# don't appear in shell history. Alternatively, pre-populate the
# credentials file at ~/.config/things-cli/credentials.yaml.
things-cli login \
  --bridge-url http://127.0.0.1:9200 \
  --auth-url http://127.0.0.1:9100 \
  --family-id <family-id>

# Show redacted credential status
things-cli status

# Commands (add --json for structured output)
things-cli todos list
things-cli todos list --list TMTodayListSource --status open  # Things built-in list id
things-cli todos show <todo-id>
things-cli projects list
things-cli projects show <project-id>
things-cli areas list
things-cli areas show <area-id>

# Discard stored credentials
things-cli logout
```

## Development

### Running tests

Tests are split into two layers:

- **Unit** (fast, in-process) — `scripts/test.sh --unit` (default).
- **Integration** (Docker-backed) — `scripts/test.sh --integration`. Each
  test spins up its own `agent-auth serve` container via Docker Compose
  (one ephemeral Compose project per test), drives it over HTTP, and
  uses `docker compose exec` to invoke the `agent-auth` CLI inside the
  container. Requires Docker + Docker Compose on the host. Tests skip
  automatically if Docker is not available. Pass a service name to run
  only that slice: `scripts/test.sh --integration agent-auth`
  (also `things-bridge`, `things-cli`, `things-client-applescript`).
- **Both** — `scripts/test.sh --all`.

See `design/decisions/0004-docker-integration-tests.md` for the design
rationale.

### Running integration tests from a devcontainer

When running the integration tests inside a devcontainer, prefer
**rootless Docker-in-Docker** over bind-mounting the host's Docker
socket:

- A mounted host socket lets any process inside the devcontainer mount
  arbitrary host paths (`~/.ssh`, `~/.aws`, keyring-backed credentials),
  which short-circuits agent-auth's token/scope contract. Rootless DinD
  keeps the blast radius inside the devcontainer.
- Socket-mount containers are siblings of the devcontainer on the host
  (volumes resolve against host paths, they outlive the devcontainer,
  they share networks with other host processes). DinD nests them so
  teardown is clean and volume paths behave as expected.
- The nested daemon's image cache and networks live inside the
  devcontainer, so integration state does not diverge based on what
  each developer has cached on their laptop.
- Rootless (not privileged root) keeps the daemon capped at the
  devcontainer user's privileges; `--privileged` is not an acceptable
  default.

Trade-offs: overlay-on-overlay storage is slower than sharing the host
cache, rootless-in-rootless needs `/dev/fuse` and user-namespace
config, and images built inside DinD are not visible to the host
`docker` CLI.

The integration-test fixture chmods the bind-mounted config directory
to `0755` and `config.yaml` to `0644` so the container user (UID 1001,
see `docker/Dockerfile.agent-auth.test`) can read it regardless of the
host tmpdir's default mode or the host runner's UID.

CI runners, where there is no host developer state to protect, can use
whatever Docker the runner provides.

## Security

- The server binds to `127.0.0.1` by default (localhost only, not network-accessible)
- Signing and encryption keys are stored in the system keyring (macOS Keychain or libsecret/gnome-keyring)
- Tokens are HMAC-SHA256 signed with the prefix included in the signature to prevent cross-type substitution
- Sensitive fields (scopes, HMAC signatures) are encrypted at rest with AES-256-GCM
- Refresh token reuse triggers automatic family-wide revocation
- Request body size is capped at 1 MiB
- Optional in-process TLS listener for devcontainer-to-host traffic — see "TLS for devcontainer-to-host traffic" below

### TLS for devcontainer-to-host traffic

Both servers bind plaintext HTTP on `127.0.0.1` by default — fine for a single-host deployment where loopback satisfies NIST SP 800-53 SC-8. When `things-cli` runs inside a devcontainer and reaches agent-auth / things-bridge on the host, the socket crosses a virtual network interface and plaintext traffic is visible to other bridge-networked containers. Configure TLS on both services to close that gap (see [ADR 0025](design/decisions/0025-tls-for-devcontainer-host-traffic.md)):

1. Generate a self-signed cert good for `localhost` and `127.0.0.1`:

   ```
   openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
     -days 365 -nodes -subj "/CN=localhost" \
     -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
   ```

2. Point each service at its cert/key via `config.yaml`:

   ```yaml
   tls_cert_path: /path/to/cert.pem
   tls_key_path:  /path/to/key.pem
   ```

3. For `things-bridge`, also set `auth_ca_cert_path` so the bridge trusts agent-auth's self-signed cert when validating tokens.

4. Inside the devcontainer, point `things-cli` at the HTTPS URLs and pass `--ca-cert` so it trusts the self-signed CA:

   ```
   things-cli --ca-cert /path/to/cert.pem \
     login --bridge-url https://host.docker.internal:9200 \
           --auth-url   https://host.docker.internal:9100 \
           --access-token ... --refresh-token ... --family-id ...
   ```

Setting only one of `tls_cert_path` / `tls_key_path` is rejected at startup so the services cannot silently fall back to plaintext when TLS was intended.

Every GitHub release ships an SPDX SBOM and keyless Sigstore cosign signatures
for each artifact and SBOM. See
[SECURITY.md § Supply-chain artifacts](SECURITY.md#supply-chain-artifacts) for
the verification recipe.

See [SECURITY.md](SECURITY.md) for the full threat model, trust boundaries, key
handling, revocation flow, audit surface, vulnerability reporting, and the chosen
cybersecurity standard (NIST SP 800-53 Rev 5).

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup,
task runner usage, commit conventions, and the release process. Participation
is governed by the project
[Code of Conduct](.github/CODE_OF_CONDUCT.md).
[SUPPORT.md](.github/SUPPORT.md) covers where to ask questions, file bugs, and
report vulnerabilities.

## License

[MIT](LICENSE.md)

## Author

Aidan Nagorcka-Smith <aidanns@gmail.com>
