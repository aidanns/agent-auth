# TODO

Outstanding items missed from or deferred by the original implementation plan
(`plans/implement-agent-auth-server.md`).

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

### Post-change review checklist should include boundary and naming questions

The post-change `/simplify` skill and the independent review
subagent are tuned to catch local hacky patterns (unused imports,
duplication, obvious dead code) but repeatedly missed judgement
calls on
[#4](https://github.com/aidanns/agent-auth/pull/4) — method-name
specificity (`check_grant` → `check_timed_grant`), public-API
boundaries for tests (go through the CLI vs open the DB), and type
discipline at security boundaries (signing key vs encryption key).
Those categories need dedicated prompts, not general "any
improvements?" prompts. Extend the post-change reviewer's checklist
to ask explicitly: (a) does every method name reflect which variant
of its concept it handles? (b) for each test file, what is the
public surface of the unit under test, and does the test stay
within it? (c) for each `bytes`/`str`/`int` parameter at a trust or
semantic boundary, is there a `NewType` or branded type? Include
these prompts in future plan templates' post-change review step.

## Lessons from PR #9 review (things-cli / things-bridge)

### Semantic types for model identifiers

The `Todo`, `Project`, and `Area` models use bare `str` for `id`,
`project_id`, `area_id`, and similar fields. This makes it easy to
accidentally swap a todo id for a project id at call sites, and type
checkers can't catch it. Introduce `typing.NewType` wrappers (e.g.
`TodoId`, `ProjectId`, `AreaId`) for each entity id, and use them
consistently across models, client methods, and server routing. This
extends the existing TODO item on semantic types for structured keys
to cover the new bridge/CLI code. Plans should include a "define
semantic types for all entity identifiers" step.

### Semantic type names throughout all source files

Reviewer feedback called for semantic type names (not just for
identifiers but for all parameters at trust boundaries): timeout
values should be `timeout_seconds` not `timeout`, URL strings
should be typed distinctly from generic strings, and token strings
should be distinguishable from other string parameters. Future plans
should include a "name parameters semantically" checklist item.

### Per-data-type authorization scopes

The bridge currently uses a single `things:read` scope for all
endpoints (todos, projects, areas). The reviewer asked for separate
scopes per data type (e.g. `things:read:todos`, `things:read:projects`,
`things:read:areas`) so that tokens can be scoped more narrowly.
This is a design-level decision that should have been addressed in
`DESIGN.md` before implementation. Future plans for access-controlled
services should include a "define granular scope model" step.

### Deterministic authorization validation on every endpoint

The bridge server's `do_GET` handler calls `_validate()` in each
route branch, but there is no structural guarantee that new routes
will remember to include the call. A reviewer asked whether there is
a way to deterministically validate that auth is checked on every
endpoint. Options: (a) move validation into a decorator or middleware
layer that runs before routing, (b) add an integration test that
enumerates all routes and asserts each requires a valid token. Plans
for new HTTP servers should include an "auth validation architecture"
step that addresses this.

### Audit logging for every HTTP endpoint

The bridge returns opaque error codes to clients (to avoid leaking
host info), but the full error detail should be logged server-side
for operator diagnostics. Additionally, the reviewer requested that
every HTTP endpoint handler log to an audit trail. Plans should
include an "audit logging" step that defines what is logged, where,
and at what level.

### Query parameter deduplication semantics

The bridge's `_first()` helper silently drops duplicate query
parameters (e.g. `?tag=A&tag=B` keeps only `A`). The reviewer
asked whether this is correct or whether duplicates should be
treated as OR. This is an API design decision that should have been
specified in `DESIGN.md`. Future API design steps should explicitly
document multi-value parameter semantics.

### Search subcommand and name/regex matching

The CLI currently requires the user to know Things entity ids for
the `show` subcommands. The reviewer asked whether ids are meaningful
to users and suggested supporting name or regex matching, or a
`todos search` subcommand. This is a UX design decision for the CLI
that should be addressed in `DESIGN.md`.

