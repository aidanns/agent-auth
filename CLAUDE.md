# CLAUDE.md

## Repository purpose

Token-based authorization system for gating AI agent access to macOS applications via AppleScript. Provides scoped tokens, JIT approval for sensitive operations, and a CLI for token lifecycle management.

This project is a testbed for production-grade software engineering
practices with Claude. Apply the full rigour of the instruction files
(ADRs, threat models, migration systems, QM/SIL, etc.) without
simplifying for "personal project" scope.

## Commands

- `source .venv/bin/activate` — activate the virtualenv
- `pip install -e .` — install in development mode
- `agent-auth --help` — show CLI usage

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
- Plugin trust boundary: the notification plugin currently uses
  `importlib.import_module` inside the server process which holds signing
  and encryption keys — tracked in #6 for migration to out-of-process

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
