# Contributing

Participation in this project — issues, pull requests, discussions — is
governed by the [Code of Conduct](.github/CODE_OF_CONDUCT.md). See
[SECURITY.md](SECURITY.md) for vulnerability reporting and
[SUPPORT.md](.github/SUPPORT.md) for where to ask questions or file bugs.

## Dev setup

01. Install [uv](https://docs.astral.sh/uv/) — the project's canonical
    Python package and environment manager (`brew install uv` on macOS,
    `curl -LsSf https://astral.sh/uv/install.sh | sh` elsewhere).
02. Install [go-task](https://taskfile.dev/installation/) — the project's
    canonical task runner (`brew install go-task` on macOS,
    `sh -c "$(curl -fsSL https://taskfile.dev/install.sh)" -- -d -b "$HOME/.local/bin"`
    elsewhere).
03. Install [shellcheck](https://www.shellcheck.net/) and
    [shfmt](https://github.com/mvdan/sh) — required by `task lint` and
    `task format` (and gated in CI). On macOS: `brew install shellcheck shfmt`. On Debian/Ubuntu: `apt-get install shellcheck` and download
    `shfmt` from its [GitHub releases](https://github.com/mvdan/sh/releases).
04. Install [mdformat](https://mdformat.readthedocs.io/) with its GFM and
    tables plugins — required by `task format` for Markdown. Install as a
    uv-managed tool: `uv tool install mdformat --with mdformat-gfm --with mdformat-tables`.
05. Install [taplo](https://taplo.tamasfe.dev/) — required by
    `task format` for TOML. On macOS: `brew install taplo`. Elsewhere:
    download from [GitHub releases](https://github.com/tamasfe/taplo/releases).
06. Install [keep-sorted](https://github.com/google/keep-sorted) — required
    by `task lint` to verify annotated sorted blocks stay sorted. On macOS
    / Linux: `go install github.com/google/keep-sorted@latest`, or download
    from [GitHub releases](https://github.com/google/keep-sorted/releases).
07. Install [treefmt](https://treefmt.com/) — the formatter
    multiplexer that drives the per-language formatters (mdformat, ruff
    format, shellcheck, shfmt, taplo) configured in `treefmt.toml`. On
    macOS: `brew install treefmt`. Elsewhere: download from
    [GitHub releases](https://github.com/numtide/treefmt/releases).
08. Install [ripsecrets](https://github.com/sirwart/ripsecrets) — the
    secret-scanning pre-commit hook. On macOS: `brew install ripsecrets`.
    Linux x86_64: download from
    [GitHub releases](https://github.com/sirwart/ripsecrets/releases).
    Other platforms: `cargo install ripsecrets`.
09. Install [lefthook](https://lefthook.dev/) — runs the pre-commit
    checks configured in `lefthook.yml` (ripsecrets, treefmt, ruff
    check, keep-sorted). On macOS: `brew install lefthook`.
    Elsewhere: `go install github.com/evilmartians/lefthook@latest`.
10. Clone the repo and `cd` into it.
11. Run `task install-hooks` to install the pre-commit hook shim
    (wraps `lefthook install`). `task verify-standards` gates on this
    being installed so that configured pre-commit checks actually fire
    on every commit.
12. Run `task --list` to see every repeatable operation.

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
| `task test`                                | Run the pytest suite (unit by default; pass `-- --fast`, `-- --integration`, or `-- --all`).                                                              |
| `task lint`                                | Run all configured linters (shellcheck, ruff check, keep-sorted).                                                                                         |
| `task format`                              | Run all configured formatters (shfmt, ruff format, mdformat, taplo). Pass `-- --check` for diff-only mode (CI uses this).                                 |
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

### Before releasing

For every user-facing PR, update `CHANGELOG.md` before merging:

1. Add a bullet under `## [Unreleased]` describing the user-visible change.
2. Keep the format consistent with the existing entries (present-tense action,
   linked to relevant issues/PRs where helpful).

### Cutting a release

`task release` is the release entrypoint. It delegates to `scripts/release.sh`,
which:

1. Resolves the target version — either from the argument you pass, or by
   deriving it from Conventional Commits since the last `v*` tag (see below).
2. Validates the working tree is clean and local `main` matches `origin/main`.
3. Checks that `CHANGELOG.md` contains a `## [X.Y.Z]` section with content for
   the resolved version.
4. Prompts for confirmation (pass `-y` / `--yes` to skip), then creates a
   signed git tag (`vX.Y.Z`).
5. Pushes the tag to `origin`.
6. Creates a GitHub release from the CHANGELOG entry for that version.

#### Version resolution

| Invocation              | Behaviour                                                                                                                                                                                                                                                                                                                                                     |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `task release`          | Auto-detect. Finds the latest `vX.Y.Z` tag, walks commits since that tag, and applies the largest SemVer bump implied by their Conventional Commit types: any `<type>!:` subject or `BREAKING CHANGE:` / `BREAKING-CHANGE:` footer → **major**; any `feat:` → **minor**; any `fix:` → **patch**. Other types alone (docs, chore, refactor, ...) → no release. |
| `task release -- 1.2.3` | Explicit override — use this for the very first release (before any `v*` tag exists) or to force a non-default bump (e.g. `1.0.0` graduation).                                                                                                                                                                                                                |

While the current tag is in the `0.x` range, the public API is not
considered stable (SemVer 2.0.0 §4). A BREAKING change that would
normally map to a **major** bump is demoted to a **minor** bump until
`v1.0.0` ships. Force the graduation to `1.0.0` with an explicit
`task release -- 1.0.0` when the API is ready to stabilise.

To cut a release:

1. Move the entries under `## [Unreleased]` in `CHANGELOG.md` into a new
   `## [X.Y.Z] - YYYY-MM-DD` section. If you don't know the version yet, run
   `task release` once — it will print the auto-detected version (e.g.
   `Auto-detected minor bump from commits since v0.1.0: v0.2.0`) then exit
   asking you to update the CHANGELOG.
2. Leave a fresh empty `## [Unreleased]` section above the new version.
3. Commit and push: `git commit -m "chore: prepare release vX.Y.Z"`.
4. Run `task release` (auto-detect) or `task release -- X.Y.Z` (explicit).
   Add `-y` / `--yes` to skip the confirmation prompt
   (e.g. `task release -- -y X.Y.Z`) when you want a hands-off run — the
   signed-tag step still needs your signing key, so pre-warm `gpg-agent`
   or `ssh-agent` first (see [Commit signing](#commit-signing)).

The version string embedded in the distributed package is derived from the git
tag at build time via `setuptools-scm`; no other version file needs updating.

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

### Non-interactive signing for `task release`

`scripts/release.sh` creates a signed tag (`git tag -s`). If your signing
key has a passphrase, the tag step pops a pinentry prompt — which blocks
`task release -- -y` from running hands-off. Configure the agent so the
passphrase is cached for the duration of the release.

**GPG:** put a cache policy in `~/.gnupg/gpg-agent.conf` and pick a
pinentry that doesn't require a graphical session if you're on a headless
box:

```text
# ~/.gnupg/gpg-agent.conf
default-cache-ttl 28800          # cache for 8 hours
max-cache-ttl     86400          # but at most 24 hours
pinentry-program  /usr/bin/pinentry-curses   # or pinentry-mac on macOS
```

Reload the agent and pre-warm the cache with a throwaway signature before
running the release:

```bash
gpgconf --kill gpg-agent
echo | gpg --clearsign > /dev/null   # enter passphrase once
task release -- -y X.Y.Z             # runs hands-off from here
```

**SSH:** if signing with an SSH key, load it into `ssh-agent` once per
session so `git tag -s` doesn't prompt:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519            # passphrase prompted once
task release -- -y X.Y.Z
```
