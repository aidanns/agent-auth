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

### Apply new lessons codebase-wide in the same PR

When a plan-template lesson gets folded into `TODO.md`, the
triggering example gets fixed but other instances of the same
pattern in the codebase tend to stay unpatched. Round 1 of
[#4](https://github.com/aidanns/agent-auth/pull/4) added
`Ciphertext = NewType(...)` and a lesson about NewTypes at trust
boundaries; the signing and encryption keys — same principle, same
file neighborhood — needed a dedicated round-2 comment before
getting the same treatment. Plan templates should include a "when
recording a new plan-template lesson, sweep the whole codebase for
other instances of the same pattern and fix them in the same PR"
step, so the lesson is deployed, not just documented.
