# agent-auth

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

## Installation

### One-line install

Requires [uv](https://docs.astral.sh/uv/) (`brew install uv` on macOS, or
`curl -LsSf https://astral.sh/uv/install.sh | sh`):

```bash
curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/install.sh | bash
```

This installs `agent-auth`, `things-bridge`, `things-cli`, and
`things-client-cli-applescript` into a uv-managed tool environment and adds
them to your PATH.

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
curl -X POST http://127.0.0.1:9100/agent-auth/validate \
  -H "Content-Type: application/json" \
  -d '{"token": "aa_<id>_<sig>", "required_scope": "things:read"}'

# Refresh a token pair
curl -X POST http://127.0.0.1:9100/agent-auth/token/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "rt_<id>_<sig>"}'

# Check token status
curl -H "Authorization: Bearer aa_<id>_<sig>" \
  http://127.0.0.1:9100/agent-auth/token/status
```

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

The bridge is indifferent to which Things-client CLI is installed — it simply runs `things_client_command`. For Linux devcontainer development and CI, a test-only fake client (`tests/things_client_fake/`, invoked as `python -m tests.things_client_fake --fixtures PATH`) reads an in-memory store from a YAML fixture so the full agent-auth + things-bridge + things-cli stack runs end-to-end without `osascript` or Things 3. Point the bridge at it via `config.yaml`:

```yaml
things_client_command:
  - python
  - -m
  - tests.things_client_fake
  - --fixtures
  - examples/fake-things.yaml
```

The fake CLI is not shipped in the sdist/wheel — it lives under `tests/` and is only reachable when running from a development checkout. It exists for integration and end-to-end testing only; never point production traffic at it.

### things-cli

`things-cli` is a thin client for `things-bridge` that auto-refreshes/reissues tokens via `agent-auth`. Credentials are kept in the system keyring by default; when no keyring backend is available (e.g. inside a devcontainer), the CLI automatically falls back to a `0600` YAML file at `~/.config/things-cli/credentials.yaml`.

```bash
# Save credentials — the CLI prompts interactively for tokens so they
# don't appear in shell history. Alternatively, pre-populate the
# credentials file at ~/.config/things-cli/credentials.json.
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
  automatically if Docker is not available.
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
to `0755` and `config.json` to `0644` so the container user (UID 1001,
see `docker/Dockerfile.test`) can read it regardless of the host
tmpdir's default mode or the host runner's UID.

CI runners, where there is no host developer state to protect, can use
whatever Docker the runner provides.

## Security

- The server binds to `127.0.0.1` by default (localhost only, not network-accessible)
- Signing and encryption keys are stored in the system keyring (macOS Keychain or libsecret/gnome-keyring)
- Tokens are HMAC-SHA256 signed with the prefix included in the signature to prevent cross-type substitution
- Sensitive fields (scopes, HMAC signatures) are encrypted at rest with AES-256-GCM
- Refresh token reuse triggers automatic family-wide revocation
- Request body size is capped at 1 MiB

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
