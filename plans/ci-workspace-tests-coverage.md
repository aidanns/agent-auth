<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Run workspace tests + per-package coverage gate in CI (#581)

Closes the gap left by the Phase 5 CI cutover (#516, commit `c9bb1f6`):
the workspace-wide root `tests/` tree (release-semver, scan-failure,
devcontainer-signing, workspace-deps, merge-bot-rollup-dedupe, etc.)
and the per-package coverage floors (#273) are configured but no CI
workflow enforces them. Both gates only run on developer machines via
`task test -- --unit`.

## Chosen shape — Hybrid (per Agent Brief)

Add a single `test-workspace` `workflow_call` child to `ci.yml`. The
job runs `task test -- --unit` (which `scripts/test.sh` already wires
to the canonical workspace-wide pytest invocation that produces a
unified `.coverage`, then chains `scripts/check-package-coverage.sh`
to enforce per-package floors). Add it to the `required-checks-passed`
aggregator's `needs:`. Treat it as diff-dependent (skipped on
verified-prior-success label re-runs, per #527).

Keep the per-package matrix in `test-unit.yml` as-is — it provides
fast per-package signal whose wall-clock would regress if the workspace
gate were folded in. The two checks are complementary:

- `test-unit.yml` (matrix): per-package shards, no coverage, fast
  per-package signal on regression localisation.
- `test-workspace.yml` (single job, new): one workspace-wide pytest
  run that emits a unified `.coverage`; floor check chained on success.

Rejected alternatives:

- **Single workspace-coverage job replacing the matrix** — loses fast
  per-package signal; out-of-scope per Agent Brief AC ("per-package
  matrix continues to provide fast per-package signal — its
  wall-clock is not regressed").
- **Add a "root" entry to `test-unit.yml`'s matrix** — doesn't combine
  `.coverage` files across shards, so the floor check can't run
  against a unified DB (the floor-check script's contract is
  per-package coverage queried from a single `.coverage` produced by
  one workspace pytest invocation).

## File changes

1. **`.github/workflows/test-workspace.yml`** (new) — `workflow_call`
   child mirroring `test-unit.yml`'s shape:

   - `actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd` (v6)
     with `fetch-depth: 0` (setuptools-scm needs tags for
     `tests/test_release_wheel_version.py`).
   - `./.github/actions/setup-toolchain` with `github-token`.
   - `uv sync --extra dev`.
   - `task test -- --unit` (this runs the workspace pytest
     invocation against `UNIT_TEST_PATHS` — including root `tests/`
     — and chains `scripts/check-package-coverage.sh` on success).
   - Single ubuntu-latest runner; no matrix.

2. **`.github/workflows/ci.yml`** — wire the new child:

   - Add `test-workspace` job slot after `test-unit`, gated by
     `needs.plan.outputs.diff_dependent_jobs_already_passed != 'true'`
     (mirrors siblings).
   - Add `test-workspace` to `required-checks-passed.needs:`.
   - Add `test-workspace` to the `DIFF_DEPENDENT_JOB_IDS` env block
     in the aggregator step.

3. **`.github/workflows/test-unit.yml`** — update the stale header
   comment that references "elsewhere in this orchestrator" so it
   points at `test-workspace.yml`.

4. **`tests/test_ci_diff_dependent_probe.py`** — extend the pinned
   `DIFF_DEPENDENT_JOB_IDS` constant and `expected_leaves` set to
   include `test-workspace / test-workspace`. Without this the
   regression-pin test fails immediately on the new diff-dependent
   child (which is the exact drift this test exists to catch).

## `needs:` graph

The new `test-workspace` job runs in parallel with `test-unit`,
`test-integration`, `test-smoke`, `test-system` — all consume the same
`needs: [plan]` and the verified-prior-success `if:` gate. No
inter-test ordering needed.

## Observable user-facing changes

- `ci / required-checks-passed` rollup grows by one diff-dependent
  child (`test-workspace`). The aggregator gate is unchanged in shape
  — branch protection still requires only the single `required-checks- passed` rollup, which now becomes stricter.
- A PR that regresses any test under root `tests/` will now fail
  `test-workspace` instead of passing CI silently.
- A PR that drops any package's `--cov-fail-under` floor will now
  fail `test-workspace` instead of passing CI silently.
- Wall-clock for the rollup grows by ~3 minutes (the local run
  measured 181s for the workspace pytest). Per-package matrix keeps
  its existing wall-clock for fast feedback.

## Out of scope

Per the issue's Agent Brief:

- Ratcheting per-package floors upward (current actuals: agent-auth
  81%/78%, agent-auth-common 73%/49%, gpg-bridge 75%/62%, gpg-cli
  76%/53%, pr-lint-validator 89%/88%, things-bridge 87%/83%,
  things-cli 66%/65%, things-client-cli-applescript 84%/73%).
- Adding new tests to the root `tests/` tree.
- Modifying `scripts/check-package-coverage.sh`'s contract.
- Branch-protection ruleset changes (the rollup gate name is
  unchanged; the new child is invisible to branch protection).

## Verification

Local pre-push:

- `task test -- --unit` exits 0 (already verified — 885 passed, all
  package floors green).
- `scripts/ci/diff-dependent-jobs.sh` enumerates `test-workspace / test-workspace` (verifies the helper auto-extends from `ci.yml`).
- `pytest tests/test_ci_diff_dependent_probe.py -v` passes
  (verifies the constant + expected-leaves drift detector still
  matches after the constant update).

CI:

- The new `test-workspace` check appears on the PR.
- The rollup `required-checks-passed` waits on it.
- The diff-dependent gate skips it on `labeled` re-runs whose head
  SHA already passed once.

## Standards review (post-implementation)

- `.claude/instructions/coding-standards.md` — N/A (workflow YAML, no
  new Python code).
- `.claude/instructions/service-design.md` — N/A (CI infra).
- `.claude/instructions/release-and-hygiene.md` — `no changelog`
  label applied at PR creation (CI-only change, no user-visible
  behaviour beyond the rollup expanding).
- `.claude/instructions/testing-standards.md` — the new gate restores
  enforcement of existing tests; no new tests added (out of scope per
  Agent Brief).
- `.claude/instructions/tooling-and-ci.md` — the new workflow follows
  the existing per-child workflow shape (single `workflow_call`,
  `permissions: contents: read`, SHA-pinned `actions/checkout`).
