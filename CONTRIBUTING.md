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

| Task                                       | Description                                                                                                                                                                         |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `task test`                                | Run the pytest suite with coverage (unit by default; pass `-- --fast`, `-- --integration`, or `-- --all`). Fails if any package's per-package `--cov-fail-under` floor is breached. |
| `task benchmark`                           | Run the pytest-benchmark suite under `packages/agent-auth/benchmarks/` (scheduled weekly in CI; see `packages/agent-auth/benchmarks/README.md`).                                    |
| `task lint`                                | Run all configured linters (shellcheck, ruff check, keep-sorted).                                                                                                                   |
| `task format`                              | Run all configured formatters (shfmt, ruff format, mdformat, taplo). Pass `-- --check` for diff-only mode (CI uses this).                                                           |
| `task typecheck`                           | Run mypy + pyright (strict) on every `packages/<svc>/src/` tree and `tests/`.                                                                                                       |
| `task build`                               | Build sdist and wheel distributions into `dist/`.                                                                                                                                   |
| `task install-hooks`                       | Install project git hooks (lefthook).                                                                                                                                               |
| `task verify-design`                       | Verify every leaf function in the functional decomposition is allocated in the product breakdown.                                                                                   |
| `task verify-function-tests`               | Verify every leaf function in the functional decomposition has test coverage.                                                                                                       |
| `task verify-dependencies`                 | Verify required CLI tools (python3, task, yq, ...) are installed on PATH.                                                                                                           |
| `task verify-standards`                    | Verify generic, portable standards (Taskfile task coverage, Dependabot ecosystem coverage, bash CI gating). Does not enforce project-specific task names.                           |
| `task release`                             | Force a refresh of the YAML-driven release PR (manual escape hatch). The release PR is normally opened automatically on every push to `main`; merging it tags + publishes.          |
| `task agent-auth -- <args>`                | Run the `agent-auth` CLI (any subcommand).                                                                                                                                          |
| `task things-bridge -- <args>`             | Run the `things-bridge` CLI.                                                                                                                                                        |
| `task things-cli -- <args>`                | Run the `things-cli` client.                                                                                                                                                        |
| `task things-client-applescript -- <args>` | Run the `things-client-cli-applescript` CLI (macOS-only).                                                                                                                           |

Each task dispatches to a script under `scripts/*.sh`; the scripts are
the single source of truth and can also be invoked directly if
`go-task` is not installed.

Per-package dev loops are also available under each service's
namespace: `task <svc>:test`, `task <svc>:lint`, `task <svc>:typecheck`,
`task <svc>:format`, and `task <svc>:check` narrow to a single
workspace member under `packages/<svc>/`. `task <svc>` (no suffix)
resolves to the namespace default and still runs the service CLI where
one exists (e.g. `task agent-auth -- serve`). Namespaces are declared
in the workspace-root `Taskfile.yml`; the root-level sweepers above
stay authoritative until #270 relocates the monolithic `tests/` and
`benchmarks/` trees into per-package subdirectories.

### Coverage

