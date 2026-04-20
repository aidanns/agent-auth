<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Split CI unit and integration tests into parallel jobs

Issue: [#104](https://github.com/aidanns/agent-auth/issues/104).

Source: GitHub issue #104 — CI latency optimisation. No
instruction-file standard mandates this.

## Goal

Reduce PR wall-clock time by running the unit suite and the Docker-backed
integration suite in parallel on CI. Total time should drop from
`unit + integration` to roughly `max(unit, integration)`, and unit-test
failures should surface before the integration image finishes building.

Today `.github/workflows/test.yml` has a single `test` job that invokes
`task test -- --all`, which runs `pytest tests/ --ignore=tests/integration`
and then `pytest tests/integration/` sequentially. The integration layer
builds `docker/Dockerfile.test` once per session (in
`tests/integration/_support.py:build_test_image`) and spins up a fresh
Compose project per test, so its cost dominates.

## Non-goals

- **Matrix OS expansion** — #69 tracks adding a macOS runner for the
  AppleScript path. This plan must not block that work, but does not
  implement it. The new structure should make adding a `macos` job a
  trivial extension of the `unit` / `integration` job definitions.
- **Changes to `scripts/test.sh` or `Taskfile.yml`** — the split is a
  workflow-level change only. Local `task test -- --all`, `--unit`,
  and `--integration` must keep working unchanged.
- **Branch-protection configuration in this repo** — see #93. This
  plan produces a rollup check that *can* be required; actually
  updating branch protection is a separate admin-level step.
- **Docker layer caching across runs** — the integration harness
  currently builds the test image with a direct `docker build` call
  that does not accept `--cache-from` flags. Wiring GHA/buildx cache
  requires a harness change that is out of scope for this PR. Filed as
  a follow-up issue; see step 4 below.

## Deliverables

1. **`.github/workflows/test.yml`** restructured to two parallel jobs
   plus a rollup:
   - `unit` — runs `task test -- --unit`. No Docker needed.
   - `integration` — runs `task test -- --integration` on a Docker-
     capable runner.
   - `tests` — rollup job with `needs: [unit, integration]`. This is
     the single check branch protection can require.
2. **Follow-up issue** filed against this repo for wiring buildx +
   GHA cache into the integration harness (so future PRs see reduced
   image-build cost on top of the parallelism win).
3. **No change** to `scripts/test.sh` or `Taskfile.yml`.

## Design and verification

The following plan-template steps are **not applicable** and are
intentionally skipped, with reasons:

- *Verify implementation against design doc* — the test workflow is
  developer/CI tooling. It does not appear in `design/DESIGN.md`,
  `functional_decomposition.yaml`, or `product_breakdown.yaml`. The
  only design-doc touchpoint is `design/ASSURANCE.md:49`'s CI-gating
  bullet, which lists `task test` abstractly; splitting its execution
  across two runners does not change that statement.
- *Threat model / cybersecurity standard compliance* — no change to
  the running service's attack surface, secrets, or data flow. The
  new workflow exposes the same `GITHUB_TOKEN` to the same composite
  action it already uses.
- *QM / SIL compliance* — no change to the production code path or
  its evidence requirements. Pytest produces the same results; only
  the scheduling changes.
- *ADRs* — splitting a CI job across runners is an operational
  optimisation, not a novel architectural decision. No ADR required.

## Implementation steps

1. **Restructure `.github/workflows/test.yml`** into three jobs:
   `unit`, `integration`, and `tests`. Shape:

   ```yaml
   name: Test

   on:
     push:
       branches: [main]
     pull_request:
       branches: [main]

   jobs:
     unit:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v6
         - uses: ./.github/actions/setup-toolchain
           with:
             github-token: ${{ secrets.GITHUB_TOKEN }}
         - name: Run unit tests
           run: task test -- --unit

     integration:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v6
         - uses: ./.github/actions/setup-toolchain
           with:
             github-token: ${{ secrets.GITHUB_TOKEN }}
         - name: Run integration tests
           run: task test -- --integration

     tests:
       runs-on: ubuntu-latest
       needs: [unit, integration]
       if: always()
       steps:
         - name: Aggregate unit and integration results
           run: |
             if [[ "${{ needs.unit.result }}" != "success" \
                || "${{ needs.integration.result }}" != "success" ]]; then
               echo "unit=${{ needs.unit.result }} integration=${{ needs.integration.result }}"
               exit 1
             fi
   ```

   The rollup uses `if: always()` plus an explicit result check so a
   skipped or failed upstream job fails the rollup. Default `needs`
   semantics would skip the rollup on upstream failure, which would
   let branch protection see "no check ran" instead of a failure.

2. **Verify the change on the PR itself.** Compare:

   - Baseline: the most recent `test` run on `main` (record its
     wall-clock).
   - New: the first `tests` rollup run on this PR (record `unit`,
     `integration`, and rollup wall-clocks).

   Put both in the PR description as evidence for acceptance criterion
   2 of #104 ("strictly lower than the current serialized run").

3. **Branch-protection note in PR description.** Call out that after
   merge the required check name changes from `test` to `tests` (the
   rollup job). The admin needs to update branch protection before
   requiring the new check. Ties into #93.

4. **File follow-up issue** for Docker layer cache. Filed as
   [#129](https://github.com/aidanns/agent-auth/issues/129) — covers
   wiring `docker/setup-buildx-action` plus `docker buildx build --cache-from type=gha --cache-to type=gha,mode=max` inside
   `tests/integration/_support.py:build_test_image`. Link from the PR
   description.

5. **Documentation review** — survey `README.md`, `CONTRIBUTING.md`,
   `design/ASSURANCE.md` for prose about the test workflow's single-job
   shape. Current survey (done while drafting this plan):

   - `README.md:41,47` — refers to `task test` command, not the
     workflow. No change.
   - `CONTRIBUTING.md:41,59` — refers to `task test` as a Taskfile
     entrypoint. No change.
   - `design/ASSURANCE.md:49` — lists `task test` as a CI gate. The
     statement remains accurate (both jobs still invoke `task test`
     with a mode flag). No change.

   Confirm during implementation that no new references have been
   added since this survey.

## Post-implementation standards review

- *Coding standards* — not applicable; no production code changes.
- *Service design standards* — not applicable; no service changes.
- *Release and hygiene* — verify the workflow still runs on the same
  `push` / `pull_request` triggers so release automation is
  unaffected.
- *Testing standards* — verify the split does not change what is
  tested, only where and in parallel. `task test -- --all` still works
  locally.
- *Tooling and CI* — verify `scripts/verify-standards.sh` still
  passes (it enforces cross-project tooling standards, not workflow
  shape).

## Risks

- **Acceptance criterion 1 (rollup is the merge gate)** depends on
  branch protection being updated out-of-band. This PR delivers the
  rollup but cannot enforce it; flag in the PR description.
- **Parallel-job runner contention** — the repo's default runner
  concurrency allows at least two parallel `ubuntu-latest` jobs. No
  change expected; if the org hits a queue limit the total wall-clock
  may not drop as much on that run, but the structure is still
  correct.
