<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# action-mediator — Design Specification

Status: Draft — 2026-11-24.

Requirements, performance targets, and operational scenarios live in
[`action-mediator-requirements.md`](action-mediator-requirements.md).

## 1. Intent

AI agents increasingly need to *change* things: edit wiki pages, send
email, update tickets. Letting them hold write credentials for each
system gives no chance to catch a bad write before it lands, and no
single place to see what agents have changed.

`action-mediator` is a hosted, multi-user service that sits between
agents and external systems. Agents never write directly. They file an
**action** describing the change they want. Business rules decide
whether the action is applied automatically or held for a human, who
can review it, edit it, and approve or reject it. Approved actions are
handed to a **plugin** for the target system, which applies them
deterministically. Every applied action is recorded, and humans can
revert or modify it after the fact.

Both motivations carry equal weight:

1. **Catch bad writes** — a human sees (and can fix) risky actions
   before they reach the external system, and can undo auto-applied
   ones afterwards.
2. **Centralised control and audit** — one place to see, govern, and
   audit what every agent changes across every system.

## 2. Goals, non-goals, anti-goals

### Goals

- Agents submit actions through one API, regardless of target system.
- Ordered, declarative rules decide `allow` / `prompt` / `deny` per
  action, using the action's type, agent, target, and payload.
- Humans review pending actions in a web UI or via integrations (e.g.
  Slack), edit the payload before approval, and approve or reject.
- What is applied is exactly what was approved (same revision, same
  bytes).
- Every applied action can be reviewed later and, where the target
  system allows, reverted or modified through a new, linked action that
  goes through the same rules and review.
- New external systems are added by registering a plugin, with no
  change to the service.
- Full, tamper-evident audit history of every action and decision.

### Non-goals (v1)

- **Executing actions.** The service never calls an external system's
  API; only plugins do.
- **Reading external systems.** The service holds no credentials for
  them and never takes "before" snapshots; reverts rely on
  plugin-supplied inverse actions (§7).
- Multi-tenant hosting (one deployment serves one organisation).
- Multi-step approval workflows beyond "N approvals from group G".
- Atomic multi-action transactions (an agent batch is N independent
  actions).
- Rich-text / WYSIWYG editing — payload editing is schema-driven forms
  plus raw-JSON and text fields.
- Replacing agent-auth. The existing host-local bridges
  (things-bridge, gpg-bridge) are unchanged and unrelated.

### Anti-goals (failure even if it "works")

- **Rubber stamping.** If reviewers approve without being able to see
  what changes (a diff, the rule that held it, the agent's stated
  reason), the service adds friction and no safety.
- **Applied ≠ approved.** Any path where a plugin receives something
  other than the approved revision.
- **Bypassable.** If agents still hold direct write credentials to
  mediated systems, the audit trail is fiction. (Deployment guidance,
  not enforceable by the service — see §13.)
- **Silent irreversibility.** A high-stakes irreversible action (e.g.
  external email) auto-applied without the rules author having
  knowingly chosen that (§7).

## 3. Constraints

- Lives in this monorepo as new packages, following repo standards
  (ADRs, threat model, functional decomposition, product breakdown,
  QM/SIL, testing standards, release model).
- It is the first **hosted, internet-reachable** service in the repo
  and the first with a browser UI and a non-Python toolchain. It cannot
  meet the "no external dependencies for core functionality" convention;
  an ADR must record that exception for these packages (§15).
- Agents run anywhere (developer devcontainers, CI, cloud) and cannot
  receive inbound connections.
- The repo's cybersecurity standard (OWASP ASVS, ADR 0019) and SDLC
  standard (NIST SSDF, ADR 0015) apply.

## 4. Approaches considered

| # | Approach | Trade-off | Outcome |
|---|----------|-----------|---------|
| 1 | Single Python service serving server-rendered UI (htmx) + outbox worker | One deployable, one toolchain; editing UX limited | Rejected |
| 2 | **Python API service + separate React SPA**, Postgres, outbox worker | Rich editing/diff UX; adds a frontend toolchain and a second build | **Chosen** |
| 3 | Built on a workflow engine (e.g. Temporal) | Durable waits/retries for free; heavy infra for what is a simple state machine | Rejected |

