# CLAUDE.md

## Repository purpose

Token-based authorization system for gating AI agent access to macOS applications via AppleScript. Provides scoped tokens, JIT approval for sensitive operations, and a CLI for token lifecycle management.

This project is a testbed for production-grade software engineering
practices with Claude. Apply the full rigour of the instruction files
(ADRs, threat models, migration systems, QM/SIL, etc.) without
simplifying for "personal project" scope.

## Commands

- `export UV_PROJECT_ENVIRONMENT=".venv-$(uname -s)-$(uname -m)"` — point uv at the per-OS/arch venv so Darwin and Linux venvs can coexist on a shared filesystem
- `uv sync --extra dev` — bootstrap the project virtualenv in development mode (reads `uv.lock`)
- `uv run agent-auth --help` — show CLI usage
- `scripts/agent-auth.sh <args...>` — run the agent-auth CLI (bootstraps `.venv-$(uname -s)-$(uname -m)` if missing); e.g. `scripts/agent-auth.sh serve`
- `scripts/things-bridge.sh <args...>` — run the things-bridge CLI (bootstraps `.venv-$(uname -s)-$(uname -m)` if missing); e.g. `scripts/things-bridge.sh serve`
- `scripts/things-cli.sh <args...>` — run the things-cli client (bootstraps `.venv-$(uname -s)-$(uname -m)` if missing); e.g. `scripts/things-cli.sh todos list`

## Architecture

- `src/agent_auth/cli.py` — CLI entrypoint using argparse
- Token store will use SQLite at `$XDG_DATA_HOME/agent-auth/tokens.db`
- Tokens are HMAC-signed: `aa_<token-id>_<hmac-signature>`
- Signing key stored in the system keyring (macOS Keychain or libsecret/gnome-keyring)

## Conventions

- Python 3.11+, no external dependencies for core functionality
- Use `src/` layout with `pyproject.toml`
- Follow user global instructions for shell scripts, commits, TODOs, etc.
- Use conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`,
  `refactor:`, `test:`, `ci:`, `style:`, `perf:`, `build:`)

## Project-specific notes

- Health endpoint: `GET /agent-auth/healthz`
- Metrics endpoint: `GET /agent-auth/metrics`
- End-to-end test lifecycle: create token -> validate for allow-tier scope ->
  refresh/rotate pair -> JIT approval for prompt-tier scope -> revoke ->
  verify invalidation
- Function-to-test allocation tracked via `scripts/verify-function-tests.sh`
- Project standards (Taskfile task coverage, Dependabot ecosystem coverage, `uv.lock` sync, ...) verified via `scripts/verify-standards.sh`
- Required local CLI tooling (python3, task, uv, yq, ...) verified via `scripts/verify-dependencies.sh`
- Plugin trust boundary: the notification plugin currently uses
  `importlib.import_module` inside the server process which holds signing
  and encryption keys — tracked in #6 for migration to out-of-process
- Linux devcontainer e2e: `things-bridge serve --fake-things[=PATH]`
  swaps `ThingsApplescriptClient` for an in-memory `FakeThingsClient`
  so the stack runs without `osascript`. Developer-only — not a config
  file option. See `design/decisions/0001-things-client-fake.md`.

## Detailed instructions

The following files in `.claude/instructions/` contain detailed standards
derived from lessons learned during development. Consult them when the
topic is relevant:

- `plan-template.md` — checklist of steps every implementation plan must
  include (design verification and post-implementation standards review).
- `coding-standards.md` — naming, types, and safety rules.
- `service-design.md` — configuration, file paths, plugin surfaces, HTTP
  services, security, and resilience standards.
- `design.md` — design directory structure, ADRs, functional decomposition,
  product breakdown, QM/SIL, and cybersecurity standard selection.
- `testing-standards.md` — test design, coverage thresholds, mutation
  testing, fault injection, and performance benchmarks.
- `tooling-and-ci.md` — standard tools (treefmt, lefthook, etc.) and CI
  configuration.
- `python.md` — Python-specific tooling and type conventions.
- `bash.md` — Bash-specific linting and formatting.
- `release-and-hygiene.md` — required project files (CONTRIBUTING, CHANGELOG,
  LICENSE, SECURITY), release process, and repo metadata.
