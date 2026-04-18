# CLAUDE.md

## Repository purpose

Token-based authorization system for gating AI agent access to macOS applications via AppleScript. Provides scoped tokens, JIT approval for sensitive operations, and a CLI for token lifecycle management.

This project is a testbed for production-grade software engineering
practices with Claude. Apply the full rigour of the instruction files
(ADRs, threat models, migration systems, QM/SIL, etc.) without
simplifying for "personal project" scope.

## Commands

- `export UV_PROJECT_ENVIRONMENT=".venv-$(uname -s)-$(uname -m)"` — point uv at the per-OS/arch venv so Darwin and Linux venvs can coexist on a shared filesystem
- `uv sync --extra dev` — bootstrap the project virtualenv in development mode (reads `uv.lock`; refreshes automatically when `pyproject.toml` or `uv.lock` change)
- `uv run agent-auth --help` — show CLI usage
- `task agent-auth -- <args...>` (or `scripts/agent-auth.sh <args...>`) — run the agent-auth CLI. E.g. `task agent-auth -- serve`.
- `task things-bridge -- <args...>` (or `scripts/things-bridge.sh <args...>`) — run the things-bridge CLI. E.g. `task things-bridge -- serve`.
- `task things-client-applescript -- <args...>` (or `scripts/things-client-applescript.sh <args...>`) — run the things-client-cli-applescript CLI directly (macOS-only). E.g. `task things-client-applescript -- todos list --status open`.
- `task things-cli -- <args...>` (or `scripts/things-cli.sh <args...>`) — run the things-cli client. E.g. `task things-cli -- todos list`.

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

- Health endpoint: `GET /agent-auth/health`
- Metrics endpoint: `GET /agent-auth/metrics`
- End-to-end test lifecycle: create token -> validate for allow-tier scope ->
  refresh/rotate pair -> JIT approval for prompt-tier scope -> revoke ->
  verify invalidation
- Function-to-test allocation tracked via `scripts/verify-function-tests.sh`
- Generic, portable project standards (Taskfile task coverage, Dependabot ecosystem coverage, bash CI gating, `uv.lock` sync, ...) verified via `scripts/verify-standards.sh`. Project-specific task names (e.g. `task agent-auth`) are **not** enforced by this script — its `REQUIRED_TASKS` list only covers cross-project standards so the check stays portable.
- Required local CLI tooling (python3, task, uv, yq, ...) verified via `scripts/verify-dependencies.sh`
- Plugin trust boundary: the notification plugin currently uses
  `importlib.import_module` inside the server process which holds signing
  and encryption keys — tracked in #6 for migration to out-of-process
- Things-client architecture: the bridge contains no Things 3 logic.
  It runs a configured `things_client_command` (default
  `["things-client-cli-applescript"]`) per request and parses a JSON
  envelope on stdout. The production CLI is shipped; a test-only fake
  lives under `tests/things_client_fake/` and is invoked as
  `python -m tests.things_client_fake --fixtures PATH`. For Linux
  devcontainer e2e, point `things_client_command` in `config.yaml` at
  the fake. See `design/decisions/0003-things-client-cli-split.md`
  (supersedes 0001).

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
