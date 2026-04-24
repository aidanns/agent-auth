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
| `task benchmark`                           | Run the pytest-benchmark suite under `benchmarks/` (scheduled weekly in CI; see `benchmarks/README.md`).                                                  |
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

### Benchmarks

`task benchmark` runs the pytest-benchmark suite under `benchmarks/`
covering the token hot path (`parse_token`, `sign_token`,
`verify_token`, `create_token_pair`) and the SQLite store
(`get_family` for a family with 200 scopes, `get_token`,
`create_token`). The suite is scheduled weekly via
`.github/workflows/benchmark.yml` — too noisy on shared runners to
gate every PR. Rationale and baseline-refresh procedure in
[`benchmarks/README.md`](benchmarks/README.md) and
[ADR 0029](design/decisions/0029-benchmark-suite.md).

### Schema migrations

The token store's SQLite schema is managed by a hand-rolled
numbered-SQL runner in `src/agent_auth/migrations/`. Alembic /
yoyo would be disproportionate for a single-family schema and
would add a runtime dependency the project intentionally keeps
out (CLAUDE.md § Conventions). Rules:

- **Never modify an applied migration in place.** Each entry in
  `src/agent_auth/migrations/_catalogue.py::CATALOGUE` is a
  pinned version. Changes land as a new `Migration(version=N+1, …)`
  tuple.
- **Every migration must be reversible.** Both `up_sql` and a
  matching `down_sql` are required. The runner refuses a partial
  rollback that would hit an irreversible step, so a missing
  `down_sql` blocks the whole roll-back path.
- **No `CREATE TABLE` / `ALTER TABLE` in application code.**
  Schema DDL lives exclusively in `_catalogue.py`;
  `scripts/verify-standards.sh` greps `src/agent_auth/store.py`
  to enforce this.
- **Test up-then-down.** `tests/test_migrations.py` asserts that
  every declared migration can be applied and rolled back cleanly.
  New catalogue entries should be covered by an equivalent test.

Adding a migration:

1. Append a `Migration(version=N, name="…", up_sql="…", down_sql="…")`
   entry to `CATALOGUE`.
2. Add or extend a test under `tests/test_migrations.py`.
3. `scripts/verify-standards.sh` re-runs the up/down drift check
   against an ephemeral DB on every PR — a stale catalogue or a
   non-reversible entry fails CI.

## Commit conventions

