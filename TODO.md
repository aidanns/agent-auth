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
commits. Add `ripsecrets` (preferred — fast, Rust-based) as a
pre-commit hook so tokens, keys, or credentials cannot be committed
by mistake. Include this in future plan templates.

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

### Metrics endpoint

The server exposes no runtime metrics. Add `GET /agent-auth/metrics`
emitting Prometheus-compatible text (or another documented format)
covering at least: request counts and latency per endpoint, token
operations by type (create/refresh/revoke/rotate/reissue),
validation decisions by tier (allow/prompt/deny), JIT approval
outcomes, active token families, and approval-grant cache size.
Decide the format (Prometheus text exposition vs OpenMetrics vs
plain JSON) and document it in `design/DESIGN.md` alongside the
health endpoint. Include a metrics-endpoint step in future plan
templates for daemons and long-running services.

### Performance testing

There is no performance-testing layer. The plan covered
correctness tests but not load, stress, or benchmark testing. Add a
benchmark suite (e.g. `pytest-benchmark` for microbenchmarks,
`locust` or `k6` for HTTP load), run it in CI on a schedule or
nightly, and track results over time to catch regressions. Include
performance-testing design in future plan templates for services
with latency or throughput requirements.

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

### Python tooling (linter, formatter, type checker, venv)

The project has no linter, formatter, or type checker wired into CI,
and uses the stock `python3 -m venv` instead of a modern venv
manager. Adopt:

- `ruff` for linting and formatting
- `mypy` and `pyright` for type checking (pyright catches different
  issues and is faster; mypy is the community baseline)
- `uv` for virtual environments and dependency resolution
- `pytest-cov` for coverage (see the coverage-threshold item below)

Gate PRs on the lint, format, and type checks. Include these tools
in future plan templates for Python projects.

### Line and branch coverage threshold

Test coverage is tracked structurally (function-to-test allocation)
but not by line or branch coverage, and there is no coverage floor
enforced in CI. Add `pytest-cov` to CI with a starting threshold
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

### Bash tooling (linter and formatter)

The project ships bash scripts (`scripts/*.sh`, `bootstrap.sh`-style
entrypoints) with no lint or format enforcement. Adopt:

- `shellcheck` for linting
- `shfmt` for formatting

Gate PRs on both. Include these tools in future plan templates for
any project that ships bash.

### go-task task runner

