# Contributing

## Dev setup

1. Install [go-task](https://taskfile.dev/installation/) — the project's
   canonical task runner (`brew install go-task` on macOS,
   `sh -c "$(curl -fsSL https://taskfile.dev/install.sh)" -- -d -b "$HOME/.local/bin"`
   elsewhere).
2. Install [shellcheck](https://www.shellcheck.net/) and
   [shfmt](https://github.com/mvdan/sh) — required by `task lint` and
   `task format` (and gated in CI). On macOS: `brew install shellcheck
   shfmt`. On Debian/Ubuntu: `apt-get install shellcheck` and download
   `shfmt` from its [GitHub releases](https://github.com/mvdan/sh/releases).
3. Clone the repo and `cd` into it.
4. Run `task --list` to see every repeatable operation.

The first time you run `task test` or `task build`, the script
bootstraps a per-OS/arch virtualenv at `.venv-$(uname -s)-$(uname -m)/`
and installs the project in editable mode with dev extras. Other tasks
(e.g. `task verify-standards`) do not require the venv and skip that
setup.

## Running tasks

Every repeatable operation is exposed through the task runner. Run
`task --list` for the current catalogue. Current tasks:

| Task | Description |
| --- | --- |
| `task test` | Run the pytest suite. |
| `task lint` | Run all configured linters. |
| `task format` | Run all configured formatters. Pass `-- --check` for diff-only mode (CI uses this). |
| `task build` | Build sdist and wheel distributions into `dist/`. |
| `task install-hooks` | Install project git hooks (lefthook). |
| `task verify-design` | Verify every leaf function in the functional decomposition is allocated in the product breakdown. |
| `task verify-function-tests` | Verify every leaf function in the functional decomposition has test coverage. |
| `task verify-standards` | Verify the Taskfile exposes every task mandated by the tooling-and-ci standard. |
| `task release` | Cut a release (version bump, tag, GitHub release, publish). |

Each task dispatches to a script under `scripts/*.sh`; the scripts are
the single source of truth and can also be invoked directly if
`go-task` is not installed.

## Commit conventions

Use conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`,
`refactor:`, `test:`, `ci:`, `style:`, `perf:`, `build:`). Default branch
is `main`; feature branches follow `aidanns/<feature-name>`. See the
project [CLAUDE.md](CLAUDE.md) for the full working agreement.

## Release process

`task release` is the release entrypoint. The underlying automation
(version bump, tag, GitHub release, publish) is tracked in
[#18](https://github.com/aidanns/agent-auth/issues/18) and is not yet
implemented — running the task today exits non-zero to prevent manual
releases that would skip the standard checks.
