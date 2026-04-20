# Plan: Split integration tests into per-service workflow jobs

Issue: [#138](https://github.com/aidanns/agent-auth/issues/138).

Follow-up from #104 (parallel unit + integration).

## Goal

Fan out the single `integration` job in `.github/workflows/test.yml`
into four per-service jobs so they run in parallel. Each service's
tests live in `tests/integration/`, partly in subdirectories and
partly at the top level. Total integration wall-clock drops from
`sum(per-service durations)` to roughly `max(per-service durations)`.

The `tests` rollup already exists (from #104) and gates merges on
`needs: [...]`; extend its needs list rather than add a second rollup.

## Non-goals

- **Docker layer caching** — tracked separately in #129. Ordering: this
  plan ships regardless; caching compounds the win when it lands.
- **Matrix strategy** — deliberately avoided. #69 will want a
  per-service macOS runner for the AppleScript path, which is easier
  with explicit jobs than a matrix.
- **Test reorganisation beyond moving agent-auth tests into their own
  subpackage.** No fixture refactoring, no shared-harness changes.

## Deliverables

1. **`tests/integration/agent_auth/`** — new subpackage holding the
   current top-level `test_*.py` files. Makes the integration test
   tree uniform (every service has its own subpackage) and eliminates
   the need for a drift-prone `--ignore` list in the agent-auth slice.

2. **`scripts/test.sh`** — `--integration` accepts an optional
   positional service argument:

   ```
   task test -- --integration                       # all services (unchanged default)
   task test -- --integration agent-auth
   task test -- --integration things-bridge
   task test -- --integration things-cli
   task test -- --integration things-client-applescript
   ```

   Extra pytest args still forward after the service name.

3. **`.github/workflows/test.yml`** — replace the single `integration`
   job with four per-service jobs, each listed in the `tests` rollup's
   `needs` list.

4. **Docs** — update `design/DESIGN.md:747` (`tests/integration/test_*.py`
   reference) and `plans/token-management-http-api.md:62` is a
   historical plan so leave untouched.

## Design and verification

Skipped template steps (reasons):

- *Verify against design doc* — no functional change to agent-auth or
  things-bridge. Only the physical layout of test files moves, plus a
  CI parallelisation.
- *Threat model / cybersecurity* — no runtime surface changes.
- *QM / SIL* — same test coverage; only scheduling changes.
- *ADRs* — no architectural decision. The move of agent-auth tests is
  a mechanical uniformity fix, not a design choice.

## Implementation steps

1. **Move agent-auth tests.** `git mv tests/integration/test_*.py tests/integration/agent_auth/`. Create an `__init__.py` in the new
   dir (matches the other service subpackages). Verify no import
   path breaks by running the unit tests and one integration slice
   locally.

2. **Teach `scripts/test.sh` per-service targeting.** Introduce a
   `SERVICE_PATHS` associative map inside the script:

   ```
   declare -A SERVICE_PATHS=(
     [agent-auth]=tests/integration/agent_auth/
     [things-bridge]=tests/integration/things_bridge/
     [things-cli]=tests/integration/things_cli/
     [things-client-applescript]=tests/integration/things_client_applescript/
   )
   ```

   After `--integration` is consumed, if the next arg is a known
   service name, run only that path; otherwise run the whole
   `tests/integration/` tree (current behaviour preserved). Unknown
   service names should fail fast with a clear message listing the
   valid keys.

3. **Update `.github/workflows/test.yml`.** Replace the single
   `integration` job with four jobs — `integration-agent-auth`,
   `integration-things-bridge`, `integration-things-cli`,
   `integration-things-client-applescript` — each invoking
   `task test -- --integration <service>`. Add all four to the
   `tests` rollup's `needs` list and update its step's `if:` to check
   every dependency's result.

4. **Derive the `needs` result check** so drift can't happen. Use
   `contains(join(needs.*.result, ''), 'failure')` /
   `contains(join(needs.*.result, ''), 'cancelled')` style, or the
   already-shipped bash inline form extended to every upstream.
   Pick whichever reads more clearly with five upstream jobs.

5. **Docs.** Update `design/DESIGN.md:747` — change the glob to cover
   the new layout (`tests/integration/agent_auth/test_*.py`). Skim
   the rest of `design/` and `README.md` / `CONTRIBUTING.md` for any
   further hits.

6. **Local verification.**

   - `task test -- --integration agent-auth` → runs only agent-auth
     tests.
   - `task test -- --integration things-bridge` → runs only
     things-bridge tests.
   - `task test -- --integration` → runs all services (unchanged
     default).
   - `task test -- --integration unknown-service` → fails fast.

## Post-implementation standards review

- *Coding standards* — n/a (no production code).
- *Service design* — n/a.
- *Release & hygiene* — verify release automation doesn't depend on
  a check named `integration` (the previous PR #133 already audited
  this).
- *Testing standards* — verify each service's test count is
  preserved. The pre-move count on main plus the post-split count
  must match.
- *Tooling & CI* — verify `scripts/test.sh` usage string and
  `Taskfile.yml` still describe the surface correctly (Taskfile uses
  `{{.CLI_ARGS}}` so no change needed).

## Risks

- **Branch-protection gap** — the rollup's job name stays `tests`, so
  no branch-protection action is required. Same story as #133.
- **Runner concurrency** — 1 unit + 4 integration = 5 parallel
  runners. If the repo hits the GHA concurrency cap, the last job
  queues but still runs; wall-clock would equal
  `max(unit, queued-max-integration)` in that case. Acceptable.
- **Per-service image rebuild cost** — every integration job builds
  `docker/Dockerfile.test` once. Before #129 caching lands, four jobs
  each pay the full build cost, which burns more CI minutes even as
  wall-clock drops. Call out in the PR description.
