<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

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
- `task gpg-bridge -- <args...>` (or `scripts/gpg-bridge.sh <args...>`) — run the gpg-bridge CLI on the host. E.g. `task gpg-bridge -- serve`.
- `task gpg-cli -- <args...>` (or `scripts/gpg-cli.sh <args...>`) — run the devcontainer gpg-cli frontend. Wired to git via `git config gpg.program gpg-cli`.
- `task gpg-backend-host -- <args...>` (or `scripts/gpg-backend-host.sh <args...>`) — run the host gpg backend CLI directly; normally invoked as a subprocess by `gpg-bridge`.
- `task setup-devcontainer-signing -- --token <T> --bridge-url <U>` (or `scripts/setup-devcontainer-signing.sh <args...>`) — wire commit signing inside the devcontainer to the host's `gpg-bridge`. Writes `$XDG_CONFIG_HOME/gpg-cli/config.yaml` and sets `git config --local gpg.program=gpg-cli` + `commit.gpgsign=true`. See `CONTRIBUTING.md` § "Signed commits inside the devcontainer".

## Architecture

- Monorepo uv workspace: each service lives under `packages/<svc>/`
  with its own `pyproject.toml`, `install.sh`, `src/<module>/`, and
  `tests/` tree (the latter relocated from the monolithic root
  `tests/` in #270). Shared types (HTTP clients, Things models,
  Prometheus metrics helper, test-only `tests_support`) live in
  `packages/agent-auth-common/src/`. The root `tests/` tree only
  carries workspace-wide checks (release-semver, openapi-spec,
  pip-audit-to-sarif, scan-failure).
- `packages/agent-auth/src/agent_auth/cli.py` — agent-auth CLI
  entrypoint using argparse
- Token store will use SQLite at `$XDG_DATA_HOME/agent-auth/tokens.db`
- Tokens are HMAC-signed: `aa_<token-id>_<hmac-signature>`
- Signing key stored in the system keyring (macOS Keychain or libsecret/gnome-keyring)

## Conventions

- Python 3.11+, no external dependencies for core functionality
- Per-service `src/` layout under `packages/<svc>/`, one `pyproject.toml` per package
- Follow user global instructions for shell scripts, commits, TODOs, etc.
- PR titles use the Palantir-style prefix set (ADR 0037):
  `feature:` (minor bump), `improvement:` / `fix:` / `deprecation:` /
  `migration:` (patch bump), `break:` (major bump, demoted to minor
  while in 0.x), `chore:` (no release entry). Optional `(scope)` is
  allowed (e.g. `feature(ci): …`). The default Conventional Commits
  prefixes (`feat:`, `perf:`, `revert:`, `docs:`, `style:`,
  `refactor:`, `test:`, `build:`, `ci:`) are NOT accepted; map
  user-visible perf wins to `improvement:` and the
  docs/style/refactor/test/build/ci cases to `chore:` when not
  user-visible. The PR-title lint
  (`.github/workflows/pr-lint.yml`) enforces the allowlist.
- The squash-merge commit body is authored inside the
  `==COMMIT_MSG==` … `==COMMIT_MSG==` block in the PR template; the
  `## Review notes` section (test plan, screenshots) does not enter
  git history. The merge bot
  (`.github/workflows/merge-bot.yml`, ADR 0038) pastes the block
  as the squash-merge body when the PR carries the `automerge`
  label and every required check is green; agents apply the label
  with `gh pr edit <pr> --add-label automerge` instead of using
  `gh pr merge --auto --squash`. The bot authors no commits, so
  the `Signed-off-by:` trailer must already sit inside the block —
  `pr-lint.yml` enforces that. See
  `docs/release/merge-bot-setup.md` for maintainer setup and
  CONTRIBUTING.md § "Writing PRs" for the worked example.
- Commit subjects must not include the linked issue number
  (no `(#<issue>)` suffix). GitHub's squash-merge appends the PR
  number, which the `conventionalcommits` preset auto-links; adding
  an issue number by hand produces a duplicate parenthesized link in
  `CHANGELOG.md`. Link the issue with a `Closes #N` footer in the
  `==COMMIT_MSG==` block. See CONTRIBUTING.md § "Writing PRs".
- Every PR commit needs a DCO `Signed-off-by:` trailer — use
  `git commit -s` every time, or alias it once with
  `git config --local alias.c 'commit -s'`. Git has no native config
  that makes `git commit` always sign off; `format.signoff` only
  affects `git format-patch`, and `commit.signoff` is not recognised.
  Enforced by `.github/workflows/dco.yml`; forgetting it makes the
  `DCO sign-off check` fail and the remedy is
  `git rebase origin/main --signoff && git push --force-with-lease`.
  See `CONTRIBUTING.md` → "DCO sign-off".

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
  lives under `packages/things-bridge/tests/things_client_fake/` and
  is invoked as `python -m things_client_fake --fixtures PATH`. For
  Linux devcontainer e2e, point `things_client_command` in
  `config.yaml` at the fake. See
  `design/decisions/0003-things-client-cli-split.md`
  (supersedes 0001).
- gpg-bridge architecture: mirrors the Things split. `gpg-bridge`
  runs on the host and delegates each request to a configured
  `gpg_backend_command` (default `["gpg-backend-cli-host"]`) which
  shells out to the real host `gpg`. `gpg-cli` runs in the
  devcontainer as a `gpg.program` replacement and forwards git's
  sign / verify argv to `gpg-bridge` over HTTPS with a bearer token
  (scope `gpg:sign`). Per-key allowlisting sits in bridge config
  (`allowed_signing_keys`). A test-only backend fake lives under
  `packages/gpg-bridge/tests/gpg_backend_fake/` and is invoked as
  `python -m gpg_backend_fake --fixtures PATH`. See
  `design/decisions/0033-gpg-bridge-cli-split.md`.

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
