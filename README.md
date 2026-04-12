# agent-auth

Token-based authorization system for gating AI agent access to macOS applications via AppleScript.

## Scope

agent-auth provides a local authorization layer between AI agents (e.g. Claude Code) and macOS applications (Things3, Outlook, etc.). It issues scoped tokens that control which operations an agent can perform, with support for:

- **Fine-grained permission scopes** modeled after GitHub PAT scopes (e.g. `things:read`, `outlook:mail:send`)
- **Three-tier access control**: `allowed` (immediate), `prompt` (requires JIT human approval), `denied` (blocked)
- **Just-in-time approval** via macOS notifications for sensitive operations
- **Token lifecycle management** with creation, rotation, and revocation
- **CLI interface** for use from shell scripts and Claude Code skills

## Installation

Requires Python 3.11+.

```bash
cd ~/Projects/agent-auth
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

```bash
# Create a token with specific scopes
agent-auth token create --scope things:read --scope outlook:mail:read --expires 7d

# List active tokens
agent-auth token list

# Revoke a token
agent-auth token revoke <token-id>

# Rotate a token (create new, revoke old)
agent-auth token rotate <token-id> --expires 7d
```

## Author

Aidan Nagorcka-Smith <aidanns@gmail.com>
