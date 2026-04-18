# Contributing

## Dev setup

1. Install [go-task](https://taskfile.dev/installation/) — the project's
   canonical task runner (`brew install go-task` on macOS,
   `sh -c "$(curl -fsSL https://taskfile.dev/install.sh)" -- -d -b "$HOME/.local/bin"`
   elsewhere).
2. Clone the repo and `cd` into it.
3. Run `task --list` to see every repeatable operation.

The first task you run bootstraps a per-OS/arch virtualenv at
`.venv-$(uname -s)-$(uname -m)/` and installs the project in editable
mode with dev extras.

## Running tasks

Every repeatable operation is exposed through the task runner. Run
`task --list` for the current catalogue. Current tasks:

| Task | Description |
| --- | --- |
| `task test` | Run the pytest suite. |
| `task lint` | Run all configured linters. |
| `task format` | Run all configured formatters. |
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

Releases are cut via `task release`, which handles version bumping,
tagging, GitHub release creation, and publishing in one step. Do not
cut releases by hand — the task enforces the standard checks.