`task test` (unit mode, the default) collects line and branch coverage
via `pytest-cov` into a unified `.coverage` database. After the pytest
run, `scripts/check-package-coverage.sh` walks every
`packages/<svc>/pyproject.toml`, extracts the per-package
`--cov-fail-under=<N>` from `[tool.pytest.ini_options].addopts`, and
fails if any package's slice of the report falls below its floor.
The per-package floor model (#273) keeps a well-tested package from
masking a regression in another and is the authoritative gate per
`.claude/instructions/testing-standards.md` "Coverage".

Each package's tests can also be exercised in isolation via
`task <svc>:test` (driven by `scripts/pkg-test.sh <svc>`). Pytest's
rootdir discovery picks up `packages/<svc>/pyproject.toml` and
enforces the same `--cov-fail-under` floor for the package alone, so
focused dev loops fail on a per-package regression without waiting
for the workspace gate.

- **Bumping a floor** (coverage-improving PRs): run
  `task <svc>:test` locally, read the reported `TOTAL` percentage,
  update `--cov-fail-under=<N>` in `packages/<svc>/pyproject.toml`'s
  pytest addopts to one below the new TOTAL (so fluctuation across
  environments doesn't flake CI), and commit alongside the
  coverage-improving changes.
- **Lowering a floor** (rare): only when a deliberate change removes
  redundant coverage (e.g. a fixture refactor or a code path moved
  out to a different package). Explain the reason in the commit
  message body; never lower silently.
- **`--fast` and `--integration` modes** run without coverage collection
  (`--no-cov`). The floors are measured against `--unit` only —
  integration tests exercise Docker-backed service interactions that
  don't map cleanly onto `packages/*/src/` line coverage.

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

`task benchmark` runs the pytest-benchmark suite under
`packages/agent-auth/benchmarks/` covering the token hot path
(`parse_token`, `sign_token`, `verify_token`, `create_token_pair`)
and the SQLite store (`get_family` for a family with 200 scopes,
`get_token`, `create_token`). The suite is scheduled weekly via
`.github/workflows/benchmark.yml` — too noisy on shared runners to
gate every PR. Rationale and baseline-refresh procedure in
[`packages/agent-auth/benchmarks/README.md`](packages/agent-auth/benchmarks/README.md)
and [ADR 0029](design/decisions/0029-benchmark-suite.md).

### Schema migrations

The token store's SQLite schema is managed by a hand-rolled
numbered-SQL runner in `packages/agent-auth/src/agent_auth/migrations/`. Alembic /
yoyo would be disproportionate for a single-family schema and
would add a runtime dependency the project intentionally keeps
out (CLAUDE.md § Conventions). Rules:

- **Never modify an applied migration in place.** Each entry in
  `packages/agent-auth/src/agent_auth/migrations/_catalogue.py::CATALOGUE` is a
  pinned version. Changes land as a new `Migration(version=N+1, …)`
  tuple.
- **Every migration must be reversible.** Both `up_sql` and a
  matching `down_sql` are required. The runner refuses a partial
  rollback that would hit an irreversible step, so a missing
  `down_sql` blocks the whole roll-back path.
- **No `CREATE TABLE` / `ALTER TABLE` in application code.**
  Schema DDL lives exclusively in `_catalogue.py`;
  `scripts/verify-standards.sh` greps `packages/agent-auth/src/agent_auth/store.py`
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

PR titles use a Palantir-style prefix set (see
[ADR 0037](design/decisions/0037-palantir-commit-prefixes-and-commit-msg-block.md)).
The PR title becomes the squash-merge commit subject, and the
`pr-title` job in [`.github/workflows/pr-lint.yml`](.github/workflows/pr-lint.yml)
enforces the allowlist:

| Type           | Release impact | Use for                                                                                         |
| -------------- | -------------- | ----------------------------------------------------------------------------------------------- |
| `feature:`     | minor bump     | New user-visible feature or capability.                                                         |
| `improvement:` | patch bump     | User-visible enhancement of an existing feature (perf wins included).                           |
| `fix:`         | patch bump     | Bug fix visible to users.                                                                       |
| `deprecation:` | patch bump     | A user-visible API or behaviour is marked for removal but still works.                          |
| `migration:`   | patch bump     | A user-visible migration step ships (e.g. a one-time data move that runs at boot).              |
| `break:`       | major bump     | A user-visible API or behaviour is removed/changed incompatibly. Demoted to minor while in 0.x. |
| `chore:`       | no release     | Build / tooling / dependency / docs / refactor / CI / test changes with no user-visible impact. |

Optional `(scope)` is allowed (e.g. `feature(ci): add pr-lint workflow`).
Allowed scopes are listed below.

The default Conventional Commits prefixes (`feat:`, `perf:`,
`revert:`, `docs:`, `style:`, `refactor:`, `test:`, `build:`, `ci:`)
are **not** accepted by the lint. Map them as follows:

- `feat:` → `feature:`.
- `perf:` (user-visible) → `improvement:`. Pure under-the-hood perf
  with no user-observable change → `chore:`.
- `revert:` → the type the original commit would have had if it
  reverses a release-bumping change; otherwise `chore:`. Note the
  revert in the body.
- `docs:`, `style:`, `refactor:`, `test:`, `build:`, `ci:` → `chore:`
  unless the change has a user-visible effect, in which case pick the
  matching user-visible type.

Breaking changes carry a `BREAKING CHANGE:` footer in the
`==COMMIT_MSG==` block (see "Writing PRs" below). They normally bump
major; while the project is in the 0.x range they are demoted to a
minor bump via
[ADR 0040](design/decisions/0040-yaml-driven-release-workflow.md)
(carried over from
[ADR 0026](design/decisions/0026-semantic-release-autorelease.md)
§ Pre-1.0 behaviour). `break:` is the corresponding PR-title prefix.

Release-impact is computed by `scripts/changelog/version_logic.py`
from the `type:` field in each `changelog/@unreleased/*.yml`. A YAML's
`type:` matches a PR-title prefix one-to-one (`type: feature` ↔
`feature:`-prefixed PR), so the table above doubles as the bump
table. See
[`docs/release/rollout-pr-template.md`](docs/release/rollout-pr-template.md)
for the rollout context.

### Picking a type

The table above is enough for obvious cases. The recurring judgment
calls:

- **User-visible incorrect behaviour wins over everything.** A change
  that makes a broken thing work is `fix:` (patch bump) even when the
  implementation looks like a refactor, an improvement, or a test
  addition. Example: tightening an HMAC comparison that was previously
  timing-leaky is `fix(tokens):`, not `improvement(tokens):`.
- **`fix(deps):` vs `chore(deps):`.** Use `fix(deps):` when the bump
  patches a CVE that our code path actually reaches, or when the
  dependency update repairs wrong behaviour we observe. Routine version
  drift on Dependabot PRs — no security advisory, no behaviour change
  — is `chore(deps):` (no release). Dev-only dependency bumps are
  `chore(deps-dev):` regardless.
- **`chore:` vs `improvement:` on internal restructuring.** A pure
  refactor with no observable change is `chore:`. A refactor that
  incidentally improves an observable surface (e.g. cuts p99 latency
  visible to the caller) is `improvement:`. If the restructure also
  fixes a latent bug, split if the diff allows: one `chore:` for the
  restructure, one `fix:` for the defect.
- **`chore:` is the catch-all for non-user-visible changes.** Build
  / packaging tweaks, CI workflow changes, dev tooling, internal
  refactors, test-only changes, and docs all collapse into `chore:`
  under the new set. The previous distinction between `build:`,
  `ci:`, `docs:`, `style:`, `refactor:`, `test:` is no longer
  encoded in the prefix; reach for the **scope** to disambiguate
  (e.g. `chore(ci): bump action SHA`, `chore(docs): rewrite README`,
  `chore(deps-dev): bump pytest`).
- **`improvement:` and `feature:` together.** If an improvement
  changes user-observable semantics (new endpoint, new config knob,
  changed defaults), it is `feature:`; the perf or quality win is a
  side-effect described in the body. Same-contract better-numbers
  changes are `improvement:`.
- **`deprecation:` vs `break:`.** Deprecation announces removal but
  keeps the surface working — a `migration:` or `break:` typically
  follows in a later release.

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

## Changelog entries (`changelog/@unreleased/*.yml`)

Every PR adds at least one YAML file under `changelog/@unreleased/`
describing the user-visible change, OR carries the `no changelog`
label to opt out (typo fixes, internal refactors with no behaviour
change, etc.). The PR-time
[`Changelog Lint`](.github/workflows/changelog-lint.yml) workflow
enforces this on every push. The release workflow (#296, in flight)
will consume these files, compute the next version, and render
`CHANGELOG.md` + GitHub Release notes from them — replacing the
commit-message-derived flow described under
[Release process](#release-process).

Filename: `pr-<N>-<slug>.yml` where `<N>` is the PR number and
`<slug>` is a short word-or-two identifier (lowercase letters, digits,
dashes, underscores). Example: `pr-295-yaml-schema.yml`. Multiple
files per PR are allowed when the change has more than one logically
distinct user-visible effect.

Schema (the lint rejects unknown keys, so this is the full surface):

```yaml
type: feature      # required: feature | improvement | fix | break | deprecation | migration
feature:           # required: nested key matches `type:` for parser disambiguation
  description: |   # required: free-text release note. Markdown allowed.
    First-class line that becomes the bullet in CHANGELOG.md.
  links:           # optional: extra URLs surfaced in the release notes
    - https://github.com/aidanns/agent-auth/issues/295
packages:          # optional: omit for a workspace-wide change
  - agent-auth
  - agent-auth-common
release-as: 1.0.0  # optional: force a specific next version (must be > inferred)
```

### Picking a `type:`

Mirrors the conventional-commit prefixes used in PR titles. The
release-impact column is the source of truth in
`scripts/changelog/version_logic.py` (the lint and the upcoming
release workflow share it):

| `type:`       | 0.x impact      | 1.x+ impact | Use for                                                            |
| ------------- | --------------- | ----------- | ------------------------------------------------------------------ |
| `feature`     | minor           | minor       | New user-visible feature or capability.                            |
| `improvement` | patch           | patch       | Enhancement to an existing feature.                                |
| `fix`         | patch           | patch       | Bug fix visible to users.                                          |
| `break`       | minor (demoted) | major       | Backwards-incompatible change to a user-facing surface.            |
| `deprecation` | patch           | patch       | Marking a feature deprecated (without removing it yet).            |
| `migration`   | patch           | patch       | Schema, config, or filesystem migration that requires user action. |

`break` demotes to a minor bump while the project is in the `0.x`
range (per ADR 0026 § Pre-1.0 behaviour). Force the graduation to
`1.0.0` with `release-as: 1.0.0` on the breaking change's YAML.

### `packages:` and `release-as:`

- **`packages:`** — list workspace members the change affects. Omit
  the field for a workspace-wide change. The lint validates each
  entry against `packages/*/pyproject.toml` `[project].name`. Today
  every entry contributes to a single workspace-level bump (#275
  graduates to per-package release trains).
- **`release-as:`** — set when forcing a specific next version
  (typically the `1.0.0` graduation). The lint requires the value
  to be strictly greater than the version inferred from all
  unreleased entries — equal or lower fails. Multiple entries
  with conflicting `release-as` values also fail; multiple entries
  with the same value pass (idempotent agreement).

### Authoring path

Three ways to satisfy the lint, in increasing order of automation:

1. **Hand-author the YAML** — write
   `changelog/@unreleased/pr-<N>-<slug>.yml` and commit it alongside
   the diff. The schema is enforced by
   [`Changelog Lint`](.github/workflows/changelog-lint.yml). Use this
   when you want to fine-tune the entry (e.g. `packages:` filters or
   a `release-as` override).
2. **Use the scaffolding helper** — `task changelog:add` (alias:
   `task changelog-add`) writes a templated entry from CLI flags or
   walks an interactive prompt. Same schema, less boilerplate. See
   [the CLI section below](#changelog-add-cli).
3. **Use the bot** — uncomment the `==CHANGELOG_MSG==` block in the
   PR template and put the release-note text between the markers.
   The
   [`Changelog Bot`](.github/workflows/changelog-bot.yml) workflow
   composes the YAML, derives the `type:` from the PR-title prefix,
   and commits the file to the PR branch on the next push. See
   [the marker section below](#changelog-bot-markers).

The `no changelog` label opt-out skips the file-presence check but
schema validation still runs over any files that *are* present, so
an opt-out PR can't sneak in malformed YAML.

### `task changelog:add` CLI

`task changelog:add` (alias `task changelog-add`, matching the
spelling in #297) drives `scripts/changelog/add.py`. The CLI runs the
same validation gates as
[`Changelog Lint`](.github/workflows/changelog-lint.yml) before
writing — the `--type`, `--packages`, and `--release-as` checks reuse
`scripts/changelog/version_logic.py` directly, so a CLI-authored
entry that *the CLI accepts* is guaranteed to also pass the CI lint.

**Interactive mode** (no flags) walks through type, description,
optional packages, PR number (auto-detected from `gh pr view`), and
optionally `release-as`:

```bash
task changelog:add
```

`$EDITOR` is opened for the description when `--editor` is passed;
otherwise the prompt accepts a single line. Pass `--release-as` (with
or without a value) to be prompted for an override; without the flag
the prompt is skipped so accidental graduations are not possible.

**Non-interactive mode** is for scripted use (e.g. inside another
agent / CI workflow). Every required field is read from flags:

```bash
task changelog:add -- \
  --type fix \
  --description "Tighten the HMAC comparison so it is constant-time." \
  --pr 123
```

Optional flags:

- `--packages agent-auth,agent-auth-common` — comma-separated
  workspace member list. Validated against `packages/*/pyproject.toml`
  `[project].name`. Omit for workspace-wide entries.
- `--release-as 1.0.0` — force a specific next version. The CLI
  re-runs `validate_release_as` against the new entry plus every
  existing entry under `changelog/@unreleased/`, so a violation
  surfaces synchronously rather than after CI.
- `--editor` — open `$EDITOR` for multi-line input in interactive
  mode. Ignored when `--description` is also passed.
- `--current-version 0.4.2` — override the current version (default
  is `git describe --tags --abbrev=0 --match v*.*.*`, falling back to
  `0.0.0` when no tag exists yet).

The slug after `pr-<N>-` is generated from a small bundled wordlist
(`scripts/changelog/wordlist.py`); two random words joined with `-`.
The CLI retries on filename collisions inside one PR's directory.

When `stdin` is not a TTY (e.g. CI, piped invocations), the
interactive walk-through is suppressed — pass every required flag or
the CLI exits non-zero with a "non-interactive mode requires …"
message rather than blocking on `input()`.

A non-blocking pre-push lefthook hook (`scripts/changelog/add.sh --check`) prints a one-line warning to stderr when the local branch
has no `changelog/@unreleased/pr-<N>-*.yml` entry vs. `origin/main`.
The hook is advisory — the PR-time `Changelog Lint` workflow is the
authoritative gate. Pass `--strict` (manual escape hatch) to make
the warning a hard local failure.

### Changelog-bot markers

The PR template ships two optional markers that the changelog bot
reads (alongside the `==COMMIT_MSG==` block from
[ADR 0037](design/decisions/0037-palantir-commit-prefixes-and-commit-msg-block.md)).
Both are commented out by default; uncomment one when you want the
bot's behaviour:

- **`==CHANGELOG_MSG==` … `==CHANGELOG_MSG==`** — content becomes the
  `description:` field of an auto-created
  `changelog/@unreleased/pr-<N>-bot-<hash>.yml`. The bot maps the
  PR-title prefix to the YAML `type:` per
  [ADR 0037](design/decisions/0037-palantir-commit-prefixes-and-commit-msg-block.md)'s
  table (`feature:` -> `feature`, `fix:` -> `fix`, ...). For
  `chore:` PRs the bot leaves a comment instead — `chore:` PRs need
  the opt-out marker below.
- **`==NO_CHANGELOG==`** — apply the `no changelog` label so the
  changelog-file requirement is bypassed. Required for `chore:` PRs
  with no user-visible change; optional for any PR where you've
  decided no changelog entry is appropriate. Removing the marker on
  the next push removes the label (only when the bot applied it; a
  maintainer-applied label is preserved).

The bot **stops modifying** the YAML it wrote once any non-bot commit
touches the file. Hand-edit freely after the bot bootstraps the
entry: a `git commit` from your identity claims authorship and the
bot leaves the file alone for the rest of the PR's life. Re-engaging
the bot is an explicit operation (revert your edit), not the default.

Setup instructions for the bot's GitHub App live in
[`docs/release/changelog-bot-setup.md`](docs/release/changelog-bot-setup.md).
Architectural rationale (dedicated App, lockout strategy,
loop-prevention guards) lives in
[ADR 0039](design/decisions/0039-bot-mediated-changelog-authoring.md).

## Release process

Releases are driven by `changelog/@unreleased/pr-*.yml` files (one per
PR — see [Changelog entries](#changelog-entries-changelogunreleasedyml))
and two GitHub Actions workflows. Rationale and trade-offs in
[ADR 0040](design/decisions/0040-yaml-driven-release-workflow.md);
the supply-chain artefact chain (SBOMs, cosign, SLSA-L3) carries over
from
[ADR 0016](design/decisions/0016-release-supply-chain.md) and
[ADR 0020](design/decisions/0020-slsa-build-provenance.md).

### Default flow

1. Land your PR on `main` with a `changelog/@unreleased/pr-<N>-*.yml`
   entry describing the change. The PR-time `changelog-lint` job
   enforces the schema.
2. The `Release PR` workflow
   ([`.github/workflows/release-pr.yml`](.github/workflows/release-pr.yml))
   runs on every push to `main`. It:
   - Reads every `@unreleased/*.yml`.
   - Computes the next version via
     `scripts/changelog/version_logic.py` (the same library the lint
     uses, so the version a contributor sees in CI matches what the
     release will bump to).
   - Renames the YAMLs from `@unreleased/` to `<X.Y.Z>/`.
   - Prepends a new `## [X.Y.Z] - YYYY-MM-DD` section to
     `CHANGELOG.md`, grouped by entry type
     (break → feature → improvement → fix → deprecation → migration).
   - Pushes the diff to a `release/<X.Y.Z>` branch and opens (or
     updates) a PR titled `chore(release): <X.Y.Z>`. The PR body is
     rendered from the YAMLs and includes a `==COMMIT_MSG==` block
     so the standard `pr-lint` checks pass.
   - Subsequent pushes to `main` while the release PR is open
     refresh the same branch + PR. If the *computed version* changes
     (e.g. a new YAML lifts the bump from patch to minor), the
     workflow closes the stale `release/<old>` PR and opens a fresh
     `release/<new>` one.
3. Review the release PR like any other change. Auto-merge is
   acceptable for routine releases; hold and review when the rendered
   notes mention behaviour the consumer needs to act on.
4. Merging the release PR fires the `Release Tag` workflow
   ([`.github/workflows/release-tag.yml`](.github/workflows/release-tag.yml)).
   It validates the head ref + title (both must match the
   `release/X.Y.Z` / `chore(release): X.Y.Z` shape), tags
   `v<X.Y.Z>` on the merge commit using the release App's
   installation token, and creates the GitHub Release with the body
   re-rendered from the *moved* YAMLs.
5. The tag push triggers the existing `Release Publish` workflow
   ([`.github/workflows/release-publish.yml`](.github/workflows/release-publish.yml)).
   It builds the sdist + wheel with `uv build`, generates an SPDX
   SBOM per artifact with Syft, signs everything with keyless cosign
   (Sigstore OIDC), and attaches the SLSA-L3 provenance attestation.
   Verification recipe: see
   [`SECURITY.md` → Supply-chain artifacts](SECURITY.md#supply-chain-artifacts).

### Manual escape hatch — `task release`

`task release` runs `scripts/release.sh`, which dispatches the
`Release PR` workflow on `main` via `gh workflow run release-pr.yml`.
Use it to force a refresh of the release PR (e.g. after editing a
`changelog/@unreleased/*.yml` directly via the GitHub UI), or when
you want to retry the workflow after a transient failure. It does
**not** cut a tag on its own — tagging always happens inside
`release-tag.yml` when the release PR merges.

### Forcing a specific version (`release-as`)

Set `release-as: <X.Y.Z>` on any `changelog/@unreleased/*.yml` to
force the release workflow to bump to that version instead of the
inferred one. The override must be strictly greater than the
inferred value (the lint checks this). Use it for things like
graduating to `1.0.0` or skipping ahead of a `release-as` mistake.
Multiple entries may carry the same `release-as` value (idempotent
agreement); conflicting values fail the lint.

### Author guidance for changelog entries

`CHANGELOG.md` is rendered from the YAML files, not hand-edited:

- The bullet text comes from the YAML's `description:` field, not
  the PR title. Treat the description as user-facing prose: include
  the rationale and the upgrade path, not the implementation detail.
- Put deeper context (test plan, screenshots, design rationale) in
  the `==COMMIT_MSG==` block + `## Review notes`, the same as any
  other PR. Those surfaces are reviewer-facing; the YAML drives
  everything that ends up in `CHANGELOG.md` and the GitHub Release.
- Reference the closing issue with `Closes #N` in the
  `==COMMIT_MSG==` block trailers so GitHub closes the issue when
  the PR merges. The YAML's `links:` field is for *additional*
  context (RFC URLs, related discussions); `Closes #N` is the
  primary linking convention.
- Mark breaking changes with `type: break` in the YAML *and* a
  `BREAKING CHANGE:` footer in the `==COMMIT_MSG==` block (paired
  with the `break:` PR-title prefix). Pre-1.0, the bump table
  demotes them to a minor bump per
  [ADR 0040](design/decisions/0040-yaml-driven-release-workflow.md)
  (carried over from ADR 0026).

Hand edits to historical `CHANGELOG.md` content are preserved
across releases — the renderer prepends new sections, it doesn't
rewrite existing ones. Older sections cut by semantic-release keep
their format; the new sections use the prose style above.

### Writing PRs

The PR description is the authoring surface for **two distinct
audiences**:

- The `==COMMIT_MSG==` block becomes the squash-merge commit body —
  it enters `git log` and the GitHub release notes. Treat it like a
  commit message: prose paragraphs, ≤ 72 char wrap, trailers at
  the end. No markdown headings, bullet lists, or task checkboxes.
- The `## Review notes` section is for the reviewer — test plan,
  screenshots, deploy notes, gotchas. It does **not** enter git
  history. Use whatever markdown you like.

The split is enforced by [`.github/workflows/pr-lint.yml`](.github/workflows/pr-lint.yml):
the `pr-title` job validates the PR-title prefix, the
`pr-body-commit-msg` job validates the `==COMMIT_MSG==` block, and
the `validator-self-test` job exercises the validator against
fixtures so a regression in the validator can never silently approve
PRs.

#### Worked example

A PR that adds a feature, references a tracking issue, and notes a
breaking change for reviewer attention:

```markdown
==COMMIT_MSG==
Wire the gpg-bridge probe into agent-auth health.

The /agent-auth/health response now embeds the latest probe status
from gpg-bridge so a single GET surfaces both services. The probe
runs every 30s and is cached; stale entries fail-open with status
"degraded".

Closes #123
Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>
==COMMIT_MSG==

## Review notes

### Test plan

- [ ] `task check`
- [ ] `task test`
- [ ] manual: `curl -k https://localhost:8443/agent-auth/health` returns
      `{"status":"healthy","probes":{"gpg-bridge":"healthy"}}`.

### Screenshots

![healthy probe](https://...)
```

PR title for that example: `feature(agent-auth): expose gpg-bridge probe in /health`.

A `chore:` PR (no release entry) follows the same shape — the
`==COMMIT_MSG==` block still records the rationale even though no
CHANGELOG line will be generated.

#### Merge mechanics — the `automerge` label

The merge bot in
[`.github/workflows/merge-bot.yml`](.github/workflows/merge-bot.yml)
pastes the `==COMMIT_MSG==` block as the squash-merge commit body
when the PR carries the `automerge` label and every required check
is green. The bot is the merge path of record:

1. Once review is satisfied, apply the `automerge` label to the PR
   (`gh pr edit <pr> --add-label automerge`). The label is the
   single "ready to merge" signal both maintainer and CI agents
   use; it replaces the legacy `gh pr merge --auto --squash` path.
2. The bot listens on `pull_request: labeled` (proceed when the
   new label is `automerge`) and `check_suite: completed`
   (sticky-label retry once the last required check turns green
   AFTER the label was set). Either trigger is enough; you can
   apply the label before checks finish.
3. On any pre-merge failure (`==COMMIT_MSG==` block missing /
   malformed, required check failed, `Signed-off-by:` trailer
   missing from the block) the bot posts a
   `Claude: Cannot merge — <reason>` comment and exits non-zero.
   The label stays applied, so a fix-and-push retriggers the bot
   automatically via `check_suite: completed`. Remove the
   `automerge` label only if you want the bot to stop trying.
4. On success the bot posts `Claude: Merged via bot.` and the
   squash commit lands on `main` with the `==COMMIT_MSG==` block
   as its body verbatim — sign-off, `Closes #N`, and any
   `BREAKING CHANGE:` footer all round-trip into git history.

The `Signed-off-by:` trailer must already sit inside the
`==COMMIT_MSG==` block — the bot authors no commits and pastes the
block as the squash-merge body. The
[`PR Lint`](.github/workflows/pr-lint.yml) workflow rejects a PR
whose block lacks the trailer at PR-author time so the bot
doesn't have to. Add the trailer manually if you're hand-editing
the block; if you ran `git commit -s` on the PR commits, copy the
same `Signed-off-by:` line into the block.

Maintainer setup of the merge-bot GitHub App is documented in
[`docs/release/merge-bot-setup.md`](docs/release/merge-bot-setup.md).
The interim maintainer-paste mechanics that pre-dated the bot are
preserved in
[`docs/release/rollout-pr-template.md`](docs/release/rollout-pr-template.md)
for historical reference.

### Release App setup

`release-tag.yml` mints a short-lived installation token via
[`actions/create-github-app-token`](https://github.com/actions/create-github-app-token)
to push the `vX.Y.Z` tag. An App token is required because tag
pushes from the default `GITHUB_TOKEN` do **not** fire downstream
`on: push: tags:` workflows — the SLSA / SBOM / cosign chain in
`release-publish.yml` would silently break.

The repo currently uses the App registered for the previous
semantic-release flow (kept named `semantic-release-agent-auth`
pending a follow-up rename — see ADR 0040 § Follow-ups). Repo
secrets:

- `SEMANTIC_RELEASE_APP_ID` — the App's numeric ID.
- `SEMANTIC_RELEASE_APP_PRIVATE_KEY` — the App's `.pem` private key
  (full contents, including the `-----BEGIN/END` markers and the
  trailing newline).

To re-register or rotate the App:

1. Create or edit the App at
   [github.com/settings/apps](https://github.com/settings/apps).
   Required permissions: **Contents: Read & write** (push tags,
   create releases). All other permissions can be **No access**.
2. Install it against `aidanns/agent-auth` only — not *All
   repositories*.
3. Generate a private key on the App's settings page and download
   the `.pem`.
4. Update the two repo secrets above in
   [Settings → Secrets and variables → Actions](https://github.com/aidanns/agent-auth/settings/secrets/actions).
5. Revoke any superseded private keys from the App's settings page.

The version string embedded in the distributed package is derived
from the git tag at build time via `setuptools-scm`; no other
version file needs updating.

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

Or alias the flag once per clone so it doesn't need to be typed every commit:

```bash
git config --local alias.c 'commit -s'
# then: git c -m "feat(thing): new thing"
```

Git has no native config option that makes `git commit` always add the
trailer (`format.signoff` only affects `git format-patch`, and
`commit.signoff` is not recognised). A `prepare-commit-msg` hook is
the alternative for contributors who'd rather not change their
muscle memory.

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

### Signed commits inside the devcontainer

The repo's `main` ruleset requires signed commits, but devcontainers
generally don't have access to the host's GPG keys — exporting them
into the container would defeat the security model. This project
solves it with a host-side signing service (`gpg-bridge`) and a
container-side `gpg`-shaped frontend (`gpg-cli`) that forwards
sign / verify requests over HTTPS. See
[ADR 0033](design/decisions/0033-gpg-bridge-cli-split.md) for the
full architecture.

To wire a fresh devcontainer to the host's `gpg-bridge`:

1. **On the host**, mint a `gpg:sign`-scoped agent-auth access token:

   ```bash
   task agent-auth -- token create --scope gpg:sign=allow --json
   ```

   Copy the `access_token` field. It's shown once.

2. **In the devcontainer**, run the setup task with the token and
   the bridge URL:

   ```bash
   task setup-devcontainer-signing -- \
     --token <ACCESS_TOKEN> \
     --bridge-url https://host.docker.internal:8443
   ```

   Optional flags: `--ca-cert-path <PATH>` if the bridge's TLS
   certificate is signed by a CA the container's trust store doesn't
   include, and `--timeout-seconds <N>` to override the per-request
   timeout (default 30s).

The setup task writes the `gpg-cli` config to
`$XDG_CONFIG_HOME/gpg-cli/config.yaml` (mode `0600`) and runs two
`git config --local` calls in the current clone:

- `gpg.program = gpg-cli` — git delegates sign / verify to the
  bridge instead of looking for `gpg` on `PATH`.
- `commit.gpgsign = true` — every `git commit` signs without needing
  `-S`.

Override per-commit with `git -c commit.gpgsign=false commit` when
you need an unsigned commit (e.g. an in-flight rebase that doesn't
touch `main`).

The setup is idempotent — re-running with the same arguments
overwrites the config file and reasserts the git-config values.
Re-run after a `gpg-bridge` URL change or a token rotation. The
script is also runnable directly as `scripts/setup-devcontainer-signing.sh`
if `go-task` isn't available.

### Tag signing under the YAML-driven release flow

The release tag (`vX.Y.Z`) is created by `release-tag.yml` using the
release App's installation token, so no maintainer signing key is
involved at tag time. Local signing setup applies only to the
maintainer's own commits on PR branches and on the release-PR merge
commit (handled by GitHub's web-flow signer when the maintainer
clicks "squash and merge").
