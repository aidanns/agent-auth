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

### End-to-end tests

The plan produced unit tests per module plus HTTP-integration tests
that exercise individual endpoints, but no end-to-end test that drives
the full lifecycle (CLI creates a token → server validates it for an
allow-tier scope → refresh rotates the pair → JIT approval gates a
prompt-tier scope → revocation invalidates subsequent use). Add an
end-to-end test layer and include it in future plan templates.

### SECURITY.md

There is no `SECURITY.md` summarising the project's cybersecurity
approach — trust boundaries, threat model, key handling, revocation
flow, audit surface, and how to report vulnerabilities. Add one and
reference it from `README.md`. Future plans for network-facing or
credential-handling projects should include a `SECURITY.md` step.

### Cybersecurity standard compliance check

The implementation has not been checked against a recognised
cybersecurity standard such as the Australian Government Information
Security Manual (ISM) or NIST SP 800-53. Pick a standard appropriate
to the project's intended use, walk the relevant controls, record
results in `design/`, and raise issues for any gaps. Future plans
should include the choice of standard and the compliance check as
explicit steps.

### Declare quality management / SIL level

The README does not declare a quality-management level (per ISO 9000)
or safety-integrity level (per IEC 61508) for the project. Decide what
level is appropriate given the project's role in gating real
application access, document it in the README (and/or `design/`), and
add a section to future plan templates to capture this up front.

### Verify implementation against declared QM / SIL level

Once a QM / SIL level is declared (see item above), verify the
implementation meets the activities, documentation, and evidence
requirements for that level. Record the verification results in
`design/` and keep them up to date as the code evolves. Future plans
should include this verification step.

### Threat model

There is no structured threat model (STRIDE or attack-tree) documented
for the project. The threat model is the root artefact that should
drive `SECURITY.md`, standards compliance, rate limiting, and key
recovery design — without it each of those is done in isolation.
Record the threat model in `design/` and include a "produce or
refresh the threat model" step in future plan templates.

### Dependency vulnerability scanning

Neither the project nor its CI scans dependencies for known
vulnerabilities. Add `pip-audit` (or `safety`) to CI and enable
Dependabot (or Renovate) for lockfile updates. Include the tool
choice in future plan templates for projects with external
dependencies.

### Secrets scanning pre-commit hook

There is no pre-commit hook guarding against accidental secret
commits. Add `gitleaks` or `detect-secrets` as a pre-commit hook so
tokens, keys, or credentials cannot be committed by mistake. Include
this in future plan templates.

### Rate limiting and DoS story

The HTTP API has no rate-limit story. Even on localhost a misbehaving
process can hammer `/validate`. Decide an expected request rate and
a ceiling, document it in `design/DESIGN.md`, and either implement
rate limiting or explicitly note why it is not required. Future plans
should include a "DoS posture" step for network-facing projects.

### Key recovery and loss scenarios

If the user's keychain is wiped, agent-auth silently generates new
signing and encryption keys on next run, invalidating every
outstanding token without warning. Design a deliberate
recovery/backup/warning flow and document it. Future plans should
include a "what happens when secrets are lost" step for projects
that manage keys.

### Observability design

The plan did not include an observability design step. Document the
log schema, log levels, log retention policy, log location (per XDG,
`$XDG_STATE_HOME`, not `$XDG_CONFIG_HOME`), and what metrics (if
any) are emitted. Include observability design in future plan
templates for daemons and long-running services.

### Health-check endpoint

The server has no health-check endpoint. Add `GET /agent-auth/healthz`
that returns 200 when keys load and the DB is readable. Include a
health-check endpoint in future plan templates for HTTP services.

### Performance budget

There is no documented performance budget for the HTTP endpoints
(e.g. `/validate` p95 latency). Pick a target, document it in
`design/DESIGN.md`, and add at least one integration test that
asserts the budget. Include a performance-budget step in future plan
templates for latency-sensitive services.

### Graceful shutdown

There is no design or test for graceful shutdown. When `serve`
receives SIGTERM today, in-flight JIT approval requests probably
hang. Design the shutdown behaviour, implement it, and add a test.
Include graceful shutdown in future plan templates for daemons.

### Architecture Decision Records