Approach 2 was chosen for the reviewer experience: editing structured
payloads, side-by-side diffs, and review queues are central to the
"catch bad writes" goal and benefit from a real client-side app.

Other decisions made during design, with alternatives:

| Decision | Chosen | Rejected alternatives |
|----------|--------|-----------------------|
| Revert model | Plugin returns an **inverse action** on apply; revert = new linked action through the normal pipeline | Service snapshots "before" state (violates "service never touches external systems"); per-plugin revert hook (reverts bypass review and history) |
| Rule expressiveness | **Ordered declarative YAML rules**, first match wins, conditions on type/agent/target/payload | Tier per action type only (cannot express "allow edits to scratch space only"); external policy engine (extra service, harder to audit) — kept as a possible later extension |
| Deployment | **Hosted team service** | Host-local only; private-network only |
| Agent identity | **Service-issued agent credentials, each owned by a human** | Federate with each user's local agent-auth (requires asymmetric token signing — breaking change to agent-auth); central agent-auth (a separate project) |
| Rules storage | **Versioned YAML in the database, edited in the web UI** | Rules in git, deployed as config (stronger review, but slower to change and no in-app editor) |
| Dispatch ordering | **Independent dispatch; plugin preconditions catch races as `conflict`** | Per-target serialised dispatch in approval order (deterministic, but a more complex worker, and one slow action holds up the target) |
| v1 scope | **Service, web UI, fake plugin, one real executor, compose deployment** | Core only; full scope with Slack and production hosting |

## 5. Domain model

| Entity | Key fields | Notes |
|--------|------------|-------|
| **User** | OIDC `sub`, email, display name, groups (from IdP) | Created on first login. |
| **Agent** | id, name, owner (User), allowed action types, labels, credentials (≥1, rotatable), status (active/disabled) | Registered by a user in the UI. |
| **Plugin** | id, kind (`executor` / `integration`), base URL, signing secret, manifest (pinned version), status | Registered by an admin. |
| **ActionType** | name (e.g. `wiki.page.update`), plugin, version, target schema, payload schema, `reversible` flag, display hints | Declared by an executor plugin's manifest. |
| **Action** | id, type, agent, origin (`agent` / `revert` / `modify`), `parent_action_id` (for revert/modify), target, reason (free text from agent), status, current revision, approved revision, created/updated | The unit of mediation. |
| **Revision** | action, number, payload, target, author (agent or user), created_at, content hash | Revision 1 is the agent's request; each human edit adds one. Immutable. |
| **Decision** | action, kind (`rule` / `human`), verdict, rule id + rules-version hash, or approver user, revision number, comment | Every verdict is recorded. |
| **Delivery** | action, revision, idempotency key, attempt count, next attempt at, last error | Outbox row driving webhook delivery. |
| **Result** | action, outcome, external reference (URL/id), human summary, inverse action (type + target + payload, or null) | Reported by the plugin. |
| **RuleSet** | version, YAML source, author, created_at, active flag | Versioned; every Decision references the version used. |
| **AuditEvent** | sequence, timestamp, actor, event kind, subject ids, payload, chain hash | Append-only; see §11. |

**Target** is a structured, plugin-defined identifier for the thing
being changed (e.g. `{"space": "eng", "page_id": "123"}`), validated
against the type's target schema. Rules match on it.
Each action type declares which target fields form its **target key**,
used to group actions on the same thing in the UI (history per target,
"later actions on this target" warnings in §8.3).

## 6. Action lifecycle

```
                     ┌─ allow ─▶ auto_approved ──────────────────────┐
submitted ─▶ [rules] ┼─ prompt ▶ pending_review ─(edits)─▶ approved ─┼─▶ dispatched ─▶ applied
                     └─ deny ──▶ denied           │                  │                ├▶ conflict
                                                  ├─▶ rejected       │                └▶ failed
                                                  ├─▶ cancelled (agent withdraws)
                                                  └─▶ expired (review TTL)
```

