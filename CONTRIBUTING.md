<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

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
| `task test`                                | Run the pytest suite with coverage (unit by default; pass `-- --fast`, `-- --integration`, or `-- --all`). Fails below the `--cov-fail-under` floor.      |
| `task lint`                                | Run all configured linters (shellcheck, ruff check, keep-sorted).                                                                                         |
| `task format`                              | Run all configured formatters (shfmt, ruff format, mdformat, taplo). Pass `-- --check` for diff-only mode (CI uses this).                                 |
| `task typecheck`                           | Run mypy + pyright (strict) on `src/` and `tests/`.                                                                                                       |
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

### Coverage

`task test` (unit mode, the default) collects line and branch coverage
via `pytest-cov` and fails when total coverage drops below the floor
configured in `pyproject.toml` under
`[tool.pytest.ini_options].addopts` as `--cov-fail-under=<N>`. The
floor ratchets upward per
`.claude/instructions/testing-standards.md` "Coverage".

- **Bumping the floor** (coverage-improving PRs): run
  `task test -- --unit` locally, read the reported `TOTAL` percentage,
  update `--cov-fail-under=<N>` in `pyproject.toml` to one below the
  new TOTAL (so fluctuation across environments doesn't flake CI), and
  commit alongside the coverage-improving changes.
- **Lowering the floor** (rare): only when a deliberate change removes
  redundant coverage (e.g. a fixture refactor). Explain the reason in
  the commit message body; never lower silently.
- **`--fast` and `--integration` modes** run without coverage collection
  (`--no-cov`). The floor is measured against `--unit` only —
  integration tests exercise Docker-backed service interactions that
  don't map cleanly onto `src/` line coverage.

### Mutation score

`task mutation-test` runs [mutmut](https://github.com/boxed/mutmut)
against the security-critical modules listed in
`[tool.mutmut].paths_to_mutate` (tokens, crypto, keys, scopes, store)
and gates the resulting score against the floor in
`[tool.mutation_score].fail_under`. The job is scheduled nightly in
`.github/workflows/mutation.yml` rather than per-PR — runtime is
too high — so a score regression is caught within 24h rather than
immediately. Rationale in
[ADR 0021](design/decisions/0021-mutation-testing-security-critical.md).

- **Bumping the floor** (mutation-strengthening PRs): run
  `task mutation-test` locally (or download the `mutmut-stats`
  artifact from a completed nightly run), compute the new score from
  `mutants/mutmut-cicd-stats.json` as `killed / (killed + survived)`,
  and raise `fail_under` in `[tool.mutation_score]` to one point
  below the new score (so fluctuation doesn't flake CI).
- **Lowering the floor** (rare): only with a commit-message
  justification; never lower silently. The floor never goes below 0.

## Commit conventions

Use conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`,
`refactor:`, `test:`, `ci:`, `style:`, `perf:`, `build:`). Default branch
is `main`; feature branches follow `aidanns/<feature-name>`. See the
project [CLAUDE.md](CLAUDE.md) for the full working agreement.

See also: [Commit signing](#commit-signing) — commit message format and GPG/SSH
signing are sibling requirements, not the same thing.

## Release process

Two release paths exist:

- **Default — semantic-release (CI)**: on every push to `main` the
  `Semantic Release` workflow parses Conventional Commits since the
  last `vX.Y.Z` tag, and — if any commit qualifies (`feat:`, `fix:`,
  `perf:`, `revert:`, or a `BREAKING CHANGE:`) — computes the next
  version, prepends a new section to `CHANGELOG.md`, creates a signed
  `vX.Y.Z` tag, creates a GitHub release, and pushes a
  `chore(release):` commit back to `main`. The tag push triggers the
  `Release Publish` workflow. The publish workflow builds the sdist
  and wheel with `uv build`, generates an SPDX SBOM per artifact with
  Syft, signs each artifact and SBOM with keyless cosign (Sigstore
  OIDC), and attaches everything to the GitHub release.
  Verification recipe: see
  [`SECURITY.md` → Supply-chain artifacts](SECURITY.md#supply-chain-artifacts).
  Rationale for the autorelease-on-merge flow — and the trade-offs
  accepted vs. the previous Release Please PR-batched flow — in
  [ADR 0026](design/decisions/0026-semantic-release-autorelease.md).
- **Break-glass — `task release` (local)**: runs `scripts/release.sh`
  on your laptop. Use when CI is unavailable or a release has to be
  cut without waiting for the runner. The tag push uses your own git
  credential (not `GITHUB_TOKEN`), so it **does** fire
  `release-publish.yml` — the release will accrue its SBOMs and
  `.sig.bundle` signatures asynchronously once the runner completes.
  The difference from the default path is timing: `gh release create`
  publishes the release up front, so downstream consumers may briefly
  see a release whose assets are still being uploaded. Documented
  below.

### Writing release-worthy commits

`CHANGELOG.md` is generated from Conventional Commit subjects and
bodies, not hand-edited. To get a rich CHANGELOG entry:

- Keep the subject line accurate — it becomes the bullet text in
  the generated section.
- Put user-visible context (behaviour change, rationale, migration
  notes) in the commit **body**, not a separate CHANGELOG edit. The
  body surfaces in the GitHub release notes even when the CHANGELOG
  keeps only the subject.
- Reference the closing issue with `Closes #N` in the footer so the
  generated section links back.
- Mark breaking changes with a `!` after the type (`feat!:`) or a
  `BREAKING CHANGE:` footer. Pre-1.0, these demote to a minor bump
  (see [ADR 0026](design/decisions/0026-semantic-release-autorelease.md)
  § Graduating to 1.0.0).

Hand edits to `CHANGELOG.md` are preserved across releases (the
generator prepends, it does not rewrite existing content), but
subsequent automated content renders in the commit-derived format
rather than the Keep-a-Changelog prose style used in older sections.

### Default path: semantic-release

One-time setup: install a **GitHub App** on this repository that the
`Semantic Release` workflow uses to mint short-lived installation
tokens via
[`actions/create-github-app-token`](https://github.com/actions/create-github-app-token).
A GitHub App token is required (rather than the default
`GITHUB_TOKEN`) because tags and `chore(release):` commits created
by `GITHUB_TOKEN` do **not** fire downstream workflow triggers —
the chain from the semantic-release tag push to the signed-artefact
publish would silently break. The App is preferred over a PAT
because it scopes to a single repo, exposes no human credential
surface, and its private key can be rotated without touching a
personal account.

#### One-time: register the "semantic-release" GitHub App

1. Go to
   [github.com/settings/apps/new](https://github.com/settings/apps/new)
   (user-owned App) and create an App with:
   - **App name**: `semantic-release` (any identifier works; the
     name appears in the `chore(release):` commit author metadata).
   - **Homepage URL**:
     `https://github.com/aidanns/agent-auth`.
   - **Webhook**: uncheck *Active* — this App does not handle
     events.
   - **Repository permissions**:
     - *Contents*: **Read & write** (create tags, push release
       commits, create releases).
     - *Pull requests*: **Read & write** (reserved for future
       backport / maintenance-branch workflows; semantic-release
       itself does not open PRs).
     - *Issues*: **Read & write** (semantic-release can comment on
       released issues; disabled in `.releaserc.json` today but the
       permission is reserved).
     - All other permissions: **No access**.
   - **Where can this GitHub App be installed?**: *Only on this
     account*.
2. Click **Create GitHub App**.
3. On the App's settings page:
   - Copy the **App ID** (numeric, shown at the top) for step 5.
   - Under **Private keys → Generate a private key**, download
     the `.pem` file. GitHub shows it once.
4. Still on the App's settings page, open **Install App** and
   install it against `aidanns/agent-auth` only — not *All
   repositories*.
5. In the repo's
   [Settings → Secrets and variables → Actions](https://github.com/aidanns/agent-auth/settings/secrets/actions),
   add:
   - `RELEASE_PLEASE_APP_ID` — the numeric App ID from step 3.
   - `RELEASE_PLEASE_APP_PRIVATE_KEY` — the **full contents** of
     the `.pem` file, including the `-----BEGIN/END` markers and
     the trailing newline.
6. Delete the legacy `RELEASE_PLEASE_TOKEN` secret if it still
   exists.

Secret names retain the `RELEASE_PLEASE_` prefix for migration
continuity — the secrets were provisioned for the previous Release
Please flow and semantic-release consumes the identical App token.
A follow-up rename to `RELEASE_APP_*` is tracked in
[ADR 0026](design/decisions/0026-semantic-release-autorelease.md)
§ Follow-ups.

The workflow in `.github/workflows/release.yml` reads
these two secrets at run time, mints an installation token via
`actions/create-github-app-token`, and hands the token to
`semantic-release` via the `GITHUB_TOKEN` env. The token is
short-lived and is not persisted beyond the workflow run.

To rotate the private key, re-run step 3 (generate a new key),
update `RELEASE_PLEASE_APP_PRIVATE_KEY` in repo settings, and
revoke the old key from the App settings page. No workflow change
is required.

1. Land PRs on `main` using Conventional Commits.
2. The `Semantic Release` workflow runs on every push to `main`. If
   at least one commit since the last tag is `feat:`, `fix:`,
   `perf:`, `revert:`, or carries a `BREAKING CHANGE:` footer, the
   workflow cuts a new release. Otherwise it exits cleanly with no
   side effects.
3. There is **no release PR to review**. Pre-1.0 risk is mitigated
   by (a) a `releaseRules` policy in `.releaserc.json` that demotes
   `BREAKING CHANGE:` to a minor bump and (b) commit-review
   discipline at PR merge time — the PR *is* the review gate.
4. Semantic-release pushes the `vX.Y.Z` tag. The tag push triggers
   `Release Publish`, which attaches the sdist, wheel, SBOMs, and
   `.sig.bundle` signatures.

### Break-glass path: `task release`

`task release` delegates to `scripts/release.sh`, which:

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

Commits to `main` must be signed. This is enforced by the repository
ruleset named `main` — pushes carrying unsigned commits are rejected by
GitHub. Configure GPG or SSH signing in git:

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
