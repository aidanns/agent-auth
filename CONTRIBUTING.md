# Contributing

## Dev setup

1. Install [uv](https://docs.astral.sh/uv/) — the project's canonical
   Python package and environment manager (`brew install uv` on macOS,
   `curl -LsSf https://astral.sh/uv/install.sh | sh` elsewhere).
2. Install [go-task](https://taskfile.dev/installation/) — the project's
   canonical task runner (`brew install go-task` on macOS,
   `sh -c "$(curl -fsSL https://taskfile.dev/install.sh)" -- -d -b "$HOME/.local/bin"`
   elsewhere).
3. Install [shellcheck](https://www.shellcheck.net/) and
   [shfmt](https://github.com/mvdan/sh) — required by `task lint` and
   `task format` (and gated in CI). On macOS: `brew install shellcheck shfmt`. On Debian/Ubuntu: `apt-get install shellcheck` and download
   `shfmt` from its [GitHub releases](https://github.com/mvdan/sh/releases).
4. Install [mdformat](https://mdformat.readthedocs.io/) with its GFM and
   tables plugins — required by `task format` for Markdown. Install as a
   uv-managed tool: `uv tool install mdformat --with mdformat-gfm --with mdformat-tables`.
5. Install [taplo](https://taplo.tamasfe.dev/) — required by
   `task format` for TOML. On macOS: `brew install taplo`. Elsewhere:
   download from [GitHub releases](https://github.com/tamasfe/taplo/releases).
6. Install [keep-sorted](https://github.com/google/keep-sorted) — required
   by `task lint` to verify annotated sorted blocks stay sorted. On macOS
   / Linux: `go install github.com/google/keep-sorted@latest`, or download
   from [GitHub releases](https://github.com/google/keep-sorted/releases).
7. Clone the repo and `cd` into it.
8. Run `task --list` to see every repeatable operation.

The first time you run any venv-backed task (e.g. `task test`,
`task build`, or a service task like `task agent-auth -- serve`), the
shared `scripts/_bootstrap_venv.sh` helper creates the per-OS/arch
virtualenv at `.venv-$(uname -s)-$(uname -m)/` via `uv sync --extra dev`
(reading `uv.lock` for reproducibility) and dispatches via `uv run`.
`uv sync` refreshes the venv automatically whenever `pyproject.toml` or
`uv.lock` change, so a new dependency or entry-point edit is picked up
on the next invocation without you having to blow away the venv. Other
tasks (e.g. `task verify-standards`) do not require the venv and skip
that setup.

## Running tasks

Every repeatable operation is exposed through the task runner. Run
`task --list` for the current catalogue. Current tasks:

| Task                                       | Description                                                                                                                                               |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `task test`                                | Run the pytest suite.                                                                                                                                     |
| `task lint`                                | Run all configured linters (shellcheck, keep-sorted).                                                                                                     |
| `task format`                              | Run all configured formatters (shfmt, mdformat, taplo). Pass `-- --check` for diff-only mode (CI uses this).                                              |
| `task build`                               | Build sdist and wheel distributions into `dist/`.                                                                                                         |
| `task install-hooks`                       | Install project git hooks (lefthook).                                                                                                                     |
| `task verify-design`                       | Verify every leaf function in the functional decomposition is allocated in the product breakdown.                                                         |
| `task verify-function-tests`               | Verify every leaf function in the functional decomposition has test coverage.                                                                             |
| `task verify-dependencies`                 | Verify required CLI tools (python3, task, yq, ...) are installed on PATH.                                                                                 |
| `task verify-standards`                    | Verify generic, portable standards (Taskfile task coverage, Dependabot ecosystem coverage, bash CI gating). Does not enforce project-specific task names. |
| `task release`                             | Cut a release (version bump, tag, GitHub release, publish).                                                                                               |
| `task agent-auth -- <args>`                | Run the `agent-auth` CLI (any subcommand).                                                                                                                |
| `task things-bridge -- <args>`             | Run the `things-bridge` CLI.                                                                                                                              |
| `task things-cli -- <args>`                | Run the `things-cli` client.                                                                                                                              |
| `task things-client-applescript -- <args>` | Run the `things-client-cli-applescript` CLI (macOS-only).                                                                                                 |

Each task dispatches to a script under `scripts/*.sh`; the scripts are
the single source of truth and can also be invoked directly if
`go-task` is not installed.

## Commit conventions

Use conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`,
`refactor:`, `test:`, `ci:`, `style:`, `perf:`, `build:`). Default branch
is `main`; feature branches follow `aidanns/<feature-name>`. See the
project [CLAUDE.md](CLAUDE.md) for the full working agreement.

See also: [Commit signing](#commit-signing) — commit message format and GPG/SSH
signing are sibling requirements, not the same thing.

## Release process

`task release` is the release entrypoint. The underlying automation
(version bump, tag, GitHub release, publish) is tracked in
[#18](https://github.com/aidanns/agent-auth/issues/18) and is not yet
implemented — running the task today exits non-zero to prevent manual
releases that would skip the standard checks.

## Commit signing

Commits to `main` must be signed. Enforcement via GitHub branch protection is
not yet wired up (tracked in
[#93](https://github.com/aidanns/agent-auth/issues/93)); until then this is an
honour-system requirement. Configure GPG or SSH signing in git:

```bash
# GPG (recommended)
git config --global commit.gpgsign true
git config --global user.signingkey <YOUR_KEY_ID>

# SSH (alternative — set these instead of the GPG options above)
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
```

Verify signing is working:

```bash
git log --show-signature -1
```