- **Terminal states:** `denied`, `rejected`, `cancelled`, `expired`,
  `applied`, `conflict`, `failed`.
- **`conflict`** — the plugin refused because the target no longer
  matches the action's preconditions (e.g. the wiki page changed since
  the agent read it). Humans can file a new action from it ("re-file
  against current state"); the original is not retried.
- **`failed`** — permanent plugin error, or retries exhausted. Admins
  and approvers may **retry** a `failed` action (re-enters
  `dispatched` with the same approved revision and idempotency key).
- **Approval binds to a revision.** `approve` must name the revision
  the reviewer saw; if a newer revision exists the request is rejected
  (409). Once approved, the payload is frozen.
- **Edits** are only allowed in `pending_review`, use optimistic
  concurrency on revision number, and are validated against the
  payload/target schemas. Editing the **target** or **type** is not
  allowed — file a new action instead (keeps rule evaluation honest).
- **Re-evaluation after edit:** when a human edits, rules are
  re-evaluated against the new revision. A `deny` result blocks
  approval with an explanation (prevents editing an action into a
  forbidden shape); `allow`/`prompt` results do not auto-approve —
  the human still approves explicitly.
- **Review TTL:** pending actions expire after a configurable period
  (default 7 days, per-rule override).
- Applied actions are never mutated. Revert and modify create new
  actions linked via `parent_action_id`; the UI shows the chain.

### 6.1 Edits and approvals

- **A new revision resets approvals.** Approvals already recorded
  against an earlier revision no longer count toward `min_approvals`.
- **Editors cannot approve** by default: a user who authored any human
  revision of an action cannot approve it. This is part of the
  configurable approval policy (§9.3).
- **Re-evaluation picks the stricter requirement.** If re-evaluation
  after an edit matches a different `prompt` rule, the action must
  satisfy *both* the original and the new rule's approver group and
  `min_approvals`; the shorter remaining TTL applies. Editing can never
  lower the bar.

### 6.2 Rule and manifest changes in flight

- A decision is made once, under the RuleSet version active at
  submission (and re-evaluation on edit uses the version active at
  edit time). Activating a new RuleSet does not touch pending actions;
  admins can explicitly run "re-evaluate pending actions" against the
  active RuleSet, after a dry-run preview showing each pending action's
  current and new outcome. The admin chooses which actions to
  re-evaluate; the new outcome applies in full (it may auto-approve,
  deny, or change approval requirements). Each re-evaluation is
  audited.
- Each action records the ActionType manifest version it was validated
  against, and the apply webhook carries it as `type_version`. Plugins
  must accept every version still listed in their manifest; a plugin
  that drops a version causes pending actions of that version to fail
  manifest re-sync validation, which the admin must resolve (cancel or
  re-file) before the re-sync is activated.

## 7. Revert and modify

- On `applied`, an executor plugin **must** return an `inverse` for
  every action type declared `reversible: true`: a complete action
  (type, target, payload) that undoes the change, typically carrying
  preconditions so it conflicts if the target has since changed.
  Missing inverse on a reversible type is a contract violation: the
  action is still recorded `applied`, flagged `revert_unavailable`, and
  an alert is raised.
- **Revert** (UI/API, by a user): files a new action with
  `origin: revert`, `parent_action_id` = the original, payload = the
  stored inverse. It goes through rules and review like any action;
  rules may match `origin`.
- **Modify** (UI/API, by a user): opens a new action of the same type
  and target, pre-filled with the applied payload, for the user to
  edit; filed with `origin: modify`.
- Reverts and modifies are themselves revertible (their own inverse).
- Reverting an action whose target has since been changed by a later
  action surfaces as `conflict` via the inverse's preconditions; the
  UI points to the later action(s) on the same target.
- **Irreversible types** (`reversible: false`) are treated like any
  other type: whether they are auto-approved is up to the rules author
  (some irreversible actions are low stakes). The `reversible` flag is
  shown to reviewers and in history, available to rules as
  `reversible`, and the rules validator emits a non-blocking
  notice listing any `allow` rules that cover irreversible types so the
  author makes that choice knowingly.
- The user who files a revert/modify is its author; self-approval
  rules (§9.3) apply to them.
- **Who may file:** any user allowed to see the original action's
  payload (§10.3) may file a revert or modify. Because it still passes
  rules and review, filing is not itself a privileged act.
- **Rule context for user-filed actions:** `agent.*` paths resolve to
  the *parent* action's agent; a new `actor.*` context (`actor.kind` =
  `agent` | `user`, `actor.id`, `actor.groups`) identifies who filed
  it. The agent allowed-types check (§9.2) applies only when
  `actor.kind == agent`.