The project has several load-bearing decisions (stdlib HTTP vs
framework, per-thread SQLite + WAL, in-memory JIT grants, HMAC
prefix inclusion, etc.) whose rationale lives only in commit
messages and the plan document. Start an `design/decisions/`
directory of short ADRs so the *why* survives. Include ADR creation
for significant decisions in future plan templates.

### API versioning strategy

HTTP endpoints are exposed as `/agent-auth/validate` etc. with no
version segment and no documented compatibility policy. Decide a
versioning strategy (URL-versioned, header-versioned, or explicit
"breaking changes bump the binary major version"), document it in
`design/DESIGN.md`, and apply it. Include an API versioning step
in future plan templates.

### DB schema migration strategy

The SQLite schema is created in Python code with no version tracking.
Any future column change will be painful. Add a `schema_version`
table and a simple idempotent migration mechanism. Include a DB
migration strategy step in future plan templates for projects with
persistent storage.

### Stable error taxonomy

The HTTP error strings (`refresh_token_reuse_detected`,
`family_revoked`, `scope_denied`, etc.) are a de-facto public API
but are not documented as such in `design/DESIGN.md`. Document
them and their stability guarantees. Include error-taxonomy
documentation in future plan templates for HTTP APIs.

### Linter, formatter, and type checker in CI

The project has no linter, formatter, or type checker wired into CI.
Add `ruff` (lint + format) and `mypy` and gate PRs on them. Include
this in future plan templates for Python projects.

### Line and branch coverage threshold

Test coverage is tracked structurally (function-to-test allocation)
but not by line or branch coverage, and there is no coverage floor
enforced in CI. Add `coverage.py` to CI with a starting threshold
that ratchets upward. Include coverage threshold configuration in
future plan templates.

### Mutation testing on security-critical paths

Coverage alone does not guarantee tests would fail when they should.
Run `mutmut` or `cosmic-ray` against `tokens.py`, `crypto.py`, and
`scopes.py` to surface weak assertions. Include mutation testing of
security-critical modules in future plan templates for security-
critical projects.

### Chaos and fault-injection tests

The test suite exercises happy paths; error paths (keyring throws,
DB is locked, disk is full, plugin times out) are largely untested.
Add a fault-injection test layer that forces these conditions.
Include chaos/fault-injection testing in future plan templates.

### CONTRIBUTING.md and release process

There is no `CONTRIBUTING.md` documenting dev setup, testing,
release cutting, or signing procedures. Add one — even for a
personal project, it saves time for future-you and for Claude.
Include a CONTRIBUTING.md step in future plan templates.

### CHANGELOG.md

There is no `CHANGELOG.md` tracking user-visible changes. Adopt
Keep-a-Changelog formatting, pair with semantic versioning, and
require updates on every user-facing PR. Include a CHANGELOG.md
step in future plan templates.

### install.sh with curl | bash idiom

The project has no one-line install script. Add `install.sh` at the
repo root that installs agent-auth on Linux and macOS, and document
the `curl -fsSL <url> | bash` idiom in the README. Include an
install script step in future plan templates for user-facing
binaries and daemons.

### Conventional commit instructions in CLAUDE.md

The project's `CLAUDE.md` does not document the conventional-commit
convention that the repository uses, even though the user's global
CLAUDE.md does. Project-level CLAUDE.md files should also state the
commit-message convention so contributors (human or Claude) see it
without needing the user's global config. Include a "document commit
conventions in project CLAUDE.md" step in future plan templates.

### Release instructions in README

The README does not document how to cut a release (version bump,
tag, GitHub release, publish). Add a "Releasing" section. Include a
release-instructions step in future plan templates for projects with
a public release surface.

### scripts/release.sh

There is no repeatable release script. Add `scripts/release.sh` that
automates version bumping, tagging, and posting the GitHub release.
Include a release script step in future plan templates for projects
with a public release surface.

### Set the GitHub repo "About"

The GitHub repository's "About" field (description, homepage,
topics) is unset. Populate it with a one-line description that
matches the README summary, plus relevant topics. Include a "set
the GitHub About" step in future plan templates for public
repositories.

### LICENSE.md and README link

The project has no `LICENSE.md`. Add one (default: MIT) and link to
it from the "License" section in the README. Include a LICENSE
step in future plan templates for any project with a public
repository.
