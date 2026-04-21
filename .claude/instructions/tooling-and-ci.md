<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Tooling and CI

Standard tools to adopt and wire into CI and git hooks. When adding a new
tool, integrate it into `treefmt` (if it's a formatter) and `lefthook`
(if it should run on pre-commit).

## Language-specific

See language-specific instruction files for tooling tied to a particular
language: `python.md`, `bash.md`.

## Markdown

- **`mdformat`** — formatting with plugins for tables and GitHub-flavoured
  Markdown.

## TOML

- **`taplo`** — linting and formatting for TOML config files.

## Security

- **`ripsecrets`** — pre-commit hook to prevent accidental secret commits.
  Preferred over alternatives for speed (Rust-based).
- **Dependabot** (or Renovate) — automated dependency updates for
  vulnerability fixes.

## Orchestration

- **`go-task`** — task runner with `Taskfile.yml` at the repo root. Every
  operation (build, lint, test, release) should be discoverable via
  `task --list`. Keep `scripts/*.sh` implementations; have the Taskfile
  dispatch to them. Project-specific tasks (running a local service
  CLI, a one-off domain command) are fine to add to `Taskfile.yml`, but
  must **not** be added to the `REQUIRED_TASKS` list in
  `scripts/verify-standards.sh`: that list is reserved for task names
  mandated by this cross-project tooling standard so the check stays
  portable to other repositories adopting it.
- **`treefmt`** — formatter/linter multiplexer. Run all formatters under one
  command with consistent behaviour.
- **`lefthook`** — git hook manager. Commit a `lefthook.yml` that runs
  `ripsecrets`, `treefmt`, and quick unit tests on pre-commit.
- **`keep-sorted`** — annotate sorted blocks (imports, dependency lists,
  allow-lists) so they stay sorted automatically.

## CI

- **Test runner script** — ensure a single-command test runner exists (e.g.
  `scripts/test.sh`) so the full test suite runs with one command.

- **Wire all check scripts into CI** — every repeatable check script must
  have a CI workflow.

- **Pin sha256 for tool binary downloads** — any CI step that downloads a
  CLI binary directly (curl/wget from a release CDN) must verify the
  artefact against a sha256 pinned in the repository before extracting or
  installing it. Pair the version input with a sibling `<tool>-sha256`
  input so version bumps and hash updates travel together. Verify with
  `echo "<sha256>  <path>" | sha256sum -c -` immediately after download
  and before any `tar`/`install`/`gunzip` step. A failed check must abort
  the action — never fall back to the unverified binary. Pinning in-repo
  is preferred over fetching an upstream `checksums.txt`, because the
  checksum file would travel over the same TLS channel as the artefact
  it claims to verify.

- **Pin release-affecting GitHub Actions to commit SHAs** — third-party
  `uses:` references in any workflow that holds `id-token: write`,
  `contents: write`, or otherwise sits on the release path must be pinned
  to a full 40-character commit SHA, not a floating `@vX` tag. A
  compromised action release on a floating tag can otherwise siphon the
  runner's OIDC token or substitute a malicious signing binary in-flight.
  Use the format `uses: ORG/REPO@<sha> # vX.Y.Z` — Dependabot reads the
  trailing comment to track upgrades and rewrites both the SHA and the
  comment on each bump, keeping the pin reviewable.

  Scope today: `.github/workflows/release-please.yml`,
  `.github/workflows/release-publish.yml`, `.github/workflows/reuse.yml`
  (the REUSE gate is a release prerequisite), and
  `.github/actions/setup-toolchain/action.yml` (indirectly part of the
  release path via `reuse.yml`). Read-only workflows (`check.yml`,
  `test.yml`, `verify-*.yml`, `typecheck.yml`, `security.yml`) stay on
  floating-major tags — their blast radius is small enough that the
  review cost of SHA-pinned bumps outweighs the benefit. Local composite
  actions referenced as `uses: ./...` are version-locked to the repo
  commit itself and need no extra pinning.

## IDE

- **VS Code project** — generate or commit a `.vscode/` directory covering
  recommended extensions, debug configurations, and workspace settings.