## 8. Plugins

Two kinds, sharing registration and signing:

- **Executor plugins** apply actions for one or more action types.
- **Integration plugins** receive lifecycle events (e.g. Slack: post a
  review card when an action enters `pending_review`) and may call back
  to approve/reject on behalf of a mapped user.

### 8.1 Registration and manifest

An admin registers a plugin by base URL. The service fetches
`GET {base}/manifest`, which returns the plugin id, kind, contract
version, and (for executors) its action types with target schema,
payload schema (JSON Schema 2020-12), target-key fields, `reversible`
flag, and display hints (field labels, which fields to diff as text,
`x-sensitive` fields to mask). The manifest is pinned; schema changes
require an admin to re-sync, and the new version applies only to
actions submitted afterwards.

Plugin base URLs are admin-controlled and checked against a
configured allowlist of hosts (SSRF control).

### 8.2 Apply webhook (executor)

`POST {base}/apply`, signed (§8.4), body:

```json
{
  "contract_version": 1,
  "action_id": "act_…",
  "revision": 3,
  "idempotency_key": "act_…:3",
  "type": "wiki.page.update",
  "target": { "space": "eng", "page_id": "123" },
  "payload": { "...": "the approved revision, byte-identical" },
  "payload_sha256": "…",
  "callback_url": "https://…/action-mediator/v1/plugin-callbacks/act_…"
}
```

The plugin responds either:

- `200` with a **result** (synchronous), or
- `202` to accept, then later `POST callback_url` (signed) with the
  result. If no callback arrives within a per-type timeout (default
  15 min) the delivery is retried with the same idempotency key.

Result body:

```json
{
  "outcome": "applied | conflict | failed",
  "retryable": false,
  "external_ref": "https://wiki/…/123?version=42",
  "summary": "Updated page 'Runbook' (v41 → v42)",
  "inverse": { "type": "wiki.page.update", "target": {…}, "payload": {…} }
}
```

Plugins **must** be idempotent on `idempotency_key`: a repeated key
returns the original result without re-applying.

### 8.3 Delivery and ordering

- State change to `approved`/`auto_approved` and the Delivery outbox
  row are written in one database transaction; a worker process sends
  webhooks from the outbox.
- Retries use exponential backoff with jitter (initial 30 s, cap 1 h,
  max 10 attempts / 24 h — configurable), on network errors, 5xx, 429,
  and `failed` + `retryable: true`. Then `failed`.
- **No ordering guarantee between actions** (requester decision):
  each approved action is dispatched independently and may be applied
  concurrently with, or out of order relative to, other actions on the
  same target. Races are caught by the plugin's preconditions and
  surface as `conflict`, which is why executor plugins **must** encode
  preconditions (e.g. expected page version) for every type whose
  target can change between request and apply.
- Delivery is at-least-once; plugin idempotency makes the effect
  exactly-once.
- **Manual retry** of a `failed` action is dispatched like any other.
  If later actions changed the target meanwhile, the plugin's
  preconditions turn the retry into `conflict` rather than overwriting
  newer state. The UI warns before retrying when later actions on the
  same target key have applied.