Use [Conventional Commit](https://www.conventionalcommits.org/) messages.
Semantic-release reads the commit type to decide whether and how to cut
a release — the full set of accepted types and their release impact
(mirrors `.releaserc.mjs` `releaseRules`):

| Type        | Release impact | Use for                                             |
| ----------- | -------------- | --------------------------------------------------- |
| `feat:`     | minor bump     | New user-visible feature or capability.             |
| `fix:`      | patch bump     | Bug fix visible to users.                           |
| `perf:`     | patch bump     | User-visible performance improvement.               |
| `revert:`   | patch bump     | Revert of an earlier commit.                        |
| `docs:`     | no release     | Docs / comments / README / CONTRIBUTING.            |
| `style:`    | no release     | Formatting, whitespace, no logic change.            |
| `chore:`    | no release     | Build / tooling / dependency bumps with no API hit. |
| `refactor:` | no release     | Internal restructuring with no behaviour change.    |
| `test:`     | no release     | Test-only changes.                                  |
| `build:`    | no release     | Build-system / packaging changes (non-dep).         |
| `ci:`       | no release     | CI workflow / action changes.                       |

Breaking changes are marked with a `!` suffix on the type
(`feat!: drop /v0 endpoint`) or a `BREAKING CHANGE:` footer. They
would normally bump major; while the project is in the 0.x range
they are demoted to a minor bump via
[ADR 0026](design/decisions/0026-semantic-release-autorelease.md)
§ Pre-1.0 behaviour.

`.releaserc.mjs` `releaseRules` is the authoritative source for the
release-impact column — if this table disagrees with that file, the
file wins. Raise a PR to fix the docs.

### Picking a type

The table above is enough for obvious cases. The recurring judgment
calls:

- **User-visible incorrect behaviour wins over everything.** A change
  that makes a broken thing work is `fix:` (patch bump) even when the
  implementation looks like a refactor, a perf improvement, or a test
  addition. Example: tightening an HMAC comparison that was previously
  timing-leaky is `fix(tokens):`, not `perf(tokens):`.
- **`fix(deps):` vs `chore(deps):`.** Use `fix(deps):` when the bump
  patches a CVE that our code path actually reaches, or when the
  dependency update repairs wrong behaviour we observe. Routine version
  drift on Dependabot PRs — no security advisory, no behaviour change
  — is `chore(deps):` (no release). Dev-only dependency bumps are
  `chore(deps-dev):` regardless.
- **`refactor:` vs `fix:`.** Internal restructuring that incidentally
  fixes a latent bug — split it if the diff allows: one `refactor:`
  for the restructure, one `fix:` for the defect. If splitting is
  artificial, pick `fix:` (the user-visible correction wins).
- **`build:` vs `ci:` vs `chore:`.** `build:` is for packaging / wheel
  / Dockerfile content that ships with the distribution. `ci:` is for
  `.github/workflows/**` and composite actions under `.github/actions/`.
  `chore:` covers everything else that is neither — Taskfile, scripts,
  lefthook, dev-only tooling glue. A change to `.github/dependabot.yml`
  is `ci:` (configures a GitHub-Actions-adjacent tool); a change to
  `pyproject.toml` dep constraints is `build:` (affects the shipped
  wheel); a change to `pyproject.toml` `[tool.ruff]` config is
  `chore:` (dev ergonomics only).
- **`test:` vs `fix:` on a test file.** A test change that fixes a
  **product** bug surfaced by the test is `fix:` — the commit
  qualifies for a patch release. A test change that fixes the test
  itself (flake, setup bug, asserting the wrong thing) is `test:`
  (no release).
- **`perf:` and `feat:` together.** If a perf improvement changes
  user-observable semantics (new endpoint, new config knob, changed
  defaults), it is `feat:`; the perf win is a side-effect described
  in the body. Pure perf changes (same contract, better numbers) are
  `perf:`.

### Allowed scopes

Scopes are drawn from a known set so `CHANGELOG.md` and `git log`
stay browsable. Adding a new scope is a CONTRIBUTING edit, not an
ad-hoc invention in a PR — if none of the scopes below fit, raise a
PR to add one.

- **Subsystem scopes** — the module or surface the commit touches.
  `agent-auth`, `things-bridge`, `things-cli`,
  `things-client-cli-applescript`, `server`, `audit`, `store`,
  `keys`, `scopes`, `rate-limit`, `tls`, `notifier`, `metrics`, `api`,
  `benchmark`, `observability`.
- **Area scopes** — cross-cutting concerns.
  `release` (release automation, CHANGELOG, versioning), `ci` (CI
  workflow / composite action changes), `deps` (runtime dep bumps),
  `deps-dev` (dev dep bumps), `docs` (README, CONTRIBUTING,
  CLAUDE.md, SECURITY.md, SUPPORT.md), `design` (`design/**`, ADRs),
  `security` (SECURITY.md content, security controls, scorecard, dco,
  supply-chain), `typecheck` (mypy / pyright), `verify-standards`
  (`scripts/verify-standards.sh`), `python` (ruff, pytest, project
  Python config), `setup-toolchain` (`.github/actions/setup-toolchain`),
  `docker` (Dockerfiles, compose, image pipeline), `vscode`
  (`.vscode/`), `claude` (CLAUDE.md / `.claude/instructions/`).

Bare (no-scope) commits are reserved for changes that genuinely
don't fit a single scope — a sweeping rename, a repo-wide lint pass.
Prefer a scope when one applies.

Default branch is `main`; feature branches follow
`<username>/<feature-name>`. See the project [CLAUDE.md](CLAUDE.md) for
the full working agreement.

See also: [Commit signing](#commit-signing) — commit message format and GPG/SSH
signing are sibling requirements, not the same thing. And
[DCO sign-off](#dco-sign-off) — legal provenance via `Signed-off-by:`,
distinct from both conventional-commit format and cryptographic signing.

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
- Do **not** append the linked issue number to the subject (no
  `(#<issue>)` suffix). GitHub's squash-merge auto-appends the PR
  number, and the `conventionalcommits` preset auto-links it in
  `CHANGELOG.md` — a hand-typed issue number would render a second,
  redundant link beside it. Link the issue via the `Closes #N` footer
  below instead.
- Reference the closing issue with `Closes #N` in the footer so
  GitHub closes the issue when the PR merges and the PR page lists
  the linkage. `CHANGELOG.md` intentionally does **not** render the
  closed-issue link — see
  [PR #220](https://github.com/aidanns/agent-auth/pull/220) for the
  rationale.
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

#### One-time: register the "semantic-release-agent-auth" GitHub App

1. Go to
   [github.com/settings/apps/new](https://github.com/settings/apps/new)
   (user-owned App) and create an App with:
   - **App name**: `semantic-release-agent-auth` (any identifier works; the
     name appears in the `chore(release):` commit author metadata).
   - **Homepage URL**:
     `https://github.com/aidanns/agent-auth`.
   - **Webhook**: uncheck *Active* — this App does not handle
     events.
   - **Repository permissions**:
     - *Contents*: **Read & write** (create tags, push release
       commits, create releases).
     - *Pull requests*: **Read & write** (needed by
       `@semantic-release/github` to post `successComment` on
       resolved PRs and add `releasedLabels` to them).
     - *Issues*: **Read & write** (needed by
       `@semantic-release/github` to post `successComment` on
       resolved issues and add `releasedLabels` to them).
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
   - `SEMANTIC_RELEASE_APP_ID` — the numeric App ID from step 3.
   - `SEMANTIC_RELEASE_APP_PRIVATE_KEY` — the **full contents** of
     the `.pem` file, including the `-----BEGIN/END` markers and
     the trailing newline.
6. Delete any legacy release secrets (`RELEASE_PLEASE_TOKEN`,
   `RELEASE_PLEASE_APP_ID`, `RELEASE_PLEASE_APP_PRIVATE_KEY`) if
   they still exist from earlier release-automation iterations.

The workflow in `.github/workflows/release.yml` reads
these two secrets at run time, mints an installation token via
`actions/create-github-app-token`, and hands the token to
`semantic-release` via the `GITHUB_TOKEN` env. The token is
short-lived and is not persisted beyond the workflow run.

To rotate the private key, re-run step 3 (generate a new key),
update `SEMANTIC_RELEASE_APP_PRIVATE_KEY` in repo settings, and
revoke the old key from the App settings page. No workflow change
is required.

1. Land PRs on `main` using Conventional Commits.
2. The `Semantic Release` workflow runs on every push to `main`. If
   at least one commit since the last tag is `feat:`, `fix:`,
   `perf:`, `revert:`, or carries a `BREAKING CHANGE:` footer, the
   workflow cuts a new release. Otherwise it exits cleanly with no
   side effects.
3. There is **no release PR to review**. Pre-1.0 risk is mitigated
   by (a) a `releaseRules` policy in `.releaserc.mjs` that demotes
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

1. Determine the target version. Either pass it explicitly
   (`task release -- 0.3.0`), or run `task release` with no argument —
   it will print the auto-detected version (e.g.
   `Auto-detected minor bump from commits since v0.2.0: v0.3.0`) and
   exit asking you to update `CHANGELOG.md`.
2. Write a `## [X.Y.Z] - YYYY-MM-DD` section at the top of
   `CHANGELOG.md` (directly below the preamble, above the previous
   version's heading) summarising user-visible changes since the last
   tag. For consistency with the CI default path, preview what
   semantic-release would produce — if the npm tooling is available
   locally, `npx semantic-release --dry-run --no-ci` prints the
   auto-generated release notes you can crib from. Otherwise walk
   `git log vX.Y.Z..HEAD --oneline` and group by Conventional Commit
   type.
3. Commit and push: `git commit -m "chore: prepare release vX.Y.Z"`.
   (`chore:` is in the no-release list in `.releaserc.mjs`, so the
   CI release workflow will ignore this commit and won't race with
   the break-glass path.)
4. Run `task release` (auto-detect) or `task release -- X.Y.Z` (explicit).
   Add `-y` / `--yes` to skip the confirmation prompt
   (e.g. `task release -- -y X.Y.Z`) when you want a hands-off run — the
   signed-tag step still needs your signing key, so pre-warm `gpg-agent`
   or `ssh-agent` first (see [Commit signing](#commit-signing)).

The version string embedded in the distributed package is derived from the git
tag at build time via `setuptools-scm`; no other version file needs updating.

## DCO sign-off

Every commit on a pull request must carry a `Signed-off-by:` trailer
that matches the commit author. The trailer asserts the
[Developer Certificate of Origin](https://developercertificate.org) —
that the contributor has the right to submit the change under the
project's MIT licence. This is enforced by the `DCO` GitHub Actions
workflow (`.github/workflows/dco.yml`), which fails any PR whose
non-bot commits are missing the trailer.

DCO is distinct from [Commit signing](#commit-signing):

- **Sign-off** (DCO) is a legal-provenance declaration — a text
  trailer in the commit message.
- **Signing** (GPG / SSH) is cryptographic authorship — a detached
  signature over the commit.

Configure git to add the trailer automatically with `-s`:

```bash
git commit -s -m "feat(thing): new thing"
```

Or set it once per clone so every `git commit` includes it:

```bash
git config --local format.signoff true
```

Bot-authored commits (Dependabot, Release Please, the GitHub
web-flow signer used on squash merges) are exempted by the workflow.

If the check fails on a branch you've already pushed, add the
trailer retroactively and force-push:

```bash
git rebase origin/main --signoff
git push --force-with-lease
```

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
