<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Parallelise the 7 release-binary downloads in setup-toolchain

Resolves [#168](https://github.com/aidanns/agent-auth/issues/168) (part 3 of
the #165 follow-up work; parts 1 and 2 landed in #169).

## Problem

`.github/actions/setup-toolchain/action.yml` now has 7 install steps
(`shellcheck`, `shfmt`, `ruff`, `taplo`, `keep-sorted`, `ripsecrets`,
`treefmt`) that each call `scripts/ci/fetch-release-asset.sh` to
download a release binary and verify its sha256. Composite-action
steps run sequentially, so those 7 independent network downloads
(~tens of MB each) are serialised on every CI job.

## Approach

Collapse the 7 `Install <tool>` steps into one composite-action step
that:

1. Fires all 7 `fetch-release-asset.sh` invocations as background
   jobs in a single `bash` block, then waits on each and fails fast
   if any sha256 / curl failure happens.
2. After every download has landed on disk, runs the per-tool
   extract/install commands sequentially. Extraction is cheap
   (local disk IO) compared to the network downloads, so there's no
   point parallelising it too.

Single-step is chosen over "download step + install step" because:

- The env-var set is the same (all 7 `*_VERSION` + `*_SHA256` are
  needed — versions by the URL at download time and by the install
  paths at install time).
- The combined step log is still readable if we emit clear
  `::group::` markers around each tool.
- Two steps would just duplicate the 14-line `env:` block.

Failure semantics:

- Each backgrounded `fetch-release-asset.sh` has `set -euo pipefail`
  and exits nonzero on curl or sha256 failure.
- The wait loop captures each job's exit code via `wait "$pid"`. A
  plain `wait` without args returns only the last job's exit code
  and hides the rest.
- Accumulate failures into a single nonzero exit so the step fails
  if any download failed, with every failing job's output still in
  the log.

Concurrency and auth:

- 7 concurrent downloads × ~tens of MB is well inside GitHub-hosted
  runner bandwidth and memory budget (each helper invocation is a
  `curl` + `sha256sum`, neither of which pins memory).
- Every download uses the same `${GITHUB_TOKEN}` so the 5,000/hr
  token budget is shared as today — no change in rate-limit
  behaviour.

Rejected alternatives:

- **`curl --parallel --parallel-max 7` in the helper.** Changes the
  helper's interface — it'd take a list of `(url, path, sha256)`
  triples and become a small batch runner. The `&`/`wait` pattern
  keeps the helper as a single-asset primitive and lives entirely
  at the call site.
- **Two separate steps (download then install).** Would require the
  step-level `env:` block to be duplicated and doesn't buy
  anything — both steps run on the same runner in the same
  composite action.
- **GitHub Actions matrix job.** Loses the per-job environment
  (`/usr/local/bin`, `$GITHUB_PATH`) propagation and complicates
  caller workflows. Out of scope.

## Changes

1. `.github/actions/setup-toolchain/action.yml` — replace the 7
   `Install <tool>` steps with a single `Install release binaries`
   step containing one bash block that:
   - Declares `SHELLCHECK_VERSION`/`SHELLCHECK_SHA256`/... +
     `GITHUB_TOKEN` in `env:`.
   - Backgrounds 7 `scripts/ci/fetch-release-asset.sh` invocations,
     recording PIDs.
   - Waits on each PID, accumulating failures.
   - Emits `::group::` markers around each tool's extract/install
     and version-echo so the step log reads per-tool.
2. `CHANGELOG.md` — add an Unreleased "Changed" entry referencing
   #168 and cross-linking #165 / #169.

## Verification

- PR CI run passes: every workflow still reaches tool commands
  (shellcheck/shfmt/ruff/taplo/keep-sorted/ripsecrets/treefmt) after
  the setup-toolchain action runs.
- Spot-check the `Install release binaries` step log and confirm:
  - Multiple `scripts/ci/fetch-release-asset.sh` invocations appear
    with overlapping/interleaved start timestamps (parallel).
  - Each sha256 verification reports OK.
  - Each `<tool> --version` line appears.
  - Step wall-time is visibly lower than the sum of the old 7
    steps' wall-times in the pre-#168 PRs.
- `shellcheck` / `shfmt` / `treefmt` clean on the bash block (via
  `treefmt --no-cache --fail-on-change` in CI).

## Skipped plan-template steps

- **Design / threat-model / ADR / cybersecurity / QM-SIL** — this is
  a composite-action refactor that preserves every
  behaviour-observable property (sha256 verify, auth, retry,
  extract, install). No runtime, no security posture, no external
  surface change.
- **Post-implementation standards review** — only
  `tooling-and-ci.md` applies. sha256 pinning contract is
  preserved (each `scripts/ci/fetch-release-asset.sh` call still
  runs `sha256sum -c -`). `bash.md` shellcheck/shfmt gates still
  pass.