- The worker must be safe to run as multiple replicas (row-level
  locking on outbox claims, e.g. `SELECT … FOR UPDATE SKIP LOCKED`) so
  each delivery is claimed by one replica at a time.

### 8.4 Signing

Both directions use the Standard Webhooks scheme (HMAC-SHA256 over
`id.timestamp.body`, 5-minute tolerance, replay protection on message
id) with a per-plugin secret generated at registration and rotatable
with an overlap window. TLS is required.

### 8.5 Integration events

Integration plugins subscribe to events: `action.submitted`,
`action.pending_review`, `action.approved`, `action.rejected`,
`action.applied`, `action.conflict`, `action.failed`,
`action.expired`. Events carry ids, type, agent, target, reason,
rule decision, and a deep link to the web UI — not full payloads
(sensitive data stays in the service). An integration that needs the
payload fetches it through the API as the mapped user (below), so
normal visibility rules (§10.3) apply. Delivery uses the same outbox
and signing.

An integration may read, **edit**, approve, and reject actions using
its integration credential **plus a user identity** mapped from the
external system (e.g. Slack user id → OIDC user, mapping established
once by the user through the web UI). The service applies all normal
authorisation checks to the mapped user, and edits follow the same
rules as UI edits: optimistic concurrency on revision number, schema
validation, rule re-evaluation, and the approval policy (§6.1, §9.3).
Each revision and decision records which integration it came through.

## 9. Business rules

### 9.1 Format

Ordered list, first match wins, with a mandatory final default.
Example:

```yaml
version: 1
approval_policy:            # global defaults (§9.3); all true if omitted
  block_owner_approval: true
  block_editor_approval: true
rules:
  - id: scratch-space-edits
    match:
      type: wiki.page.update
      target.space: { in: [scratch, sandbox] }
    verdict: allow

  - id: small-wiki-edits-by-docs-bot
    match:
      type: { prefix: "wiki." }
      agent.labels: { contains: docs-bot }
      payload.body: { length_lt: 2000 }
    verdict: allow

  - id: external-email
    match:
      type: email.send
      payload.to: { any_not_suffix: "@example.com" }
    verdict: prompt
    approvers: { group: comms, min_approvals: 1 }
    approval_policy: { block_owner_approval: true }   # per-rule override
    review_ttl: 2d

  - id: no-prod-config
    match:
      type: { prefix: "config." }
      target.env: prod
    verdict: deny
    message: "Agents may not change production config."

default:
  verdict: prompt
  approvers: { group: reviewers }
```

### 9.2 Semantics

- Match keys are field paths into the evaluation context: `type`,
  `reversible`, `origin`, `agent.id`, `agent.owner`, `agent.labels`,
  `target.*`, `payload.*`. All conditions in a `match` must hold.
- Operators (closed set, no code execution): equality, `in`,
  `not_in`, `prefix`, `suffix`, `contains`, `regex` (RE2-compatible,
  anchored), numeric `lt/lte/gt/gte`, `length_lt/length_gt`,
  `exists`, and `any_*` / `all_*` forms over arrays.
- An unknown path evaluates as non-matching, never as an error.
- Verdicts: `allow`, `prompt` (with `approvers` group and
  `min_approvals`, default 1), `deny` (with `message`).
- Before rules run, the agent's **allowed action types** are checked;
  a type outside that list is `denied` without rule evaluation.

### 9.3 Approval authority

- An approver must be in the rule's group (or the `admins` group).
- **Approval policy (restrictive by default, configurable).** Like
  GitHub's "PR authors can't approve their own PR" and "dismiss stale
  approvals on new pushes" settings, these restrictions are on by
  default and can be relaxed:

  | Setting | Default | Effect when `false` |
  |---------|---------|---------------------|
  | `block_owner_approval` | `true` | A user may approve actions from agents they own. |
  | `block_filer_approval` | `true` | A user may approve a revert/modify they filed. |
  | `block_editor_approval` | `true` | A user who edited an action may approve it. |
  | `reset_approvals_on_edit` | `true` | Approvals on earlier revisions still count. |

  The policy is set globally in the RuleSet (`approval_policy:`) and
  may be overridden per rule (e.g. relax it for a low-stakes type,
  tighten it for `email.send`). Every Decision records the effective
  policy. With `min_approvals > 1`, approvals always come from
  distinct users.
