# Changelog

## [0.17.3] - 2026-05-02

### Fixes

- Trigger `dependabot-adaptor-bot.yml` on `pull_request_target` so the App credentials resolve under the Dependabot secrets context. (#543)

## [0.17.2] - 2026-05-02

### Improvements

- pr-lint.yml jobs now consume the released pr-lint-validator wheel from GitHub Releases instead of in-tree scripts. (#506)

## [0.17.1] - 2026-05-02

### Improvements

- `pr-lint-validator` backports rule 8 (no leading subject line in the `==COMMIT_MSG==` block) so the wheel matches the canonical in-tree script. (#500)

## [0.17.0] - 2026-05-02

### Features

- Extract the PR-title and `==COMMIT_MSG==` block validators into a
  new `pr-lint-validator` workspace package shipped as a wheel and
  console script on every release. (#489)

## [0.16.6] - 2026-04-28

### Improvements

- `merge-bot` now closes linked issues referenced in the squash commit body, working around GitHub's App-token auto-close gap. (#434)

## [0.16.5] - 2026-04-28

### Improvements

- Release-PR Signed-off-by trailer now identifies the agent-auth-release-bot App. (#433)

## [0.16.4] - 2026-04-28

### Improvements

- Release-note entries now end with `(#N)` so a reader of
  `CHANGELOG.md`, the GitHub release body, or the release-PR
  `==COMMIT_MSG==` block can click straight through to the
  originating PR for the verbose context that the terse YAML
  `description:` field omits. The PR number is derived from the
  YAML filename via `pr-<N>-<slug>.yml`; a new PR-time lint check
  fails non-conforming filenames so the renderer always has a
  number to derive. The wrap algorithm also keeps `(#N)` bound to
  the preceding token so a soft-wrap never visually divorces the
  link from the entry it belongs to. (#426)

## [0.16.3] - 2026-04-28

### Fixes

- Per-package wheel and sdist filenames once again carry the
  release-tag's version (e.g. `agent_auth-0.16.1-py3-none-any.whl`)
  instead of setuptools-scm's `0.0.0+unknown` fallback. `v0.16.0`
  shipped 70 supply-chain assets versioned `0.0.0+unknown` because
  each `packages/<svc>/pyproject.toml`'s `[tool.setuptools_scm]`
  block did not set `root`, so `uv build --all-packages` ran
  setuptools-scm from a per-package directory that is not a git
  root and quietly fell back. Pinning `root = "../.."` in every
  package points setuptools-scm at the workspace's `.git`. The
  `cosign verify` recipe in `SECURITY.md` § Supply-chain artifacts
  matches the next release tag's assets again.

  Two regression gates ride the fix: a `task test`-time check
  (also exercised by `release-dryrun.yml`) that asserts every
  workspace package pins `root = "../.."` and that built wheels
  don't carry the fallback string, and a fail-fast step in
  `release-publish.yml` between `uv build` and `cosign sign`
  that aborts the publish path if any artefact filename does
  not contain the release-tag's version.

## [0.16.2] - 2026-04-28

### Improvements

- Release-PR squash-merge commit bodies (rendered by
  `render_commit_msg_block`) no longer open with a redundant
  `Release vX.Y.Z.` paragraph — the version is already in the
  `chore(release): X.Y.Z` subject, so the body now opens directly
  with the first per-section paragraph (`Improvements: ...`,
  `Fixes: ...`). `render_release_notes` (the GitHub Release surface)
  keeps its `Release vX.Y.Z.` header where the version is
  load-bearing.
- The release-PR `==COMMIT_MSG==` block now emits one bullet per
  changelog entry under each section heading, regardless of entry
  count. The shape is identical for single-entry and multi-entry
  sections, so `git log` and the GitHub release page scan
  uniformly. Replaces the historical semicolon-joined prose
  paragraph per section.

## [0.16.1] - 2026-04-27

### Improvements

- `release-publish.yml` now accepts a `workflow_dispatch` trigger
  with a required `tag` input so a maintainer can run
  `gh workflow run release-publish.yml -f tag=<TAG>` to re-publish
  an existing tag whose original `push: tags:` run produced an
  incomplete asset set. The dispatched run threads
  `inputs.tag || github.ref_name` through the concurrency group,
  both `actions/checkout` ref: fields, and the
  `gh release upload` / `gh release view` env blocks so the
  build / sign / SBOM / SLSA-provenance chain binds to the tag's
  commit (not `main`'s tip). `gh release upload --clobber`
  overwrites partial assets idempotently. Adds SECURITY.md
  § Supply-chain artifacts notes for tag ranges where the
  per-package verification recipe will not match the release
  page: `v0.6.0..v0.10.0` ship the legacy single-package shape;
  `v0.11.0..v0.15.3` have incomplete asset sets pending the
  post-merge re-publish ops driven by #372; `v0.16.0` carries
  `0.0.0+unknown`-versioned wheels per #408.

## [0.16.0] - 2026-04-27

### Features

- Each `packages/<svc>/install.sh` no longer requires `uv` at install time — only Python 3.11+ with the stdlib `venv` module. The release pipeline now publishes one wheel + sdist + `.sha256` + SBOM + cosign bundle per workspace package (`uv build --all-packages`); install scripts download the service wheel + every workspace-dep wheel, verify sha256, install into `~/.local/share/<svc>/venv`, and symlink entrypoints into `~/.local/bin`. SLSA Build L3 provenance subjects now enumerate every wheel + sdist in the release. `--local <dir>` lets CI exercise the install path end-to-end without a published release. See ADR 0044.

### Improvements

- The `release-publish.yml` `verify-assets` post-publish gate and
  the `release-dryrun.yml` PR-time gate now assert exact per-package
  counts derived from the workspace member count, instead of the
  pre-#324 "at least one" thresholds. With N workspace members the
  gates expect N wheels, N sdists, 2N `.sha256` sidecars, 2N SBOMs
  (one per artefact), and 4N cosign signature bundles (one per
  artefact + one per SBOM). A regression that drops one package's
  asset set (e.g. a `gh release upload` glob change that misses
  `*.spdx.json.sig.bundle`, or a `uv build --all-packages` skip)
  will now fail the gate; the previous `-ge 1` thresholds would
  silently pass. Adds `.sha256` sidecar enumeration, which the
  earlier check did not cover at all, and a `actions/checkout`
  step on `verify-assets` so the workspace member count is read
  from `packages/*/pyproject.toml` rather than hard-coded.

## [0.15.3] - 2026-04-27

### Improvements

- `merge-bot` now fires on two additional event surfaces so
  `automerge`-labeled PRs no longer wedge on state transitions
  that produced no merge-bot trigger event before. New
  `pull_request_review` trigger (types `submitted` and
  `dismissed`) re-fires the bot when a review state changes,
  closing the gap where `automerge` was applied before the
  final approval landed and no `workflow_run.completed` was
  tied to the review submission. New `push: branches: [main]`
  trigger plus a `sweep` job lists every open `automerge` PR
  whenever `main` advances and dispatches the existing per-PR
  `merge` job via `gh workflow run merge-bot.yml -f pr_number=<N>`, closing the gap where a labeled PR was
  up-to-date when the bot last fired and then `main` moved
  with nothing else to re-trigger the bot. Sweep concurrency
  (`merge-bot-sweep`, `cancel-in-progress: true`) collapses a
  burst of merges to `main` into one sweep; per-PR concurrency
  (`merge-bot-<n>`) is unchanged. The sweep uses the default
  `GITHUB_TOKEN` (with `actions: write` added to the
  workflow-level `permissions:` block) rather than the App
  token, so no additional App permission grant is required.

## [0.15.2] - 2026-04-27

### Improvements

- Relax the `==COMMIT_MSG==` block validator to permit plain `-` /
  `*` bullets and `1.` numbered lists. The kernel/cbea.ms
  enumerated-changes form often reads better in `git log` than the
  run-on prose paragraphs authors fell back to under the previous
  blanket no-markdown rule. The audience-split defence — keep
  test-plan, deploy-checklist, and screenshot content out of
  `git log` — is now carried by three structural bans (markdown
  headings, task checkboxes, image embeds) rather than a
  blanket markdown ban.

## [0.15.1] - 2026-04-27

### Improvements

- `merge-bot` now auto-updates a PR whose head sits behind `main`
  instead of treating the merge API's 405 as a hard failure. After
  the green-check and DCO gates the bot re-fetches
  `mergeStateStatus`; if the value is `BEHIND`, it calls
  `PUT /pulls/{n}/update-branch` (with `expected_head_sha` pinned),
  posts a one-line `Claude: Branch was behind main — updated; …`
  comment, and exits 0. The new head SHA retriggers every PR-gating
  CI workflow, and the existing `workflow_run.completed` trigger
  re-fires merge-bot for the second-pass merge once those workflows
  complete. A loop guard caps the worst case at three auto-updates
  per PR — the fourth `BEHIND` state surfaces
  `Claude: Auto-update loop exceeded — main is moving too fast or this PR keeps falling behind. Investigate manually.` and fails the
  job rather than burning further CI cycles. Requires
  `contents: write` on both the workflow's top-level `permissions:`
  block and the App installation.

## [0.15.0] - 2026-04-27

### Features

- Add CI gates that catch broken release-publish pipelines before
  they ship: a PR-time dry-run (`release-dryrun.yml`) that runs the
  same build commands the publish path will run via the new shared
  `scripts/build-release-artifacts.sh`, and a post-publish
  `verify-assets` job in `release-publish.yml` that fails the
  workflow if any expected asset (wheel, sdist, SBOM, cosign
  bundle, SLSA provenance) is missing from the GitHub release.
  Closes the gap that hid the workspace-split release-build
  regression for ~13 consecutive releases. The dry-run is
  informational (`continue-on-error: true`) until #324 unbreaks
  the build; a follow-up config-only PR will move it to required
  status checks once the soak window passes.

## [0.14.1] - 2026-04-26

### Improvements

- `release-publish.yml` now mints an installation token from the
  `agent-auth-release-bot` GitHub App and passes it as `GH_TOKEN`
  to the `gh release upload` step, instead of relying on the
  default `GITHUB_TOKEN`. Asset-upload events on the release
  timeline and audit trail now show `agent-auth-release-bot[bot]`
  as the actor, matching `release-pr.yml` and `release-tag.yml`
  so all three legs of the release pipeline share a single bot
  identity. The App's existing `contents: write` installation
  permission covers the upload; the artefact set, cosign keyless
  signing, SBOM generation, and the SLSA provenance reusable
  workflow are unchanged.

## [0.14.0] - 2026-04-26

### Features

- Restructure the PR template around a `==COMMIT_MSG==` fenced
  block (squash-merge commit body) plus a clearly separated
  `## Review notes` section (review-only). The new `PR Lint`
  workflow enforces the Palantir-style PR-title prefix allowlist
  (`feature` / `improvement` / `fix` / `break` / `deprecation` /
  `migration` / `chore`) and validates the `==COMMIT_MSG==` block
  (line wrap, no markdown, BREAKING CHANGE positioning, trailer
  parsing). A sibling self-test job exercises the validator
  against every fixture on every PR so a regression in the
  validator can never silently approve every PR.
- Introduce the file-per-change YAML schema for `changelog/@unreleased/`
  entries and a PR-time CI lint that enforces file presence, naming,
  schema validity, and the `release-as` invariant. Foundation for the
  upcoming release workflow rewrite.
- Merge bot extracts the `==COMMIT_MSG==` block as the squash-merge
  commit body, replacing the maintainer-paste step from #290.
  Triggered by the `automerge` label on a PR; refuses to merge if
  any required check failed, the block is malformed, or the block
  lacks a `Signed-off-by:` trailer (now enforced PR-time by the
  `pr-lint` validator). Runs as a dedicated `agent-auth-merge-bot`
  GitHub App (least-privilege scoped); see
  `docs/release/merge-bot-setup.md` for the one-time maintainer
  setup.
- Add the `agent-auth-changelog-bot` GitHub App and the
  `Changelog Bot` workflow that backs it. Contributors uncomment a
  `==CHANGELOG_MSG==` block in the PR template and the bot composes
  a `changelog/@unreleased/pr-<N>-*.yml`, derives the YAML `type:`
  from the PR-title prefix, and commits the file to the PR branch.
  A sibling `==NO_CHANGELOG==` marker applies the `no changelog`
  label so the changelog lint bypasses the file-presence check.
  Reconciliation with manual edits is via author-history lockout:
  once any non-bot commit touches the file, the bot leaves it alone
  for the rest of the PR's life. Loop-prevention via a workflow
  `if:` plus a head-commit-author check on every run.
- Add `task setup-devcontainer-signing` (and the underlying
  `scripts/setup-devcontainer-signing.sh`) for one-shot wiring of
  devcontainer commit signing to the host's `gpg-bridge`. Writes
  the gpg-cli config to `$XDG_CONFIG_HOME/gpg-cli/config.yaml` at
  mode 0600 and runs `git config --local` for `gpg.program=gpg-cli`
  and `commit.gpgsign=true`. Unblocks #217 (re-enable
  `required_signatures` on the `main` ruleset).
- Replace semantic-release with a YAML-driven release workflow that
  opens a release PR per push to main and tags + publishes on its
  merge. The release version is computed from
  `changelog/@unreleased/*.yml` files via the shared `version_logic`
  library. Decommissions `.releaserc.mjs`, `package.json`,
  `package-lock.json`, the npm Dependabot ecosystem, and the legacy
  `scripts/release.sh` local-tag flow (the script is repurposed as
  a workflow-dispatch wrapper). See ADR 0041.
- Add `task changelog:add` (alias `task changelog-add`) for scaffolding `changelog/@unreleased/*.yml` entries. Interactive prompt-driven walk-through by default, fully flag-driven (`--type / --description / --pr`) when stdin is not a TTY. Joins the hand-authored (#295) and bot-mediated (#298) paths as a third authoring mode; all three converge on the same on-disk YAML format.
- `gpg-cli` now persists a refresh-capable agent-auth credential pair and rotates it transparently. A 401 `token_expired` from `gpg-bridge` triggers `POST /agent-auth/v1/token/refresh`; `refresh_token_expired` falls back to `/token/reissue` (blocks on host JIT approval). The new pair is written to `$XDG_CONFIG_HOME/gpg-cli/config.yaml` at mode `0600` *before* the retried request runs, honouring the single-use refresh contract from ADR 0011. `scripts/setup-devcontainer-signing.sh` writes the new schema (`--access-token` / `--refresh-token` / `--family-id` / `--auth-url`); the old single-`--token` schema is rejected at load time with a directive to re-run the script. Operators who installed `gpg-cli` before this release must re-run `setup-devcontainer-signing.sh` to bootstrap a refresh-capable credential pair.
- Add `--version` to every argparse-backed CLI in the workspace (`agent-auth`, `agent-auth-notifier`, `gpg-bridge`, `things-bridge`, `things-cli`, `things-client-cli-applescript`); the version string is resolved at runtime from installed distribution metadata via `importlib.metadata.version`. `gpg-cli` keeps its existing `--version` (gpg-shaped output for git's probe) and gains a new `--gpg-cli-version` flag that prints the package version. Lets operators verify which build of a CLI is installed in a host or devcontainer.
- `gpg-bridge` now optionally holds signing-key passphrases in
  the system keyring (per ADR 0042). New
  `gpg-bridge passphrase set / clear / list` subcommands manage
  per-fingerprint entries; on each sign request the bridge feeds
  any stored passphrase to the host `gpg` subprocess via
  `--passphrase-fd`, removing the dependency on `gpg-agent`'s
  cache. Passphrases never appear in stdout, stderr, server log,
  or HTTP error responses. Operators who prefer the pre-0042
  behaviour can disable the store with
  `passphrase_store_enabled: false` in the bridge `config.yaml`.

### Improvements

- Publish `packages/gpg-bridge/openapi/gpg-bridge.v1.yaml` covering
  every route `gpg-bridge` serves (sign, verify, health, metrics)
  and gate it via `tests/test_openapi_spec.py` the same way the
  other two service specs are gated. Documents the `gpg-bridge`
  error surface in `design/error-codes.md` so spec drift is caught
  on every PR.
- Collapse `gpg-backend-cli-host` into `gpg-bridge` per the ADR
  0033 amendment of 2026-04-25. The bridge now invokes the host
  `gpg` binary directly, dropping the per-request backend
  subprocess hop (~50 ms / request saved). Migration: rename the
  `gpg_backend_command` config key to `gpg_command` in
  `~/.config/gpg-bridge/config.yaml`; the new default is `["gpg"]`
  rather than `["gpg-backend-cli-host"]`. The `gpg-backend-cli-host`
  PyPI/install path and the `task gpg-backend-host` Taskfile entry
  are removed; the HTTP API on `gpg-bridge` is unchanged.
- `setup-devcontainer-signing.sh` now runs an end-to-end smoke
  test before exiting 0. Verifies (1) `gpg-cli` is on PATH, (2)
  `git config user.signingkey` is set, (3) the bridge URL is
  reachable, and (4) a trial sign through gpg-cli succeeds —
  each failure mode prints a named cause and a remediation hint
  so operators don't discover the breakage at first `git commit`.
  Adds `--signing-key <FP>` to write `git config --local user.signingkey` and `--skip-smoke` to bypass the probes for
  constrained environments. New troubleshooting page at
  `docs/operations/gpg-bridge-host-setup.md`.

### Fixes

- Migration runner now propagates the underlying `OperationalError`
  when an up- or down-migration's SQL fails, instead of masking it
  behind a follow-up `cannot rollback - no transaction is active`
  error. Operators hitting a failed migration (e.g. running against
  a pre-#222 store where `token_families` already exists) now see
  the real SQL error in the traceback.
- `gpg-bridge` now fails fast on a wedged host gpg subprocess. The
  per-subprocess deadline drops from 35s to 10s and a new
  `signing_backend_unavailable` error code (HTTP 503) carries the
  structured signal across the bridge / `gpg-cli` trust boundary.
  `gpg-cli` translates it to a directed stderr message naming the
  most likely cause (`allow-loopback-pinentry` and a primed
  passphrase cache; see `docs/operations/gpg-bridge-host-setup.md`)
  instead of the previous misdirecting `bridge unavailable: gpg-bridge unreachable: timed out` after 30s.
- `merge-bot` no longer wedges on a fail-then-pass for the same
  required check on a single head SHA. The `Inspect required checks`
  step now groups `statusCheckRollup` entries by check name (falling
  back to `.context` for legacy commit statuses) and evaluates only
  the most-recent run per name, so a check that failed on the first
  workflow attempt and passed on a rerun reads as "currently passing"
  instead of carrying its historical FAILURE entry forward forever.
  The same dedupe applies to the pending selector — a stale
  `IN_PROGRESS` from a cancelled rerun no longer pins the bot in the
  wait-clean-exit path.
- `merge-bot` now refires automatically when CI goes green after the
  `automerge` label was already applied. The bot's old
  `check_suite: completed` trigger never delivered because GitHub's
  anti-recursion rule suppresses `check_suite` events for upstream
  workflows authenticated with the default `GITHUB_TOKEN` — which
  every CI workflow in this repo uses. The trigger has been swapped
  for `workflow_run: completed` with each PR-gating CI workflow
  listed by name; `workflow_run` events fire regardless of the
  upstream's authenticating token, so contributors no longer have
  to remove and re-add the `automerge` label as an undocumented
  kick once CI completes.
- The `Release PR` workflow now runs `mdformat CHANGELOG.md` after
  rendering the next release section, so the generated `CHANGELOG.md`
  matches the repo's mdformat conventions byte for byte. Without this
  pass, the release PR's `Check` job failed `scripts/format.sh --check` and the maintainer had to hand-reformat before merging —
  a regression introduced when the release flow moved from
  semantic-release (which had this pass via its prepare step) to the
  YAML-driven workflow in #321. The shared
  `./.github/actions/setup-toolchain` action provisions the
  manifest-pinned mdformat the new step depends on.
- `scripts/changelog/build_release.py` no longer produces a
  release-PR `==COMMIT_MSG==` body that fails the PR-body lint
  when changelog descriptions cite an ADR, issue, or spec by
  number. Greedy 72-char word wrap previously landed tokens like
  `0011.` (from `ADR 0011.`) or `1234)` (from `(issue 1234)`) at
  line start, which `validate-commit-msg-block.py`'s
  `numbered list item` rule rejects as an ordered-list item — see
  PR #355's broken `chore(release): 0.14.0` body. When a numeric
  token would otherwise overflow the current line, the renderer
  now moves the preceding token down with it so the wrap point
  sits between two ordinary tokens — preserving both the 72-char
  width rule and the no-numbered-list rule. Hyphen-joined
  identifiers like `CVE-2024-12345` still wrap normally.

## [0.13.1](https://github.com/aidanns/agent-auth/compare/v0.13.0...v0.13.1) (2026-04-25)

### Features

- **ci:** bot-mediated changelog authoring via PR markers ([#314](https://github.com/aidanns/agent-auth/issues/314))

- **ci:** CLI helper to scaffold changelog entries ([#322](https://github.com/aidanns/agent-auth/issues/322))

### Bug Fixes

- **store:** preserve original SQL error from failed up-migration ([#330](https://github.com/aidanns/agent-auth/issues/330))

## [0.13.0](https://github.com/aidanns/agent-auth/compare/v0.12.2...v0.13.0) (2026-04-25)

### Features

- **ci:** changelog YAML schema + PR-time lint ([#303](https://github.com/aidanns/agent-auth/issues/303))

- **ci:** merge bot extracts ==COMMIT_MSG== as squash body ([#310](https://github.com/aidanns/agent-auth/issues/310))

- **ci:** PR template + commit-msg block lint ([#302](https://github.com/aidanns/agent-auth/issues/302))

- **gpg-cli:** add task setup-devcontainer-signing for one-shot wiring ([#315](https://github.com/aidanns/agent-auth/issues/315))

## [0.12.2](https://github.com/aidanns/agent-auth/compare/v0.12.1...v0.12.2) (2026-04-25)

### Bug Fixes

- **test-support:** install SIGTERM handler in notifier so compose teardown exits cleanly ([#300](https://github.com/aidanns/agent-auth/issues/300))

## [0.12.1](https://github.com/aidanns/agent-auth/compare/v0.12.0...v0.12.1) (2026-04-25)

### Bug Fixes

- **test-harness:** drop docker compose -t override; gate compose_stop budget ([#292](https://github.com/aidanns/agent-auth/issues/292))

## [0.12.0](https://github.com/aidanns/agent-auth/compare/v0.11.0...v0.12.0) (2026-04-25)

### Features

- **coverage:** split --cov-fail-under into per-package floors ([#293](https://github.com/aidanns/agent-auth/issues/293))

## [0.11.0](https://github.com/aidanns/agent-auth/compare/v0.10.0...v0.11.0) (2026-04-25)

### ⚠ BREAKING CHANGES

- \*\* the root `install.sh` is deleted. Users must switch
  to the per-service installers (root README lists them). Every shipped
  console-script continues to work from its per-service package.

Closes #105.

## Test plan

- [x] `uv run pytest tests/ --ignore=tests/integration` — 509 passed,
  coverage 80.27 %.
- [x] `uv run ruff check`, `uv run mypy`, `uv run pyright` — clean
  across the new `packages/*/src` trees.
- [x] `scripts/verify-standards.sh`,
  `scripts/verify-integration-isolation.sh`,
  `scripts/verify-function-tests.sh`, `scripts/verify-design.sh`,
  `scripts/verify-token-cli-http-parity.sh`, `scripts/reuse-lint.sh` — all
  green.
- [ ] CI integration suite on all four `integration-*` jobs (requires
  Docker — not run locally).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

### Features

- **ci:** verify workspace dep graph against an explicit allowlist ([#285](https://github.com/aidanns/agent-auth/issues/285))

- **gpg-bridge:** implement gpg-cli / gpg-bridge packages (MVP) ([#254](https://github.com/aidanns/agent-auth/issues/254))

- **standards:** derive install.sh requirement from [project.scripts] ([#284](https://github.com/aidanns/agent-auth/issues/284))

- **taskfile:** per-package namespaces via Taskfile includes ([#279](https://github.com/aidanns/agent-auth/issues/279))

- **things-bridge:** restrict subprocess env to minimal allowlist ([#277](https://github.com/aidanns/agent-auth/issues/277))

### Code Refactoring

- split services into a uv workspace of per-service subprojects ([#257](https://github.com/aidanns/agent-auth/issues/257))

## [0.10.0](https://github.com/aidanns/agent-auth/compare/v0.9.1...v0.10.0) (2026-04-23)

### Features

- **design:** wire generator + CI drift gate for design/\*.yaml renders ([#256](https://github.com/aidanns/agent-auth/issues/256))

## [0.9.1](https://github.com/aidanns/agent-auth/compare/v0.9.0...v0.9.1) (2026-04-23)

### Bug Fixes

- **verify-standards:** tighten tool-name regexes against hyphen word boundaries ([#247](https://github.com/aidanns/agent-auth/issues/247))

## [0.9.0](https://github.com/aidanns/agent-auth/compare/v0.8.0...v0.9.0) (2026-04-23)

### Features

- **vscode:** commit .vscode workspace ([#245](https://github.com/aidanns/agent-auth/issues/245))

## [0.8.0](https://github.com/aidanns/agent-auth/compare/v0.7.1...v0.8.0) (2026-04-23)

### Features

- **benchmark:** pytest-benchmark suite with scheduled CI ([#241](https://github.com/aidanns/agent-auth/issues/241))

## [0.7.1](https://github.com/aidanns/agent-auth/compare/v0.7.0...v0.7.1) (2026-04-23)

### Bug Fixes

- **things-bridge:** bound subprocess stderr capture ([#239](https://github.com/aidanns/agent-auth/issues/239))

## [0.7.0](https://github.com/aidanns/agent-auth/compare/v0.6.0...v0.7.0) (2026-04-23)

### ⚠ BREAKING CHANGES

- **audit:** HMAC-chained audit log with verify-audit CLI (#103) (#230)

### Features

- **audit:** HMAC-chained audit log with verify-audit CLI ([#103](https://github.com/aidanns/agent-auth/issues/103)) ([#230](https://github.com/aidanns/agent-auth/issues/230))

## [0.6.0](https://github.com/aidanns/agent-auth/compare/v0.5.0...v0.6.0) (2026-04-23)

### ⚠ BREAKING CHANGES

- **notifier:** migrate notification plugin to out-of-process HTTP (#6) (#227)

### Features

- **notifier:** migrate notification plugin to out-of-process HTTP ([#6](https://github.com/aidanns/agent-auth/issues/6)) ([#227](https://github.com/aidanns/agent-auth/issues/227))

## [0.5.0](https://github.com/aidanns/agent-auth/compare/v0.4.0...v0.5.0) (2026-04-23)

### Features

- **rate-limit:** in-memory per-token-family rate limiting ([#102](https://github.com/aidanns/agent-auth/issues/102)) ([#226](https://github.com/aidanns/agent-auth/issues/226))

## [0.4.0](https://github.com/aidanns/agent-auth/compare/v0.3.0...v0.4.0) (2026-04-23)

### Features

- **store:** numbered-SQL migration runner for the token store ([#29](https://github.com/aidanns/agent-auth/issues/29)) ([#222](https://github.com/aidanns/agent-auth/issues/222))

## [0.3.0](https://github.com/aidanns/agent-auth/compare/v0.2.2...v0.3.0) (2026-04-23)

### Features

- **keys:** detect keyring wipe against a non-empty token store ([#31](https://github.com/aidanns/agent-auth/issues/31)) ([#202](https://github.com/aidanns/agent-auth/issues/202))

## [0.2.2](https://github.com/aidanns/agent-auth/compare/v0.2.1...v0.2.2) (2026-04-23)

### Bug Fixes

- **release:** drop commit-hash and closes-issue links from changelog ([#220](https://github.com/aidanns/agent-auth/issues/220))

## [0.2.1](https://github.com/aidanns/agent-auth/compare/v0.2.0...v0.2.1) (2026-04-23)

### Bug Fixes

- **release:** run task format on semantic-release output ([#219](https://github.com/aidanns/agent-auth/issues/219)) ([f4ec2e1](https://github.com/aidanns/agent-auth/commit/f4ec2e1394f6bfcbe83dbd714dc719255325ecb0))

## [0.2.0](https://github.com/aidanns/agent-auth/compare/v0.1.0...v0.2.0) (2026-04-23)

### Features

- **api:** publish OpenAPI 3.1 specs for agent-auth and things-bridge ([#176](https://github.com/aidanns/agent-auth/issues/176)) ([b782b04](https://github.com/aidanns/agent-auth/commit/b782b047e377243a4bdb32ee3d95f8bdc664edbb)), closes [#28](https://github.com/aidanns/agent-auth/issues/28) [#94](https://github.com/aidanns/agent-auth/issues/94)
- **audit:** add schema_version field and stability policy ([#167](https://github.com/aidanns/agent-auth/issues/167)) ([eecc9d6](https://github.com/aidanns/agent-auth/commit/eecc9d62760f81f4b7cafc2b55fb0cd2567e2e54)), closes [#20](https://github.com/aidanns/agent-auth/issues/20)
- **audit:** attach OTel service.name/service.version to every audit entry ([#100](https://github.com/aidanns/agent-auth/issues/100)) ([#200](https://github.com/aidanns/agent-auth/issues/200)) ([ad72be7](https://github.com/aidanns/agent-auth/commit/ad72be7f54c1a4108df0cf008e710604a7aa763d))
- expose token management operations via HTTP API ([#97](https://github.com/aidanns/agent-auth/issues/97)) ([20b73a9](https://github.com/aidanns/agent-auth/commit/20b73a97fbb8383e449f359b8d6948dd2c15bd5a))
- **metrics:** /agent-auth/metrics and /things-bridge/metrics Prometheus endpoints ([#26](https://github.com/aidanns/agent-auth/issues/26)) ([#186](https://github.com/aidanns/agent-auth/issues/186)) ([6d266fb](https://github.com/aidanns/agent-auth/commit/6d266fbbddfd78c94ebb708d28e39f2c72bed969))
- migrate config to YAML, version APIs at /v1/, and add error/audit contract tests ([#126](https://github.com/aidanns/agent-auth/issues/126)) ([4c61c2a](https://github.com/aidanns/agent-auth/commit/4c61c2ae10f553ed115fd2bddbd3d2bfc483abe4)), closes [#24](https://github.com/aidanns/agent-auth/issues/24) [#27](https://github.com/aidanns/agent-auth/issues/27) [#28](https://github.com/aidanns/agent-auth/issues/28) [#20](https://github.com/aidanns/agent-auth/issues/20)
- **release:** attest SLSA Build L3 provenance on every release ([#109](https://github.com/aidanns/agent-auth/issues/109)) ([#180](https://github.com/aidanns/agent-auth/issues/180)) ([7eb1efd](https://github.com/aidanns/agent-auth/commit/7eb1efd3c35f86dcb8e6e69259ac08d3c710040c))
- **release:** migrate autorelease driver to semantic-release ([#204](https://github.com/aidanns/agent-auth/issues/204)) ([857958c](https://github.com/aidanns/agent-auth/commit/857958c718d5811d131052e0352e7971ff100a92))
- **release:** signed SBOMs, autorelease via Release Please, REUSE compliance ([#132](https://github.com/aidanns/agent-auth/issues/132)) ([38e257b](https://github.com/aidanns/agent-auth/commit/38e257b28bceba20c0110dddf01f020785f53974)), closes [SECURITY.md#supply-chain-artifacts](https://github.com/aidanns/SECURITY.md/issues/supply-chain-artifacts) [#97](https://github.com/aidanns/agent-auth/issues/97) [110/#111](https://github.com/110/agent-auth/issues/111) [#127](https://github.com/aidanns/agent-auth/issues/127) [#128](https://github.com/aidanns/agent-auth/issues/128) [#109](https://github.com/aidanns/agent-auth/issues/109) [#93](https://github.com/aidanns/agent-auth/issues/93) [#18](https://github.com/aidanns/agent-auth/issues/18) [#106](https://github.com/aidanns/agent-auth/issues/106) [#110](https://github.com/aidanns/agent-auth/issues/110) [#111](https://github.com/aidanns/agent-auth/issues/111)
- **security:** adopt OWASP ASVS v5 as application security standard ([#177](https://github.com/aidanns/agent-auth/issues/177)) ([de46858](https://github.com/aidanns/agent-auth/commit/de4685815f4bdca146c0f3049476c537a4374c62))
- **server:** graceful SIGTERM / SIGINT shutdown for agent-auth and things-bridge ([#154](https://github.com/aidanns/agent-auth/issues/154)) ([#162](https://github.com/aidanns/agent-auth/issues/162)) ([600a901](https://github.com/aidanns/agent-auth/commit/600a9014a4a5989115cc24f157e137a524a73857)), closes [#152](https://github.com/aidanns/agent-auth/issues/152) [#152](https://github.com/aidanns/agent-auth/issues/152)
- **things-bridge:** deepen /health to verify things-client binary is resolvable ([#91](https://github.com/aidanns/agent-auth/issues/91)) ([#198](https://github.com/aidanns/agent-auth/issues/198)) ([4f93930](https://github.com/aidanns/agent-auth/commit/4f93930a833d916ca89156f9cdbee64c25356552))
- **tls:** optional in-process TLS listener on both HTTP servers ([#101](https://github.com/aidanns/agent-auth/issues/101)) ([#201](https://github.com/aidanns/agent-auth/issues/201)) ([076fa6d](https://github.com/aidanns/agent-auth/commit/076fa6dd35f8bb3ed61881323aca36cff2c52fd3))
- **typecheck:** ratchet agent_auth/\* to strict mypy + pyright ([#164](https://github.com/aidanns/agent-auth/issues/164)) ([35a95e4](https://github.com/aidanns/agent-auth/commit/35a95e488a13177e11147471aaca39725fc4c25d)), closes [#145](https://github.com/aidanns/agent-auth/issues/145)
- **typecheck:** ratchet tests/ + tests_support/ under strict mypy + pyright ([#171](https://github.com/aidanns/agent-auth/issues/171)) ([f51a9f6](https://github.com/aidanns/agent-auth/commit/f51a9f6843aa73b831f1c8f4e56be46f84a364d2)), closes [#148](https://github.com/aidanns/agent-auth/issues/148)
- **typecheck:** ratchet things_bridge/\* to strict mypy + pyright ([#156](https://github.com/aidanns/agent-auth/issues/156)) ([5f090a7](https://github.com/aidanns/agent-auth/commit/5f090a77fc3913e1cac489d76cbc0a4e5717b648)), closes [#146](https://github.com/aidanns/agent-auth/issues/146) [#147](https://github.com/aidanns/agent-auth/issues/147)
- **typecheck:** ratchet things_cli/\* + things_client_common/\* + things_models/\* to strict ([#161](https://github.com/aidanns/agent-auth/issues/161)) ([b0f76f9](https://github.com/aidanns/agent-auth/commit/b0f76f9a86c8e3955625ca342fc426168022d17b)), closes [#147](https://github.com/aidanns/agent-auth/issues/147)
- **verify-standards:** gate graceful-shutdown standard ([#32](https://github.com/aidanns/agent-auth/issues/32)) ([#188](https://github.com/aidanns/agent-auth/issues/188)) ([563c297](https://github.com/aidanns/agent-auth/commit/563c29770706aeaef57637d4352d6f78fbc89140)), closes [#154](https://github.com/aidanns/agent-auth/issues/154)
- **verify-standards:** gate health-endpoint standard ([#25](https://github.com/aidanns/agent-auth/issues/25)) ([#179](https://github.com/aidanns/agent-auth/issues/179)) ([f01491f](https://github.com/aidanns/agent-auth/commit/f01491f943d6e1f68d1d278b177ec90497e20ed4))

### Bug Fixes

- move token management routes under /v1/ namespace ([#137](https://github.com/aidanns/agent-auth/issues/137)) ([#142](https://github.com/aidanns/agent-auth/issues/142)) ([0ead162](https://github.com/aidanns/agent-auth/commit/0ead162e6a037b767de8824256da23dd6411505e)), closes [#126](https://github.com/aidanns/agent-auth/issues/126) [#97](https://github.com/aidanns/agent-auth/issues/97)
- **release:** repair github plugin options and anchor CHANGELOG title ([#213](https://github.com/aidanns/agent-auth/issues/213)) ([7ffd296](https://github.com/aidanns/agent-auth/commit/7ffd296a0a030200f52b685784a7ce955ffad4b8))
- **server:** drain oversize request bodies before rejecting ([#144](https://github.com/aidanns/agent-auth/issues/144)) ([#199](https://github.com/aidanns/agent-auth/issues/199)) ([6c73ec1](https://github.com/aidanns/agent-auth/commit/6c73ec1e6b09c10c4ee37456155e4fab12777a94)), closes [#139](https://github.com/aidanns/agent-auth/issues/139)

## [0.1.0] - 2026-04-19

### Added

- **agent-auth server and CLI** — HTTP validation server (`agent-auth serve`) with full
  token lifecycle management: create, list, modify, revoke, rotate. HMAC-SHA256 signed
  tokens with AES-256-GCM field encryption and signing key held in the system keyring.
  Three-tier scope model (allow / prompt / deny), JIT approval via pluggable notification
  plugin, token families with refresh-token reuse detection, and audit logging.
- **things-bridge** — HTTP bridge server (`things-bridge serve`) that delegates token
  validation to agent-auth and exposes read-only Things 3 endpoints under
  `/things-bridge/`. The bridge contains no Things 3 logic; it shells out to a configured
  Things-client CLI per request.
- **things-client-cli-applescript** — Standalone read-only CLI that talks to Things 3 via
  `osascript` on macOS. Emits JSON on stdout; usable independently of things-bridge for
  local debugging.
- **things-cli** — Thin HTTP client for things-bridge that auto-refreshes/reissues tokens
  via agent-auth. Stores credentials in the system keyring (falls back to a
  `~/.config/things-cli/credentials.yaml` file when no keyring backend is available).

### Changed

- **`task release` auto-derives the next version.** Run `task release` with no
  argument and the script walks Conventional Commits since the last `v*` tag to
  pick a major / minor / patch bump (BREAKING → major, `feat:` → minor,
  `fix:` → patch). Pass `task release -- X.Y.Z` to override. While the current
  tag is in the `0.x` range the API is not considered stable (SemVer 2.0.0 §4),
  so a detected major bump is demoted to a minor bump; pass an explicit
  `task release -- 1.0.0` to graduate.
- **`task release -- -y` skips the confirmation prompt** so the release can
  run hands-off (e.g. `task release -- -y 1.2.3`). The signed-tag step still
  needs your signing key; see `CONTRIBUTING.md` § "Non-interactive signing
  for `task release`" for gpg-agent / ssh-agent pre-warm instructions.

[0.1.0]: https://github.com/aidanns/agent-auth/releases/tag/v0.1.0
