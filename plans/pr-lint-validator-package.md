<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# pr-lint-validator — package extraction (issue #446)

Closes #446. Part of the parent #440 plan to migrate the PR-lint
checks off ad-hoc `scripts/validate-*.py` invocations and onto a
versioned, releasable artifact that downstream CI can consume by
tag.

This issue stops at "the validator package exists in the workspace
and ships as a release asset". The cutover that switches
`.github/workflows/pr-lint.yml` to consume the released artifact is
tracked separately in #477; the larger CI restructure that moves
the jobs into `check-pull-request.yml` is tracked in #463. Both
are explicitly out of scope here.

## Context

Today, `pr-lint.yml`'s validator jobs invoke
`scripts/validate-pr-title.py` and `scripts/validate-commit-msg-block.py`
directly out of the source tree at the PR's HEAD. Two structural
gaps with that arrangement:

1. **The check-runs-on-the-PR-being-checked.** A PR that introduces
   a regression in the validator can also self-approve under the
   regressed validator. ADR 0037 / #401 / #402 widened the
   validator's logic to the point where this is no longer
   theoretical — the matrix and two-tier rules carry enough
   complexity that a misedit could pass `--self-test` and still
   wave through invalid titles.
2. **Downstream consumers can't run the same checks.** The
   `aidanns/dotfiles` and `aidanns/systems-engineering` repos have
   started copy-pasting the validator scripts. There is no pinned,
   verifiable artifact they can fetch and execute.

The fix is to extract the validators into a workspace package
(`packages/pr-lint-validator/`) that ships as a per-package wheel +
sdist on every release, alongside the existing services. The
release-bot's per-package fan-out already attaches one wheel + one
sdist + sha256 sidecar + SBOM + cosign bundle per workspace member
(ADR 0044), so adding a package automatically attaches the artifact
to the next tagged release with no `.github/workflows/` change.

## Proposal

### Package layout

```
packages/pr-lint-validator/
├── pyproject.toml                 # name = "pr-lint-validator"
├── README.md
├── Taskfile.yml                   # test / lint / typecheck / format
├── src/pr_lint_validator/
│   ├── __init__.py
│   ├── cli.py                     # argparse subparsers, entry point
│   ├── commit_taxonomy.py         # bundled snapshot (see below)
│   ├── title.py                   # was scripts/validate-pr-title.py
│   └── commit_msg.py              # was scripts/validate-commit-msg-block.py
└── tests/
    ├── conftest.py
    ├── test_title.py              # title rule coverage
    ├── test_commit_msg.py         # commit-msg rule coverage
    ├── test_cli.py                # subcommand argv coverage
    └── test_commit_taxonomy_in_sync.py  # bundled vs. canonical
```

The CLI is exposed via `[project.scripts] pr-lint-validator = "pr_lint_validator.cli:main"`,
yielding subcommands:

- `pr-lint-validator title` — wraps `validate-pr-title.py`'s public
  surface; takes `--title`, `--changed-files-from`, `--pr-number`,
  `--self-test`.
- `pr-lint-validator commit-msg` — wraps
  `validate-commit-msg-block.py`'s public surface; takes a body
  file path, `--title`, `--self-test`.

Subcommand names match the existing script suffixes minus the
`validate-` / `-block` chrome so the cutover in #477 reads naturally.
The third `predict-release-impact` subcommand is **deferred** (see
"Out of scope" below).

### Source migration — copy, not move

The two `scripts/validate-*.py` files stay where they are. The new
package gets a copy of each module's public surface (the
`validate(...)` / `extract_block(...)` / `extract_commit_msg_block(...)`
functions, the regex constants, the `*ValidationError` exception
types). The CLI entry points are rewritten to be argparse
subparsers under one root parser instead of two standalone scripts.

This is the pattern the issue body asks for ("Leave
`scripts/validate-*.py` ... untouched — the cutover happens in
#477"). Two copies coexist for the duration of #477; once that PR
lands and `pr-lint.yml` consumes the released artifact, the
`scripts/` copies get deleted. A test in this PR
(`test_commit_taxonomy_in_sync.py`) compares the bundled
`commit_taxonomy.py`'s static constants (`ALLOWED_TYPES`,
`AREA_SCOPES`, `INTERNAL_ONLY_SCOPES`, `RELEASE_BUMPING_TYPES`,
`ReleaseImpact`) with the canonical
`scripts/lint/commit_taxonomy.py` so the duplication window cannot
drift on the values the validators read. The dynamic
`PACKAGE_SCOPES` discovery is intentionally divergent (see below).

### Bundled commit_taxonomy snapshot

`scripts/lint/commit_taxonomy.py` is the single source of truth for
`ALLOWED_TYPES`, `AREA_SCOPES`, `INTERNAL_ONLY_SCOPES`,
`PACKAGE_SCOPES`. The validator currently imports it via
`importlib.util.spec_from_file_location` because `scripts/` isn't on
`sys.path`. For the package version, the file is **copied** into
`src/pr_lint_validator/commit_taxonomy.py` so the wheel is
self-contained.

