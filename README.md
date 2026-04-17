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

Requires Python 3.11+.

```bash
cd ~/Projects/agent-auth
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For development (includes pytest):

```bash
pip install -e ".[dev]"
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

`things-bridge` is an HTTP server that wraps the Things 3 application on macOS via AppleScript. It delegates token validation to `agent-auth` and exposes read-only endpoints under `/things-bridge/`. Run it alongside `agent-auth serve`:

```bash
# Start the bridge (default: 127.0.0.1:9200)
things-bridge serve
```

Host, port, and agent-auth URL are configured in `~/.config/things-bridge/config.yaml`.

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

## Security

- The server binds to `127.0.0.1` by default (localhost only, not network-accessible)
- Signing and encryption keys are stored in the system keyring (macOS Keychain or libsecret/gnome-keyring)
- Tokens are HMAC-SHA256 signed with the prefix included in the signature to prevent cross-type substitution
- Sensitive fields (scopes, HMAC signatures) are encrypted at rest with AES-256-GCM
- Refresh token reuse triggers automatic family-wide revocation
- Request body size is capped at 1 MiB

## Author

Aidan Nagorcka-Smith <aidanns@gmail.com>
