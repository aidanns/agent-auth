<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: pr-lint.yml consumes the released pr-lint-validator wheel

Closes #477. Follows on from #446 (PR #489) which extracted the
PR-title and `==COMMIT_MSG==` block validators into a new
`pr-lint-validator` workspace package shipped on every release as a
wheel + sha256 sidecar.

## Context

Today the four `scripts/validate-*.py` jobs in
`.github/workflows/pr-lint.yml` invoke in-tree Python scripts that
duplicate the validator logic now also living in
`packages/pr-lint-validator/`. The duplication is brittle: a fix in
one half can drift past the other. The released wheel from #446 makes
the package the canonical implementation; this PR cuts pr-lint.yml
over to consume it.

## Scope reconciliation

The issue body lists four target jobs but is older than #489's actual
implementation (the orchestrator's prompt explicitly flags this as a
stale-paths case):

| Issue's name                | pr-lint.yml job          | Wheel ships?                                                | Action                          |
| --------------------------- | ------------------------ | ----------------------------------------------------------- | ------------------------------- |
| `title-prefix`              | `pr-title`               | n/a (uses `amannn/action-semantic-pull-request`)            | leave untouched                 |
| `title-prose-style`         | `pr-title-style`         | yes (`pr-lint-validator title`)                             | swap                            |
| `commit-message`            | `pr-body-commit-msg`     | yes (`pr-lint-validator commit-msg`)                        | swap                            |
| `release-impact-prediction` | `release-impact-comment` | NO (cli.py reserves `release-impact` "for a future change") | leave untouched, file follow-up |

The wheel deferred packaging the changelog tooling (per #489's PR
body, packaging `predict_release_impact.py` is out of scope for that
issue). So this PR can only cut over the two scripts the wheel does
ship: `validate-pr-title.py` and `validate-commit-msg-block.py`. A
follow-up issue tracks packaging the release-impact predictor and
cutting `release-impact-comment` over to it.

The self-test jobs (`pr-title-self-test`, `pr-body-warning-self-test`,
`validator-self-test`) all also call `scripts/validate-*.py --self-test`. Since the wheel `--self-test` modes carry the same
fixture/case set, these three jobs swap too — keeping the cutover
complete for the title + commit-msg surface.

## Rewrite shape

The four jobs that consume the swapped scripts (`pr-title-style`,
`pr-body-commit-msg`, `pr-title-self-test`, `pr-body-warning-self-test`,
`validator-self-test`) each need a fetch + verify + install +
invoke step shape:

1. **Fetch** the wheel + sha256 sidecar:
   `gh release download v0.17.1 --pattern 'pr_lint_validator-0.17.1-py3-none-any.whl*' --repo ${GITHUB_REPOSITORY} --dir <dir>`.
2. **Verify** the checksum:
   `cd <dir> && sha256sum -c pr_lint_validator-0.17.1-py3-none-any.whl.sha256`.
   Fail loud on mismatch.
3. **Install** into a per-job venv:
   `python -m venv <venv> && <venv>/bin/pip install --no-cache-dir <dir>/pr_lint_validator-0.17.1-py3-none-any.whl`.
4. **Invoke** the appropriate subcommand on the existing env vars:
   `<venv>/bin/pr-lint-validator title --pr-number ... --changed-files-from ... -- "${TITLE}"`
   etc.

To DRY the boilerplate, extract a composite action at
`.github/actions/install-pr-lint-validator/action.yml` with one
input (`version`, default `0.17.1`) and one output (the venv path
the consuming job runs `pr-lint-validator` from). The composite
encapsulates fetch + verify + install. Each consuming job then
collapses to:

```yaml
- uses: ./.github/actions/install-pr-lint-validator
- run: pr-lint-validator title --title "${TITLE}" ...
```

This keeps the 4-job rewrite minimal-diff. Required: the composite
must be a **local** composite (`uses: ./...`); third-party composites
would need SHA pinning per `.claude/instructions/tooling-and-ci.md`.

## Tag pin strategy