Drift protection: `tests/test_commit_taxonomy_in_sync.py` reads both
files and asserts they are identical. The test runs in the
package's pytest suite and, by extension, the workspace `task test`
ratchet. A future contributor who edits the canonical file without
syncing the bundled copy fails CI on the next PR.

`PACKAGE_SCOPES` is *dynamically discovered* in the canonical file
(`_discover_package_scopes()` reads `packages/*/` relative to
`__file__`). The bundled copy can't use that anchor — when the wheel
runs from `site-packages/`, `__file__` resolves outside the consumer
repo. The bundled module instead exposes
`discover_package_scopes(repo_root: Path | None = None)`, which
defaults to walking `packages/` relative to the current working
directory (matching how GitHub Actions invokes the validator inside
`$GITHUB_WORKSPACE`) and accepts a `repo_root` override. The CLI
threads `--repo-root` through so a non-standard layout can be
specified explicitly. The validator's `validate(...)` signature also
takes a `package_scopes=` override so tests can drive the two-tier
scope rule against a representative workspace without writing a
fake `packages/` tree.

### Build artifact

The release path attaches one wheel + one sdist + sha256 sidecar +
SBOM + cosign bundle per workspace member, all driven by the
member-discovery loop in `release-bot.yml`'s `publish-assets` job
(`uv build --all-packages`) and `verify-assets`'s
`find packages -mindepth 2 -maxdepth 2 -name pyproject.toml` count.
Adding `packages/pr-lint-validator/` with a `pyproject.toml`
automatically increments the expected member count and the
package's wheel + sdist appear on the next tag's release.

This means **no `.github/workflows/` change is needed for the
artifact to ship**. The dryrun gate (`release-dryrun.yml`) and the
asset verifier (`verify-assets`) both auto-tighten on the new
member count.

### CLI consumption pattern (for #477)

Documented in `packages/pr-lint-validator/README.md` § Usage:

```bash
# In #477's pr-lint.yml job, fetch by tag and run.
gh release download "${TAG}" --pattern 'pr_lint_validator-*-py3-none-any.whl'
gh release download "${TAG}" --pattern 'pr_lint_validator-*-py3-none-any.whl.sha256'
sha256sum -c pr_lint_validator-*-py3-none-any.whl.sha256
pip install --user pr_lint_validator-*-py3-none-any.whl
pr-lint-validator title --title "${PR_TITLE}" --pr-number "${PR_NUMBER}" \
  --changed-files-from changed-files.txt
```

The wheel is `py3-none-any` (pure Python), so a single asset works
on every runner. Tag pinning is the consumer's choice; the contract
this PR ships is "the wheel + sha256 sidecar + cosign bundle exist
on every release tag from this point forward".

The pyz zipapp form proposed as an alternative in the issue body
(`pr-lint-validator.pyz` + sha256 sidecar) is **not** built here.
Wheel + sdist already give a self-contained pure-Python install
path that pipx and `pip install --user` cover; adding a pyz
duplicates the form and would need a `.github/` change to attach
the new file to the release. The wheel form satisfies the issue's
"the artifact exists on a GitHub Release" contract verbatim, and
#477 can refine to a pyz later if a runner-side `pip install` step
turns out to be too slow.

## Out of scope

- **`predict-release-impact` subcommand.** The script lives at
  `scripts/changelog/predict_release_impact.py` and depends on
  `build_release` / `version_logic` / `commit_taxonomy` — three
  modules tightly coupled to the changelog-bot tooling under
  `scripts/changelog/`. Moving it would unwind that package and
  expand this PR well past "extract the title + commit-msg
  validators". Tracked as a follow-up; documented in the PR body
  and the package README.

- **Touching `pr-lint.yml`.** The cutover is #477's job.

- **Deleting `scripts/validate-*.py`.** Same — happens at the end
  of #477.

- **Building a `.pyz` zipapp.** Wheel + sdist cover the contract;
  pyz would require attaching a new asset shape to the release,
  which is a `.github/` change.

## Test plan

Static checks:

- [ ] `task pr-lint-validator:test` passes (the new package's
  pytest suite).
- [ ] `task pr-lint-validator:lint` and
  `task pr-lint-validator:typecheck` are green.
- [ ] `task test` (workspace) includes the new package and stays
  green.
- [ ] `scripts/build-release-artifacts.sh --out /tmp/dist-test`
  produces a `pr_lint_validator-*.whl` and a
  `pr_lint_validator-*.tar.gz`.
- [ ] `release-dryrun.yml`'s wheel/sdist count gate accepts the
  bumped expected count (the `find packages -mindepth 2 ...`
  counter does this automatically).
