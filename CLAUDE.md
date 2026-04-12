# CLAUDE.md

## Repository purpose

Token-based authorization system for gating AI agent access to macOS applications via AppleScript. Provides scoped tokens, JIT approval for sensitive operations, and a CLI for token lifecycle management.

## Commands

- `source .venv/bin/activate` — activate the virtualenv
- `pip install -e .` — install in development mode
- `agent-auth --help` — show CLI usage

## Architecture

- `src/agent_auth/cli.py` — CLI entrypoint using argparse
- Token store will use SQLite at `~/.config/agent-auth/tokens.db`
- Tokens are HMAC-signed: `aa_<token-id>_<hmac-signature>`
- Signing key stored at `~/.config/agent-auth/signing.key`

## Conventions

- Python 3.11+, no external dependencies for core functionality
- Use `src/` layout with `pyproject.toml`
- Follow user global instructions for shell scripts, commits, TODOs, etc.
