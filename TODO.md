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

### Function-to-test allocation

Tests now declare the leaf functions they exercise via
`@pytest.mark.covers_function("Function Name", ...)` decorators, which
`systems-engineering function verify` reads. Coverage stands at **37 of
47** leaf functions; the 10 uncovered functions are all in the deferred
Example App Bridge / Example App CLI components, plus
`Handle Serve Command` and `Load Notification Plugin` (both exercised
indirectly by the server integration tests but not annotated as such).

Run `scripts/verify-function-tests.sh` to see the current list.