Project operations (build, lint, test, release) are each a separate
bash script invoked by hand. Adopt [`go-task`](https://taskfile.dev)
and a `Taskfile.yml` at the repo root so every operation is
discoverable (`task --list`) and composable (dependencies between
tasks). Keep the `scripts/*.sh` implementations; have the Taskfile
dispatch to them. Include a task runner step in future plan
templates.

### treefmt for formatter/linter multiplexing

As more language-specific formatters and linters are added (ruff,
shfmt, mdformat, taplo, etc.), invoking each by hand or wiring each
into CI separately is tedious. Adopt `treefmt` to run them all
under one command with consistent behaviour, then call `treefmt`
from lefthook and CI. Include a multiplexer step in future plan
templates for multi-language projects.

### VS Code project generation

There is no committed `.vscode/` configuration and no generator for
it, so every contributor re-derives tasks, launch configs, and
recommended extensions. Generate or commit a `.vscode/` directory
covering recommended extensions, debug configurations, and workspace
settings. For monorepos, generate a multi-root `.code-workspace`
file. Include a VS Code project generation step in future plan
templates.

### lefthook for git pre-commit hooks

There is no git hook management, so secrets-scanning, formatting,
and linting rely on CI alone — too late to catch easily. Adopt
`lefthook` and commit a `lefthook.yml` that runs `ripsecrets`,
`treefmt` (once adopted), and quick unit tests on pre-commit.
Include a git-hook manager step in future plan templates.

### keep-sorted for language-agnostic sorting

Sorted blocks of code, imports, and lists drift out of order over
time without tooling. Adopt `keep-sorted` with annotated blocks so
sorted regions stay sorted automatically. Include a keep-sorted
step in future plan templates for projects with sorted lists
(imports, dependency lists, allow-lists, etc.).

### mdformat for Markdown formatting

Markdown files (README, DESIGN, CLAUDE.md, TODO, PR bodies) are
hand-formatted, so table alignment, list indentation, and trailing
whitespace drift. Adopt `mdformat` (with plugins for tables and
GitHub-flavored Markdown) and call it from `treefmt`/lefthook.
Include a Markdown formatter step in future plan templates.

### taplo for TOML formatting

`pyproject.toml` and any other TOML files (`Cargo.toml`, configs)
are hand-formatted. Adopt `taplo` for TOML linting and formatting
and call it from `treefmt`/lefthook. Include a TOML formatter step
in future plan templates for projects with TOML config.

### LICENSE.md and README link

The project has no `LICENSE.md`. Add one (default: MIT) and link to
it from the "License" section in the README. Include a LICENSE
step in future plan templates for any project with a public
repository.

### Include units in names of configuration fields and constants

Initial implementation had `access_token_ttl: int`, `refresh_token_ttl:
int`, and `KEY_SIZE = 32` — all of which forced readers to guess the
unit. Adopt a convention that any numeric configuration field or
constant carrying a unit encodes it in the name
(`access_token_ttl_seconds`, `KEY_SIZE_BYTES`). Include a "units in
names" bullet in CLAUDE.md and the plan template's coding-standards
section.

### XDG Base Directory compliance across all path classes

The initial implementation put everything under `~/.config/agent-auth`
(config, DB, and logs). Per the XDG Base Directory Spec, data belongs
in `$XDG_DATA_HOME`, state/logs in `$XDG_STATE_HOME`, and config in
`$XDG_CONFIG_HOME`. Future plans for any project that persists files
on disk should include a "path layout" step that maps each
file class to its XDG variable.

### NewType at security/trust boundaries

The initial `encrypt_field` / `decrypt_field` accepted and returned
raw `bytes`, so a caller could accidentally pass plaintext to a
store field that expected ciphertext (or vice versa) with no type
checker complaint. Future plans for projects with security-critical
type distinctions should require `typing.NewType` (or equivalent) at
the boundary — and a note in the plan template to look for these
boundaries up front.

### Don't persist default configuration on first run

The initial `load_config` created and wrote a default `config.json`
on first run. A fresh install should rely on in-code defaults until
the user deliberately customises them — writing a defaults file
creates a parallel source of truth and forces migration work when
defaults change. Plan templates for projects with config files
should include a "defaults live in code, not on disk" step.

### Semantic types instead of raw tuples/strings for structured keys

The initial `ApprovalManager` used `dict[tuple[str, str], datetime]`
for session grants, leaving the meaning of each tuple element
implicit. Prefer `typing.NamedTuple` (or `dataclass`) whenever a
tuple or raw string carries structure. Include a "name your keys"
bullet in the plan template's coding-standards section.

### Tests should assert persistent state, not captured stdout

Early CLI tests asserted on `stdout` text only (e.g. `"revoked" in
out.lower()`). These are fragile to formatting changes and do not
prove the on-disk state matches the user-visible report. Plan
templates should require that CLI/integration tests verify the
durable state (DB rows, filesystem effects, keyring entries) in
addition to or instead of stdout.

### Single source of truth for configuration

Initially `agent-auth serve` duplicated `--host` and `--port` flags
that already existed in `config.json`. Two sources of truth for the
same value invites drift (which one wins? is it logged?). Plan
templates should require: for each configurable value, pick exactly
one source of truth — flag, config field, or env var — and document
why.

### Version string derived from git tags

`__version__` was hard-coded to `"0.1.0"` in two places
(`__init__.py` and `pyproject.toml`), forcing manual bumps on every
release. Adopt `setuptools-scm` (or language-equivalent) so the
version is derived from git tags at build time, and read it back via
`importlib.metadata`. Include a "version from git tags" step in the
plan template for any project with a release surface.

### Audit-log on-disk format is a public API

The audit log's JSON-lines schema is load-bearing for downstream
consumers (SIEM ingestion, compliance review, forensics), but the
initial tests only asserted a couple of fields. Lock the schema with
tests that pin every field's name and type. Plan templates for
projects with audit output should treat the log format as a public
API and require schema tests.

### Plugin systems that run arbitrary code in a secret-holding process

The notification plugin interface uses `importlib.import_module` so
any Python module on the path can run inside the agent-auth server
process — which also holds the signing and encryption keys. Tracked
in [#6](https://github.com/aidanns/agent-auth/issues/6). The lesson
for plan templates: when a project holds secrets, any plugin or
extension surface should default to out-of-process (HTTP, IPC) so
third-party code never crosses the trust boundary.

### Integration-test isolation strategy

The initial HTTP integration tests bound directly to `127.0.0.1` on
an ephemeral port. On a host with multiple branch-worktrees
running simultaneously (or a CI runner with parallel jobs) this
races. Tracked in
[#7](https://github.com/aidanns/agent-auth/issues/7). Plan templates
for network-facing projects should include an "integration-test
isolation" step that picks containers, per-test network namespaces,
or an equivalent approach up-front.
