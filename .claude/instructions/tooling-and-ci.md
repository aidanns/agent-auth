# Tooling and CI

Standard tools to adopt and wire into CI and git hooks. When adding a new
tool, integrate it into `treefmt` (if it's a formatter) and `lefthook`
(if it should run on pre-commit).

## Python

- **`ruff`** — linting and formatting. Gate PRs on both.
- **`mypy` and `pyright`** — type checking. Run both in CI; `pyright` catches
  different issues and is faster, `mypy` is the community baseline.
- **`uv`** — virtual environment and dependency resolution. Still creates
  `.venv/` in the project directory per the global convention.
- **`pytest-cov`** — line and branch coverage with a ratcheting threshold.
- **`pip-audit`** (or `safety`) — dependency vulnerability scanning in CI.

## Bash

- **`shellcheck`** — linting for all `*.sh` files. Gate PRs.
- **`shfmt`** — formatting for all `*.sh` files. Gate PRs.

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
  dispatch to them.
- **`treefmt`** — formatter/linter multiplexer. Run all formatters under one
  command with consistent behaviour.
- **`lefthook`** — git hook manager. Commit a `lefthook.yml` that runs
  `ripsecrets`, `treefmt`, and quick unit tests on pre-commit.
- **`keep-sorted`** — annotate sorted blocks (imports, dependency lists,
  allow-lists) so they stay sorted automatically.

## IDE

- **VS Code project** — generate or commit a `.vscode/` directory covering
  recommended extensions, debug configurations, and workspace settings.
