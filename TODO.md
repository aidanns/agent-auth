# TODO

Outstanding items missed from or deferred by the original implementation plan
(`plans/implement-agent-auth-server.md`).

## In DESIGN.md but not implemented

### Example app bridge (deferred)

The plan's Context section explicitly defers the example app bridge to a
follow-up. Functions in the decomposition covering this area:

- Handle App Commands
- Send Bridge Request
- Serve Bridge HTTP API
- Execute External System Interaction

### Example app CLI (deferred)

Also explicitly deferred in the plan. Depends on the bridge.

## Missing from DESIGN.md and the plan (should have been included)

### Verify implementation matches DESIGN.md

The plan's verification step checked that the CLI/server behaved as
described, but it did not include an explicit cross-check of the final
implementation against `design/DESIGN.md`. Add this to the plan template
(and future plans): after implementation, diff the behavior and schema
against the design doc, reconcile any drift, and either fix the code or
update the design.

### Add `scripts/test.sh`

The plan did not call for a repeatable test runner. `scripts/test.sh`
has since been added, but future plans should include a step to create
or verify that such a script exists so the test suite can be run with
one command.

### GitHub Actions for all tests

The plan produced a workflow for `scripts/verify-design.sh` only
(`.github/workflows/verify-design.yml`). `scripts/test.sh` and
`scripts/verify-function-tests.sh` have no CI coverage, so unit and
integration test regressions and function-coverage regressions can
land on `main` unnoticed. Future plans should include a step to wire
every repeatable check script into GitHub Actions.

### Function-to-test allocation

The `systems-engineering function verify` check reports **0 of 48 leaf
functions** from `design/functional_decomposition.yaml` are allocated to
tests in `tests/`. The implementation has coverage, but neither the
design nor the plan specified how tests should declare the functions
they exercise. Decide on an annotation/allocation mechanism, document
it in the design, and apply it so `scripts/verify-function-tests.sh`
passes.

Run `scripts/verify-function-tests.sh` to see the current list.