- Any approver in the group may reject; one rejection is terminal.

### 9.4 Management

RuleSets are stored in the database as versioned YAML documents, edited
by admins through the UI/API (with validation, a dry-run "which rule
would match these recent actions?" preview, and diff against the
active version). Activating a version is audited. Every Decision
records the rule id and RuleSet version hash.

## 10. Identity and access

### 10.1 Humans

- Login via the organisation's OIDC provider (authorization code +
  PKCE). The API acts as the backend-for-frontend: it holds tokens
  server-side and issues an `HttpOnly`, `Secure`, `SameSite=Lax` session
  cookie; state-changing requests require a CSRF token.
- Roles derive from IdP groups via configuration: `admins` (manage
  plugins, rules, all agents), approver groups (named in rules), and
  `viewers` (read-only). Every authenticated user can register and
  manage their own agents and view actions from their agents.

### 10.2 Agents

- A user registers an agent in the UI, choosing a name, labels, and
  allowed action types (subject to an admin-configured cap per role).
  The service issues a **client id + secret** (shown once).
- Agents exchange credentials for a short-lived bearer token
  (OAuth 2.0 client-credentials grant, 15-minute lifetime) at
  `POST /action-mediator/v1/oauth/token`.
- Owners can rotate secrets (two live secrets during rotation),
  disable, or delete agents. Disabling an agent cancels its pending
  actions.
- When an owner leaves the IdP (deprovisioned), their agents are
  disabled on the next sync (§10.4).

### 10.3 Visibility

- Action **metadata** (type, agent, owner, target, status, rule,
  timestamps) is visible to every authenticated user.
- Full **payloads** (all revisions, diffs, inverse) are visible to: the
  agent's owner, members of any approver group named by the action's
  matched rule(s), the `viewers` group, and `admins`. `x-sensitive`
  fields stay masked for everyone except approvers of that action and
  admins, with an audited "reveal".
- The History screen shows all actions' metadata and expands payloads
  only where the viewer is entitled.

### 10.4 Group freshness and deprovisioning

- Group claims are refreshed from the IdP at least hourly through the
  OIDC refresh token while a session is live; **approve, reject and
  admin actions require groups refreshed within the last hour**, or
  the UI forces re-authentication.
- A failed refresh (user disabled or deleted at the IdP) ends the
  session. A background job re-checks each agent owner's status daily
  using the refresh token stored at their last login. Owners whose
  check fails have their agents disabled. SCIM provisioning is a later
  extension (record in ADR 4).

### 10.5 Secrets at rest

- Agent client secrets: stored only as Argon2id hashes.
- Plugin signing secrets and stored OIDC refresh tokens: encrypted at
  the application level (AES-256-GCM envelope encryption) under a
  master key supplied by the deployment (environment or KMS), never
  stored in the database in plaintext. The master key is rotatable;
  rotation re-wraps data keys.
- The repo's system-keyring pattern does not apply to this hosted
  service (record in ADR 1).

## 11. Audit and history

- Every state transition, edit, decision, delivery attempt, result,
  rule change, plugin change, and credential event writes an
  **AuditEvent** in the same transaction as the change.
- Events follow the shared audit envelope (ADR 0024) and are
  hash-chained (in the spirit of ADR 0028) so tampering is detectable;
  a verification command checks the chain.
- Audit events are also exportable as JSON lines for SIEM ingestion.
- Retention: actions and audit events are kept indefinitely by default;
  a configurable retention period may purge payload bodies (keeping
  metadata and hashes) for actions older than N days.

## 12. API surface

All under `/action-mediator/v1/`, JSON, documented in an OpenAPI spec
(the repo already gates OpenAPI specs).