Hardcode `v0.17.1` as the default `version` input on the composite.
v0.17.0 was the first release that shipped
`pr_lint_validator-*.whl` but it was missing rule 8
(`check_no_leading_subject_line`); v0.17.1 (PR #500 backport, then
the release-PR #501 cut) is the first release whose wheel matches
the in-tree validator surface end to end. Document the bump
procedure in the composite's `action.yml` description. Renovate
doesn't auto-track GitHub Release tags by default; the simplest
approach is "manual bump on release-bot's publish PR". File a
follow-up issue to consider a Renovate custom manager or
release-bot post-publish hook for automation.

## Decision: delete `scripts/validate-pr-title.py`; KEEP `scripts/validate-commit-msg-block.py` (this PR)

`validate-pr-title.py` has no other in-tree callers — `grep` confirms
it's only imported / invoked from the swapped pr-lint.yml jobs and
the (now-updated) CONTRIBUTING.md doc references. Delete it.

`validate-commit-msg-block.py`, in contrast, exports `extract_block`,
`extract_commit_msg_block`, `ValidationError`, and `BlockMarkerError`
that the merge-bot's `scripts/extract-commit-msg-block.py` and the
changelog-bot's `scripts/changelog/bot.py` both import via
`importlib.util.spec_from_file_location`. Deleting the validator
script outright would cascade into rewriting both bots to install
the wheel and import from `pr_lint_validator.commit_msg`, expanding
this PR's scope into two unrelated bot workflows. The clean follow-up
is to either:

1. Switch the bots to consume the wheel like pr-lint.yml does
   (file follow-up issue), then delete the script in that PR; or
2. Reduce `validate-commit-msg-block.py` to a thin compatibility
   shim that re-exports from `pr_lint_validator.commit_msg` (per
   the issue body's "thin wrapper" option) once the wheel is
   installed at the bot-workflow level.

Either path is its own piece of work. For #477, the cleanest call is
to leave `validate-commit-msg-block.py` in tree so the bots keep
working unchanged. The pr-lint.yml jobs that USED to invoke the
script are cut over to the wheel (the issue's actual goal); the
script itself stays as a parser-import surface for the other bots,
not as a CI validator.

`scripts/changelog/predict_release_impact.py` stays for the same
reason as before — the wheel does not yet replace it (see scope
table above). `release-impact-comment` and
`predict-release-impact-self-test` jobs are unchanged.

## Required-check identifier stability

The job names in pr-lint.yml become the GitHub branch-protection
required-check identifiers. Per the issue body, the names MUST stay
stable so branch protection doesn't need an update. The five jobs
this PR rewrites keep their existing `name:` strings verbatim:

- `PR title (subject style)`
- `PR body (==COMMIT_MSG== block)`
- `PR title validator self-test`
- `PR body warning-rule validator self-test`
- `Validator self-test`

The job `id:` names (the YAML keys) also stay the same.

## Documentation updates

CONTRIBUTING.md references `scripts/validate-pr-title.py` and
`scripts/validate-commit-msg-block.py` in the "Writing PRs" and
"Writing release-worthy commits" sections (lines 317, 367, 840, 846,
945, 961, 969 today). Replace those with the wheel-installed
`pr-lint-validator title` / `pr-lint-validator commit-msg` invocation
shape so contributors who copy the doc-suggested local-test command
still get a working invocation.

## Test plan

- [x] Local: `pip install` the wheel from a freshly-built `dist/` and
  invoke `pr-lint-validator title --self-test` /
  `pr-lint-validator commit-msg --self-test`. Confirm both return 0
  and exercise their full case sets.
- [x] Local: re-run the same `--self-test` against the published
  v0.17.1 wheel (proves the released artefact, not just the in-tree
  source, exercises the full self-test surface, including rule 8
  `check_no_leading_subject_line` which the v0.17.0 wheel was
  missing).
- [x] Local: confirm the v0.17.1 wheel CLI rejects
  `.github/workflows/tests/pr-lint-fixtures/invalid-leading-subject-line.md`
  with non-zero exit (rule 8 backport from #500 reaches the
  released wheel surface).
- [ ] CI: every PR body fixture under
  `.github/workflows/tests/pr-lint-fixtures/*.md` continues to fail
  (`invalid-*`) or pass (`valid-*`) under the wheel's `commit-msg`
  invocation in the `Validator self-test` job.
- [ ] CI: `pr-title-self-test` exits 0 against the wheel's
  `title --self-test`.
- [ ] CI: `pr-body-warning-self-test` exits 0 against the wheel's
  `commit-msg --self-test`.
- [ ] CI: This PR's own `pr-title-style` and `pr-body-commit-msg`
  jobs both pass against the wheel — proves the live CLI invocation
  path (not just the self-test path) end-to-end.
- [ ] CI: every other pr-lint.yml job that was untouched
  (`pr-title`, `release-impact-comment`, `predict-release-impact-self-test`,
  `pr-title-types-self-test`) still runs green.

## Out of scope

- Packaging `scripts/changelog/predict_release_impact.py` into the
  wheel. The wheel reserves a `release-impact` subcommand but does
  not ship one yet (see #489 § "Out of scope"). File a follow-up
  issue to track this and to swap `release-impact-comment` /
  `predict-release-impact-self-test` once the subcommand lands.
- Renovate / Dependabot automation for the pinned `v0.17.1` tag.
  Manual bump on release-bot's publish PR is the documented cadence
  for now; file a follow-up issue if the manual cost becomes
  meaningful.
- Moving the rewritten jobs into the new nested
  `check-pull-request.yml` (the issue body explicitly punts this to
  #463: "doing the validator-source swap first, in place, lets us
  prove the released artifact works end-to-end before the larger CI
  restructure rearranges where the jobs live").

## Design and verification

- **Threat model** — N/A. The cutover swaps one script for an
  equivalent wheel binary, no change to the trust boundary; the
  workflow stays on `pull_request_target` with the same base-ref
  pinning that prevents fork PRs from weakening the validator.
  Adding a `gh release download` is a privileged-token operation
  the workflow already uses (see the `release-impact-comment` job).
- **ADR** — N/A. No new architectural decision; this is the
  consumption side of #446's already-decided "ship validators as a
  wheel" architecture (ADR superseded by the package extract).
- **PIR** — N/A.
- **QM / SIL** — N/A. Validator behaviour is unchanged; only the
  invocation path changes.

## Post-implementation standards review

- Apply coding standards (`coding-standards.md`) — N/A,
  workflow-only edit.
- Apply service design (`service-design.md`) — N/A.
- Apply release and hygiene (`release-and-hygiene.md`) — verify
  the changelog YAML lands and the version/CHANGELOG paths still
  work.
- Apply testing standards (`testing-standards.md`) — verify the
  fixture-driven self-test surface still runs.
- Apply tooling and CI standards (`tooling-and-ci.md`) — composite
  action's local `uses:` is fine without a SHA pin (local refs
  are version-locked to the repo commit). The `gh release download`
  step relies on the default `GITHUB_TOKEN` which already has
  `contents: read` for private-release downloads.