### Shared configuration library between services

Both `agent-auth` and `things-bridge` implement similar XDG-based
configuration loading (JSON config file, default directories). The
reviewer suggested extracting a small shared library. This would
reduce duplication as more bridges are added. Track as a future
architecture decision.

### `_safe_id` return type as a distinct type

The `_safe_id` function returns `str | None`, meaning the caller
gets back the same `str` type they passed in and must remember the
value has been validated. A `NewType("SafeId", str)` return would
make the validated-vs-raw distinction visible to type checkers. This
is a specific instance of the semantic types TODO above.

### 404 vs 400 for unparseable path-segment ids

When `_safe_id` rejects an id (control characters, over-length),
the bridge returns 404 rather than 400. This avoids leaking
validation details but is arguably semantically incorrect — the
resource path is syntactically invalid, not merely absent. This
is an API design decision that should be documented in `DESIGN.md`.

### HEAD and OPTIONS implementation

The bridge currently returns 405 for HEAD and OPTIONS. HEAD on
read-only endpoints would be trivial and useful for health checks.
OPTIONS (CORS preflight) may be needed if the bridge is ever
accessed from a browser context. The decision to implement or
explicitly exclude these should be documented in `DESIGN.md`.

### macOS Keychain per-application access control

On macOS, Keychain Access supports per-application ACLs on
individual keychain items. The Python `keyring` library does not
expose this functionality. A reviewer asked whether things-cli
should ensure that its keychain entries are only readable by itself.
This is a security design decision: using the Keychain partitioned
access API (`SecAccessControl`) would prevent other processes
running as the same user from reading the credentials, but requires
either native code (PyObjC) or a custom keyring backend. Document
the decision and trade-offs in `DESIGN.md`.

### Interactive credential input for CLI login

The `things-cli login` command currently accepts `--access-token`
and `--refresh-token` as CLI flags, which exposes them in shell
history. The reviewer asked for interactive input (like `gh auth
login` prompts) or pre-populated config file as alternatives. This
is a UX and security design decision that should be addressed in
`DESIGN.md` and the implementation plan. Plans should include a
"credential input method" step that considers shell history exposure.

### Safe logging with typed argument wrappers

Introduce a safe-logging convention similar to Palantir's
[safe-logging](https://github.com/palantir/safe-logging) library.
Log arguments would be wrapped in `Safe(value)` or `Unsafe(value)`
(or `UnsafeArg` / `SafeArg`) to distinguish values that are safe to
include in log output from values that may contain sensitive data
(tokens, user ids, filesystem paths, AppleScript stderr). The
logging layer would then automatically redact or omit `Unsafe`
arguments when writing to logs that may be exposed (e.g. HTTP
responses, metrics), while including them in operator-only logs.

This is particularly relevant for things-bridge, which already
strips AppleScript stderr from HTTP error responses to avoid leaking
host info — safe-logging would formalise that distinction and make
it harder to accidentally log sensitive data. It also aligns with
the audit-logging TODO: structured audit log entries should tag each
field as safe or unsafe so log aggregation tools can apply
appropriate redaction policies.

Plans should include a "define safe-logging wrappers and apply to
all log call sites" step.

### Functional decomposition must stay implementation-agnostic

PR #9 introduced a `functional_decomposition.yaml` entry that
referenced "via AppleScript" in the Things Bridge description and
"via AppleScript (osascript)" in the Execute External System
Interaction function. These are implementation details — the
functional decomposition should describe *what* capability is
required, not *how* it is implemented. AppleScript could be replaced
by a database query, a REST API, or a different scripting bridge
without changing the function the system needs to perform.

The post-change review checklist should include: "review any updates
to `design/functional_decomposition.yaml` and verify that
descriptions reference only the required function (what), not the
implementation mechanism (how)."