**Agent-facing** (bearer token):

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/oauth/token` | Exchange client credentials for a token |
| GET | `/action-types` | Discover types (and schemas) this agent may submit |
| POST | `/actions` | Submit an action (`Idempotency-Key` header required) |
| GET | `/actions/{id}` | Status, decision, result (`?wait=N` long-poll up to 60 s for a status change) |
| GET | `/actions?status=&type=` | The agent's own actions |
| POST | `/actions/{id}/cancel` | Withdraw while `pending_review` |

Agents only see their own actions. The response to `POST /actions`
includes the immediate rule outcome (`auto_approved`, `pending_review`,
or `denied` + message) so agents can adapt.

**Human-facing** (session cookie): list/filter/search actions; action
detail with revisions, diffs, decisions, deliveries, and result;
`PATCH /actions/{id}` (new revision); `POST /actions/{id}/approve`
(`{revision}`); `/reject`; `/retry`; `/revert`; `/modify`;
agent management; and admin endpoints for plugins, rules, and role
mapping.

**Plugin-facing**: `POST /plugin-callbacks/{action_id}` (signed);
integration approve/reject endpoints (integration credential + mapped
user).

**Operational**: `GET /action-mediator/health`,
`GET /action-mediator/metrics` (Prometheus), consistent with the other
services.

## 13. Web UI

React + TypeScript SPA, served as static assets by the API on the same
origin (one origin keeps cookie/CSRF handling simple).

Core screens:

- **Review queue** — actions awaiting the current user, with type,
  agent, owner, target, reason, matched rule, age.
- **Action detail** — agent's reason; matched rule and why; target;
  payload as a schema-driven form; **diff** of each revision against
  the agent's original (text diff for fields marked as text, structural
  diff otherwise); after application, the plugin summary and external
  link; revert/modify buttons; the revert/modify chain.
- **Edit** — schema-driven form with validation, plus raw-JSON mode.
- **History** — all actions with filters (system, agent, owner,
  status, date), including auto-approved ones, for after-the-fact
  review.
- **Agents** — register, rotate credentials, set allowed types.
- **Admin** — plugins (register, re-sync manifest, rotate secret),
  rules (edit, dry-run, activate), role mapping, integration identity
  mappings.

Payload content is untrusted agent output: render as text only, never
as HTML; mask `x-sensitive` fields by default.

## 14. Security considerations (threat-model inputs)

A full threat model is required before implementation. Key threats:

| Threat | Mitigation |
|--------|-----------|
| Agent bypasses the service with direct credentials | Out of scope technically; deployment guidance and an audit of credential holders. Documented as residual risk. |
| Stolen agent credentials | Short-lived tokens, rotation, per-agent allowed types, rules, disable switch. |
| Approved content differs from applied | Revision-bound approval, frozen payload, `payload_sha256` in webhook, audit chain. |
| Reviewer approves something different from what they saw (TOCTOU) | Approve names the revision; 409 on mismatch. |
| Editing an action into a forbidden shape | Rule re-evaluation on edit; `deny` blocks approval. |
| Self-approval / collusion | Restrictive approval policy by default (§9.3); relaxations are explicit, per-rule, and audited; distinct approvers for `min_approvals > 1`. |
| XSS via agent payloads | Text-only rendering, CSP, no `dangerouslySetInnerHTML`. |
| Forged webhooks / callbacks | Standard Webhooks HMAC both ways, timestamp tolerance, replay cache. |
| SSRF via plugin URLs | Admin-only registration, host allowlist. |
| Approval fatigue | Diffs, matched-rule display, rule dry-run tooling to tune `allow` rules; review-queue metrics. |
| Sensitive data in payloads | `x-sensitive` masking, payload retention purge, events carry no payloads. |
| Integration spoofing a user | Integration credential plus pre-established user mapping; normal authorisation on the mapped user. |

## 15. Required ADRs

The implementation PRs must add ADRs for:

1. Hosted multi-user service and the dependency exception for the
   action-mediator packages.
2. Python API stack: web framework, Postgres, and migration tooling
   (distinct from agent-auth's SQLite migration system).
3. Frontend toolchain (React/TS, package manager, build, lint, test)
   and its integration with treefmt, lefthook, Dependabot/Renovate, CI,
   and the release model (ADRs 0035, 0044).
4. Identity: OIDC BFF for humans, client-credentials for agents.
5. Plugin contract: manifest, apply/callback, Standard Webhooks
   signing, idempotency.
6. Inverse-action revert model.
7. Rules language and its evaluation semantics.

## 16. Repository impact

- `packages/action-mediator/` — Python API + outbox worker (two entry
  points: `serve`, `worker`), plus CLI subcommands for admin bootstrap
  (e.g. first admin mapping, rules import, audit-chain verify).
- `packages/action-mediator-web/` — React SPA.
- A test-only fake executor plugin (alongside the service's tests, like
  `things_client_fake`) that implements the contract with an in-memory
  store and controllable failures/conflicts.
- **One real executor plugin** (e.g. a wiki), in its own package, to
  prove the contract end to end — including inverse actions and
  preconditions — against a real system. The requester picks the
  target system at implementation kickoff. Slack and other integration
  plugins, further executors, and production hosting
  (infra-as-code, HA) are out of v1 scope.
- A thin Python client library for agents (`action_mediator_client`,
  matching the per-service client pattern of ADR 0030).
- Updates to `design/DESIGN.md`, functional decomposition, product
  breakdown, `ASSURANCE.md`, and `SECURITY.md` / ASVS mapping.
- Container image and a reference deployment (compose file: API,
  worker, Postgres) for local and integration testing.

## 17. Verification

- **End-to-end lifecycle** (against the fake plugin): agent submits →
  auto-allowed → applied → human reverts → revert held for review →
  edited → approved → applied; plus deny, reject, cancel, expire,
  conflict, retry-to-failed, and manual retry.
- **Contract tests** for the plugin protocol, runnable by third-party
  plugin authors against their own plugin.
- **Rules engine:** table-driven tests per operator; property tests
  for first-match semantics; mutation testing (ADR 0021 — security
  critical).
- **State machine:** every legal and illegal transition, with mutation
  testing.
- **Concurrency:** concurrent edit vs approve; duplicate deliveries;
  parallel actions on one target resolving to one `applied` and the
  rest `conflict` via preconditions; multiple worker replicas.
- **Fault injection:** plugin timeouts, 5xx, malformed results, worker
  crash between send and record.
- **UI:** component tests plus browser end-to-end tests for review,
  edit, approve, revert.

## 18. Left to the builder

- Choice of Python web framework, ORM/query layer, and migration tool
  (record in ADR 2).
- Choice of frontend libraries (form generation from JSON Schema, diff
  rendering, routing, state management) and package manager.
- Exact database schema and indexes.
- Pagination, filtering syntax, and error-body shapes (follow the
  repo's existing error-code conventions in `design/error-codes.md`).
- Default numeric values not fixed above (rate limits, page sizes).
- Implementation order and how to slice it into PRs/issues.

## 19. Calls made by the author (not yet confirmed by the requester)

These were decided while writing the spec and should be checked:

- Service name `action-mediator`.
- Editing cannot change an action's type or target.
- Rule re-evaluation on edit; `deny` blocks approval.
- 7-day default review TTL; 15-minute agent token lifetime.
- Integration events carry no payloads.
- New revisions reset approvals by default; re-evaluation after an edit
  takes the stricter requirement (§6.1).
- Pending actions keep their original decision when rules change;
  plugins accept every manifest version they still list (§6.2).
- Any user entitled to see a payload may file a revert/modify;
  `agent.*` resolves to the parent's agent, plus `actor.*` (§7).
- Manual retries of failed actions rely on plugin preconditions to
  avoid overwriting newer state (§8.3).
- Payload visibility rules (§10.3).
- Hourly group refresh, approvals need fresh groups, daily owner
  re-check, SCIM later (§10.4).
- Envelope encryption under a deployment-supplied master key; Argon2id
  agent-secret hashes (§10.5).