- [ ] `pr-lint-validator title --self-test` exits 0 and reports the
  same case count as `python3 scripts/validate-pr-title.py --self-test`.
- [ ] `pr-lint-validator commit-msg --self-test` exits 0 and
  reports the same case count as
  `python3 scripts/validate-commit-msg-block.py --self-test`.
- [ ] `tests/test_commit_taxonomy_in_sync.py` asserts the bundled
  copy of `commit_taxonomy.py` matches the canonical file
  byte-for-byte.

Live smoke (post-merge, only verifiable on the next release):

- [ ] The next `release/X.Y.Z` PR's `release-dryrun.yml`
  `Assert expected artefact set` step passes with the bumped
  member count.
- [ ] After `tag-and-release` fires, `gh release view vX.Y.Z` lists
  `pr_lint_validator-X.Y.Z-py3-none-any.whl`,
  `pr_lint_validator-X.Y.Z-py3-none-any.whl.sha256`,
  `pr_lint_validator-X.Y.Z.tar.gz`,
  `pr_lint_validator-X.Y.Z.tar.gz.sha256`, plus matching SBOMs
  and cosign bundles.

## Design decisions

### Why copy the validator modules instead of importing them?

The package needs to ship as a self-contained wheel. Importing the
existing `scripts/validate-*.py` files via path-spec would couple
the wheel to a layout that doesn't exist outside the agent-auth
repo. A copy is structurally simpler and the duplication window is
short — #477 deletes the originals.

### Why bundle `commit_taxonomy.py` instead of importing it?

Same reason: the wheel must run without the consumer repo's
`scripts/` directory on `sys.path`. The taxonomy is small (~200
lines of pure Python) and the drift protection (the in-sync test)
is structurally cheap.

### Why argparse subparsers, not separate console scripts?

CONTRIBUTING.md and `CLAUDE.md` both standardise on argparse
subparsers for the project's CLIs (`agent-auth`, `things-cli`,
`gpg-bridge`). One entry point keeps the wheel's
`[project.scripts]` table small and lets the validator surface
extend (`pr-lint-validator release-impact ...`) without shipping a
new console script per subcommand.

### Why no pyz / zipapp?

The wheel form already gives a pure-Python install via
`pip install --user <wheel>` or `pipx run --from <wheel>`. A pyz
adds a second asset shape that needs its own `.github/` upload step
and its own checksum sidecar — a `.github/` change is a public-
break blocker per the project's PR rules. The wheel + sdist + the
existing per-artefact sha256 / SBOM / cosign coverage are enough
for #477 to consume by tag. If a runner-side `pip install` proves
too slow, the pyz form can be added later as a focused follow-up
that owns the workflow change.

### Why is `predict-release-impact` deferred?

`scripts/changelog/predict_release_impact.py` imports
`build_release` and `version_logic` from the same directory, which
in turn import `commit_taxonomy` and `wordlist`. Pulling
`predict_release_impact` into the package would cascade into
relocating four more modules and the entire
`scripts/changelog/tests/` tree. That is a larger refactor than
this issue's scope and overlaps with #298's changelog-bot work.
A focused follow-up under #440 can do it once the dust on
`scripts/changelog/` settles.

## Design and verification

- **Verify implementation against design doc** — the only design
  doc this PR touches is the per-package release-asset layout in
  ADR 0044. The new package automatically inherits that layout;
  no ADR amendment is needed.
- **Threat model** — N/A (no network surface, no
  authentication / authorisation surface).
- **PIR** — N/A (not remediating a confirmed vulnerability).
- **ADR** — no new ADR. The package extraction is incremental on
  ADR 0037 (PR-title prefix allowlist) and ADR 0044 (per-package
  release assets) — both decisions stand unchanged.
- **Cybersecurity standard compliance** — N/A (no security
  surface).
- **QM / SIL compliance** — N/A.

## Post-implementation standards review

- **`coding-standards.md`** — verb names on every function in
  the new package (`validate(...)`, `check_*(...)`,
  `extract_block(...)`); no raw tuples for structured fields
  (regex captures stay in named groups); no implicit units in
  parameter names.
- **`service-design.md`** — N/A (CLI / library, not a service).
- **`release-and-hygiene.md`** — hand-author
  `changelog/@unreleased/pr-<N>-pr-lint-validator-package.yml`
  with `type: feature` since the package is a new user-visible
  surface; DCO sign-off on every commit.
- **`testing-standards.md`** — tests cover the package's public
  CLI surface (subcommand argv -> exit code + stdout/stderr).
  The `test_commit_taxonomy_in_sync.py` test is a regression
  guard whose impact is documented in its docstring.
- **`tooling-and-ci.md`** — `task pr-lint-validator:test` /
  `lint` / `typecheck` / `format` / `check` mirror every other
  package's namespace tasks; the workspace-level `task test` /
  `task lint` etc. fan out into the new namespace automatically
  via `Taskfile.yml`'s include block.
