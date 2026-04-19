# ADR 0010 — Three-tier scope model with JIT approval

## Status

Accepted — 2026-04-19.

Backfilled ADR.

## Context

AI agents want access to local applications with varying levels of
sensitivity. Reading the user's inbox is noise — the user doesn't want
a prompt every time. Sending mail or completing a to-do on the user's
behalf is consequential and shouldn't go through without explicit
consent. Permanently removing a capability isn't expressible in a
prompt model — it's a policy decision.

The simplest permission model ("token has scope X → allowed")
collapses these three cases into one, forcing either blanket grant
(and a loud audit trail that catches problems only after the fact) or
blanket prompt (and an alert-fatigued user who clicks "approve" on
autopilot).

## Considered alternatives

### Per-operation policy configuration

Let the user configure policy per-scope in a config file, enumerating
endpoints and their required approval mode.

**Rejected** because:

- Puts policy in a static config file, making "grant this one-off
  for the next 10 minutes" hard to express.
- Doesn't compose well with token modification — changing policy
  then requires restarting the server or reloading config.

### Out-of-band approval (Slack / email)

Send a link to Slack or email for prompt-tier operations.

**Rejected** as a default because the whole point of JIT approval is
the user is physically present at the host. Plugin surface (see
below) lets an operator wire Slack in if they want, without making
it the default.

## Decision

Every scope granted on a token family carries a **tier**:

- **allow** — request executes immediately, logged only.
- **prompt** — request blocks at the `agent-auth/validate` call
  while the configured notification plugin asks the user. On
  approval, the request proceeds; on denial, the bridge returns 403.
- **deny** — request is rejected without prompting.

Tiers are per-family, not per-token: running
`agent-auth token modify <family-id> --set-tier things:write=prompt`
takes effect on the next validate call without reissuing tokens
(see DESIGN.md "Scope modification").

The approval plugin is loaded out of the agent-auth config as a
Python module path (similar to Claude Code hooks). The default
(`Config.notification_plugin = "terminal"`) is an interactive
terminal prompt that displays the request description and waits on
stdin for a yes/no — appropriate for the solo-developer deployment
the project is built around. Operators can swap in a desktop
notification plugin, Touch ID plugin, YubiKey plugin, or custom
script as fits their setup. Plugin loading is `importlib.import_module` inside the
agent-auth server process today — the plugin trust caveat is tracked
as [#6](https://github.com/aidanns/agent-auth/issues/6) for future
migration to out-of-process execution.

Approval grants can be:

- **Once** — only the specific invocation executes.
- **Time-boxed** — all subsequent requests for the same scope within
  a duration pass without re-prompting. Held in memory on the server
  only; lost on restart.

Time-boxed grants do not persist and do not modify the token's
scope tier — they're a UX shortcut, not a policy change.

## Consequences

- Day-to-day reads (things:read, outlook:mail:read) run at `allow`
  with zero interaction, letting agents operate fluidly.
- Writes (things:write, outlook:mail:send) default to `prompt`, so
  the user sees and approves each consequential action with full
  context — the notification plugin shows the `description` the
  bridge forwards along the validate call.
- Operations the user never wants to delegate (e.g.
  outlook:mail:delete) can sit at `deny` and the token simply can't
  be used for them.
- Time-boxed grants give the user a "for the next hour" escape hatch
  when they're driving many small actions, without permanently
  downgrading policy.
- Plugin trust sits inside the server process for now; the plugin
  authors write Python that runs in the same memory as the signing
  key. Mitigated by keeping the default plugin surface small and
  documented, and tracked for out-of-process migration.
- `tests_support.always_approve` and `tests_support.always_deny`
  plugins live under `src/tests_support/` for integration testing
  (see ADR 0004). Not shipped in the `agent-auth` wheel.
