<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# action-mediator — Requirements, Performance Targets, and Scenarios

Status: Draft — 2026-11-24. Companion to
[`action-mediator.md`](action-mediator.md) (the "spec"); section
references like "spec §7" point there.

This document holds the preliminary-design baseline for the service:

1. **Stakeholders** (§1) and **operational scenarios** (§2) — how the
   service is used, including failure and incident cases.
2. **System requirements** (§3) — numbered, verifiable "shall"
   statements traced to scenarios and spec sections.
3. **Capacity assumptions and performance targets** (§4) — the
   numbers the design must meet, with margin.

## Conventions

- **IDs** are stable once published; deleted requirements are marked
  *Withdrawn*, never renumbered.
- **Priority:** **M** = must (v1 cannot ship without it), **S** =
  should (v1 target; may slip with a tracked issue), **C** = could
  (post-v1).
- **Verification method:** **T** test (automated), **D**
  demonstration (scripted manual run), **A** analysis (calculation,
  review of a model or load test result), **I** inspection (review of
  code, config, or documents).
- **Source** lists the spec section(s) and scenario(s) the requirement
  derives from.
- Items marked **[assumption]** are the author's proposals, not yet
  confirmed by the requester.

## 1. Stakeholders

| Stakeholder | Interest | Primary interfaces |
|-------------|----------|--------------------|
| **Agent** (software) | Submit actions, learn outcomes, adapt to denials and conflicts | Agent API, client library |
| **Agent owner** (user) | Register and control their agents; see what they did | Web UI |
| **Reviewer / approver** (user in an approver group) | Review, edit, approve or reject pending actions quickly and safely | Web UI, integrations (e.g. Slack) |
| **Viewer / auditor** | See and verify history of all changes | Web UI, audit export, chain verification |
| **Admin** | Plugins, rules, role mapping, re-evaluation, incident response | Web UI, admin API, admin CLI |
| **Plugin author** | Implement executor/integration plugins against a stable contract | Plugin contract, contract test kit |
| **Operator** | Deploy, monitor, back up, upgrade the service | Container image, config, metrics, health, runbooks |
| **External system owner** (e.g. wiki admin) | Changes to their system are attributable and reversible | Plugin results, external references |

## 2. Operational scenarios

Each scenario names the actors, the trigger, the main flow, and notable
variations. Requirements in §3 trace back to these IDs.

### OS-01 — Onboard an executor plugin

**Actors:** admin, plugin author. **Trigger:** a new external system
(e.g. the wiki) needs mediation.

1. Plugin author deploys the plugin and runs the contract test kit
   against it until it passes.
2. Admin registers the plugin's base URL in the web UI. The service
   checks the URL against the host allowlist, fetches the manifest,
   validates it, and shows the declared action types, schemas, and
   reversibility.
3. Admin confirms; the service generates the signing secret, shown
   once, which the plugin author installs.
4. Admin adds rules for the new types (with a dry run against no
   history yet), then activates them.

*Variations:* manifest invalid → registration refused with errors;
URL not on allowlist → refused; later re-sync with changed schemas →
diff shown, pending actions on dropped versions block activation
(spec §6.2).

### OS-02 — Register an agent

**Actors:** user (agent owner). **Trigger:** a user wants an agent to
write to a mediated system.

1. User logs in via SSO, opens Agents, registers "docs-bot" with labels
   and allowed action types (within the cap for their role).
2. Service shows client id and secret once; user stores them in the
   agent's secret store.
3. Agent exchanges credentials for a 15-minute token and calls
   `GET /action-types` to discover schemas.

*Variations:* user requests a type above their cap → refused; secret
rotation with overlap; user disables the agent.

### OS-03 — Auto-approved action

**Actors:** agent. **Trigger:** agent wants to edit a scratch-space
wiki page.

1. Agent submits `wiki.page.update` with target, payload,
   preconditions (expected page version), reason, and an
   `Idempotency-Key`.
2. Service validates against the schema, checks allowed types,
   evaluates rules → `allow` → `auto_approved`; responds immediately
   with the outcome.
3. Worker dispatches the apply webhook; plugin applies, returns
   `applied` with external ref and inverse.
4. Agent long-polls and sees `applied` with the external ref.

*Variations:* agent retries submission after a timeout with the same
`Idempotency-Key` → same action returned, not a duplicate.

### OS-04 — Held action, reviewed and edited in the web UI

**Actors:** agent, reviewer. **Trigger:** agent wants to send an
external email.

1. Agent submits `email.send`; rules → `prompt` (group `comms`) →
   `pending_review`. Agent receives `pending_review` and long-polls.
2. Integration posts a review card; reviewer opens the deep link.
3. Reviewer sees the agent's reason, the matched rule, the target,
   the payload form, and the irreversible badge. Reviewer fixes a
   sentence — revision 2 — and the diff shows it against revision 1.
4. Rules are re-evaluated against revision 2 (still `prompt`).
5. A second comms member approves revision 2 (the editor is blocked
   from approving by the default policy).
6. Worker dispatches revision 2 exactly; plugin returns `applied`.

*Variations:* reviewer rejects with a comment → agent sees `rejected`
and the comment; two reviewers edit concurrently → second edit gets
409 and reloads; reviewer approves revision 1 after someone saved
revision 2 → 409; edit makes rules `deny` → approval blocked with the
rule's message; no one acts within the TTL → `expired`.

### OS-05 — Review and edit through an integration

**Actors:** reviewer, Slack integration plugin. **Trigger:** action
enters `pending_review`.

1. Service emits `action.pending_review`; the integration posts a
   card with summary and deep link.
2. Reviewer (Slack identity mapped to their SSO user) opens an edit
   dialog; the integration fetches the payload as that user, submits
   the edit, then the reviewer approves (if policy allows) or another
   approver does.

*Variations:* reviewer's Slack account is not mapped → integration
prompts them to link via the web UI; mapped user lacks the approver
group → 403 surfaced in Slack; mapped user's groups are stale →
integration tells them to re-authenticate in the web UI.

### OS-06 — Review history and revert an auto-approved action

**Actors:** reviewer or agent owner. **Trigger:** weekly review of
auto-approved changes finds a bad edit.

1. User filters History by system, agent, and date; opens the action;
   sees the applied payload and external ref.
2. User clicks Revert. Service files a new `revert` action with the
   stored inverse; rules apply (`origin: revert`).
3. It is held or auto-approved per rules; on apply, the page is back
   to its prior content and the chain shows original → revert.

*Variations:* page changed since → revert ends `conflict`, UI links
the later actions on the same target; type is irreversible → Revert
is unavailable, Modify may still be offered; inverse missing
(`revert_unavailable`) → Revert disabled with an explanation.

### OS-07 — Modify an applied action

**Actors:** user. **Trigger:** an applied change needs a correction,
not a full undo.

1. User clicks Modify; a new action of the same type and target is
   pre-filled with the applied payload; user edits and files it.
2. It follows rules and review like any action.

### OS-08 — Race on the same target

**Actors:** two agents, plugin. **Trigger:** two approved actions
edit the same page at about the same time.

1. Both are dispatched independently (no ordering guarantee).
2. The first applies; the second fails its precondition and ends
   `conflict`; its agent sees `conflict` and may re-read and re-submit.

### OS-09 — Plugin outage

**Actors:** worker, plugin, admin. **Trigger:** the wiki plugin is
down for two hours.

1. Deliveries get network errors / 5xx; the worker backs off and
   retries; actions stay `dispatched`.
2. Alerts fire for delivery failure rate and dispatch age.
3. Plugin recovers; retries succeed; idempotency prevents duplicates
   for any delivery that had actually landed.

*Variations:* outage exceeds the retry budget → `failed`; admin or
approver uses Retry after recovery (UI warns if later actions on the
same target have applied).

### OS-10 — Change rules and re-evaluate pending actions

**Actors:** admin. **Trigger:** the team decides to auto-approve
small docs-bot edits.

1. Admin edits the RuleSet, runs a dry run over the last 30 days of
   actions to see which would now be auto-approved, and activates it.
2. Admin opens "re-evaluate pending", sees the current and new outcome
   for each pending action, selects some, and applies; some become
   `auto_approved` and dispatch.

### OS-11 — Compromised or misbehaving agent

**Actors:** agent owner or admin. **Trigger:** an agent starts
submitting unwanted actions.

1. Owner or admin disables the agent: its tokens stop working
   immediately and its pending actions are cancelled.
2. Admin filters History to that agent since a time, reviews applied
   actions, and reverts the bad ones — individually or with a **bulk
   revert** that files one revert per selected action.
3. Owner rotates credentials and re-enables once fixed.

### OS-12 — action-mediator outage

**Actors:** agents, operator. **Trigger:** the service is unavailable
(deploy, crash, database failover).

1. Agents receive connection errors or 503; they retry submission with
   the same `Idempotency-Key` and back off. No action is lost or
   duplicated.
2. On recovery, pending actions, revisions, and undelivered outbox
   rows are intact; the worker resumes deliveries.
3. Agents never fall back to writing to external systems directly.

### OS-13 — User leaves the organisation

**Actors:** IdP admin, service. **Trigger:** a user is disabled in
the IdP.

1. The user's live session ends at the next group refresh (≤ 1 hour).
2. The daily owner check disables the user's agents; their pending
   actions are cancelled.
3. Their past decisions and revisions remain in history, attributed.

### OS-14 — Audit

**Actors:** auditor. **Trigger:** periodic review or incident
investigation.

1. Auditor exports audit events for a period as JSON lines into the
   SIEM.
2. Operator runs the chain-verification command; it reports intact or
   the first broken link.
3. For a given external change, the auditor traces: external ref →
   action → revisions → decisions (rule version or approvers) → agent
   → owner.

### OS-15 — Upgrade and restore

**Actors:** operator. **Trigger:** new release; or database loss.

1. Operator upgrades: database migrations run, API and worker roll
   without losing in-flight deliveries.
2. On database loss, operator restores the latest backup; actions
   dispatched after the backup point are reconciled using plugin
   idempotency (re-delivery returns the original result).

## 3. System requirements

### 3.1 Action submission (agent API)

| ID | Requirement | Pri | Ver | Source |
|----|-------------|-----|-----|--------|
| AM-SUB-01 | The service shall accept an action submission containing type, target, payload, and a free-text reason from an authenticated agent. | M | T | spec §5, §12; OS-03 |
| AM-SUB-02 | The service shall validate the target and payload against the action type's pinned schemas and reject invalid submissions with field-level errors. | M | T | spec §8.1; OS-03 |
| AM-SUB-03 | The service shall require an `Idempotency-Key` on submission and return the original action for a repeated key from the same agent within 24 hours, without creating a duplicate. | M | T | spec §12; OS-03, OS-12 |
| AM-SUB-04 | The service shall deny, without rule evaluation, any submission whose type is not in the agent's allowed action types. | M | T | spec §9.2 |
| AM-SUB-05 | The service shall return the immediate rule outcome (`auto_approved`, `pending_review`, or `denied` with message) in the submission response. | M | T | spec §12; OS-03, OS-04 |
| AM-SUB-06 | The service shall let an agent read the status, decision, and result of its own actions, and wait for a status change by long-poll for up to 60 seconds. | M | T | spec §12; OS-03 |
| AM-SUB-07 | The service shall let an agent cancel its own action while `pending_review`. | S | T | spec §6 |
| AM-SUB-08 | The service shall not reveal any other agent's actions to an agent. | M | T | spec §12 |
| AM-SUB-09 | The service shall expose to each agent the action types (with schemas) it may submit. | M | T | spec §12; OS-02 |

### 3.2 Rules

| ID | Requirement | Pri | Ver | Source |
|----|-------------|-----|-----|--------|
| AM-RUL-01 | The service shall evaluate an ordered RuleSet with first-match-wins semantics and a mandatory default, producing `allow`, `prompt`, or `deny`. | M | T | spec §9 |
| AM-RUL-02 | Rule conditions shall support the closed operator set in spec §9.2 over `type`, `reversible`, `origin`, `agent.*`, `actor.*`, `target.*`, and `payload.*`, with unknown paths evaluating as non-matching. | M | T | spec §7, §9.2 |
| AM-RUL-03 | Rule evaluation shall not execute arbitrary code. | M | I | spec §9.2 |
| AM-RUL-04 | The service shall store RuleSets as versioned documents and record, on every rule decision, the rule id and RuleSet version hash. | M | T | spec §9.4; OS-14 |
| AM-RUL-05 | The service shall validate a RuleSet before activation and report a non-blocking notice listing `allow` rules that cover irreversible types. | M | T | spec §7 |
| AM-RUL-06 | The service shall provide a dry run that shows, for a candidate RuleSet, which rule would match each action in a chosen historical window. | S | T | spec §9.4; OS-10 |
| AM-RUL-07 | The service shall re-evaluate rules against each new revision; a `deny` result shall block approval of that revision. | M | T | spec §6; OS-04 |
| AM-RUL-08 | When re-evaluation after an edit matches a different `prompt` rule, the service shall require both rules' approval requirements, and apply the shorter remaining TTL. | M | T | spec §6.1 |
| AM-RUL-09 | Activating a RuleSet shall not change pending actions; the service shall let an admin preview and apply re-evaluation to a selected set of pending actions, applying the new outcome in full. | M | T | spec §6.2; OS-10 |

### 3.3 Review, edit, and approval

| ID | Requirement | Pri | Ver | Source |
|----|-------------|-----|-----|--------|
| AM-REV-01 | The service shall present each reviewer with a queue of pending actions they are entitled to approve. | M | T | spec §13; OS-04 |
| AM-REV-02 | The action view shall show the agent's reason, matched rule, target, reversibility, current payload, and a diff of each revision against the agent's original. | M | D | spec §13; OS-04 |
| AM-REV-03 | The service shall let authorised users edit the payload of a `pending_review` action, storing each edit as a new immutable revision with its author. | M | T | spec §6; OS-04 |
| AM-REV-04 | Edits shall use optimistic concurrency on revision number and be rejected (409) when stale. | M | T | spec §6; OS-04 |
| AM-REV-05 | Edits shall not change an action's type or target. | M | T | spec §6 |
| AM-REV-06 | Approval shall name a revision; the service shall reject approval of any revision other than the latest (409). | M | T | spec §6; OS-04 |
| AM-REV-07 | An approver shall be a member of the rule's approver group or of `admins`. | M | T | spec §9.3 |
| AM-REV-08 | The service shall enforce the approval policy (`block_owner_approval`, `block_filer_approval`, `block_editor_approval`, `reset_approvals_on_edit`), defaulting each to `true`, configurable globally and per rule, and record the effective policy on each decision. | M | T | spec §9.3 |
| AM-REV-09 | With `min_approvals > 1`, the service shall count only approvals from distinct users. | M | T | spec §9.3 |
| AM-REV-10 | A single rejection by an entitled approver shall be terminal. | M | T | spec §9.3 |
| AM-REV-11 | Pending actions shall expire after the effective review TTL (default 7 days). | M | T | spec §6; OS-04 |
| AM-REV-12 | Once approved, an action's payload shall be immutable. | M | T | spec §6 |

### 3.4 Dispatch and plugins

| ID | Requirement | Pri | Ver | Source |
|----|-------------|-----|-----|--------|
| AM-DSP-01 | The service shall record the transition to `approved`/`auto_approved` and the delivery record atomically. | M | T | spec §8.3; OS-12 |
| AM-DSP-02 | The service shall deliver the approved revision to the executor plugin byte-identical to the approved payload, with its SHA-256, idempotency key, and type version. | M | T | spec §8.2 |
| AM-DSP-03 | The service shall accept synchronous (200) and asynchronous (202 + signed callback) results, and re-deliver with the same idempotency key if no callback arrives within the per-type timeout. | M | T | spec §8.2 |
| AM-DSP-04 | The service shall retry deliveries with exponential backoff and jitter within a configurable budget, then mark the action `failed`. | M | T | spec §8.3; OS-09 |
| AM-DSP-05 | The service shall let an authorised user retry a `failed` action with the same approved revision and idempotency key, warning when later actions on the same target key have applied. | M | T | spec §8.3; OS-09 |
| AM-DSP-06 | The worker shall be safe to run as multiple replicas, with each delivery claimed by one replica at a time. | M | T | spec §8.3 |
| AM-DSP-07 | The service shall sign every outbound webhook and verify every inbound plugin callback using the Standard Webhooks scheme, with timestamp tolerance and replay protection. | M | T | spec §8.4 |
| AM-DSP-08 | The service shall refuse plugin registration for base URLs outside the configured host allowlist. | M | T | spec §8.1; OS-01 |
| AM-DSP-09 | The service shall fetch, validate, and pin plugin manifests, and require admin action to adopt a changed manifest. | M | T | spec §8.1; OS-01 |
| AM-DSP-10 | The service shall emit lifecycle events to subscribed integration plugins without including payloads. | M | T | spec §8.5; OS-05 |
| AM-DSP-11 | The service shall let an integration read, edit, approve, and reject on behalf of a mapped user, applying that user's authorisation and the approval policy, and record the integration on each revision and decision. | M | T | spec §8.5; OS-05 |
| AM-DSP-12 | The service shall provide a contract test kit that a plugin author can run against their plugin. | M | D | spec §17; OS-01 |

### 3.5 History, revert, and modify

| ID | Requirement | Pri | Ver | Source |
|----|-------------|-----|-----|--------|
| AM-HIS-01 | The service shall keep every action, revision, decision, delivery attempt, and result, and present them in a filterable history (system, agent, owner, status, date). | M | T | spec §11, §13; OS-06 |
| AM-HIS-02 | The service shall store the inverse action returned for each applied action. | M | T | spec §7 |
| AM-HIS-03 | For a reversible type applied without an inverse, the service shall mark the action `revert_unavailable` and raise an alert. | M | T | spec §7; OS-06 |
| AM-HIS-04 | The service shall let an entitled user revert an applied action by filing its inverse as a new `revert` action linked to the original, subject to rules and review. | M | T | spec §7; OS-06 |
| AM-HIS-05 | The service shall let an entitled user file a `modify` action pre-filled from an applied action, linked to the original. | M | T | spec §7; OS-07 |
| AM-HIS-06 | The service shall display the chain of linked actions (original, reverts, modifies) and the later actions on the same target key. | S | D | spec §7; OS-06 |
| AM-HIS-07 | The service shall let an admin bulk-revert a selected set of applied actions, filing one revert action per selection. **[assumption]** | S | T | OS-11 |

### 3.6 Identity, access, and visibility

| ID | Requirement | Pri | Ver | Source |
|----|-------------|-----|-----|--------|
| AM-IAM-01 | The service shall authenticate users through the organisation's OIDC provider using authorization code with PKCE, holding tokens server-side. | M | T | spec §10.1 |
| AM-IAM-02 | Browser sessions shall use `HttpOnly`, `Secure`, `SameSite=Lax` cookies, and state-changing requests shall require a CSRF token. | M | T | spec §10.1 |
| AM-IAM-03 | The service shall map IdP groups to `admins`, approver groups, and `viewers` through configuration. | M | T | spec §10.1 |
| AM-IAM-04 | Approve, reject, and admin operations shall require group membership refreshed within the last hour. | M | T | spec §10.4; OS-13 |
| AM-IAM-05 | The service shall disable a user's agents and cancel their pending actions within 24 hours of the user being disabled at the IdP. | M | T | spec §10.4; OS-13 |
| AM-IAM-06 | The service shall issue agent credentials to a registering user, show the secret once, and store only an Argon2id hash. | M | T | spec §10.2, §10.5; OS-02 |
| AM-IAM-07 | Agents shall authenticate with the OAuth 2.0 client-credentials grant, receiving tokens with a 15-minute lifetime. | M | T | spec §10.2 |
| AM-IAM-08 | The service shall support secret rotation with two live secrets, and agent disable, which invalidates the agent's tokens within 60 seconds and cancels its pending actions. | M | T | spec §10.2; OS-11 |
| AM-IAM-09 | The service shall enforce the visibility rules in spec §10.3 on every API, including payload masking of `x-sensitive` fields and audited reveal. | M | T | spec §10.3 |
| AM-IAM-10 | The service shall cap the action types a user may grant to their agents according to their role. | S | T | spec §10.2; OS-02 |

### 3.7 Audit

| ID | Requirement | Pri | Ver | Source |
|----|-------------|-----|-----|--------|
| AM-AUD-01 | Every state change, edit, decision, delivery attempt, result, rule change, plugin change, and credential event shall write an audit event in the same transaction as the change. | M | T | spec §11 |
| AM-AUD-02 | Audit events shall use the shared audit envelope (ADR 0024) and be hash-chained. | M | T | spec §11 |
| AM-AUD-03 | The service shall provide a command that verifies the audit chain and reports the first broken link. | M | T | spec §11; OS-14 |
| AM-AUD-04 | The service shall export audit events for a time range as JSON lines. | M | T | spec §11; OS-14 |
| AM-AUD-05 | For any applied action, the service shall let a user trace external ref → action → revisions → decisions → agent → owner. | M | D | OS-14 |

### 3.8 Security

| ID | Requirement | Pri | Ver | Source |
|----|-------------|-----|-----|--------|
| AM-SEC-01 | The web UI shall render agent-supplied content as text only, never as HTML, under a restrictive Content Security Policy. | M | T, I | spec §13, §14 |
| AM-SEC-02 | Plugin signing secrets and stored OIDC refresh tokens shall be encrypted at rest under a deployment-supplied master key that can be rotated. | M | T, I | spec §10.5 |
| AM-SEC-03 | All external interfaces shall require TLS 1.2 or later. | M | I | spec §8.4 |
| AM-SEC-04 | The service shall rate-limit agent submissions per agent and authentication attempts per client id. **[assumption]** | M | T | spec §14 |
| AM-SEC-05 | The service shall meet OWASP ASVS Level 2 controls applicable to its components. | M | I, A | ADR 0019 |
| AM-SEC-06 | The service shall enforce a configurable maximum payload size (default 1 MiB). **[assumption]** | M | T | §4 |

### 3.9 Operations

| ID | Requirement | Pri | Ver | Source |
|----|-------------|-----|-----|--------|
| AM-OPS-01 | The service shall expose `GET /action-mediator/health` and Prometheus metrics at `GET /action-mediator/metrics`. | M | T | spec §12 |
| AM-OPS-02 | Metrics shall include submission rate by outcome, review queue depth and age, dispatch age, delivery failure rate by plugin, and `revert_unavailable` count. | M | I | OS-09 |
| AM-OPS-03 | The service shall emit OpenTelemetry traces linking submission, decision, and delivery for an action. | S | T | ADR 0017 |
| AM-OPS-04 | Pending actions, revisions, and undelivered outbox rows shall survive process restarts and database failover. | M | T | OS-12 |
| AM-OPS-05 | API and worker shall shut down gracefully, finishing in-flight requests and releasing claimed deliveries. | M | T | ADR 0018; OS-15 |
| AM-OPS-06 | Database migrations shall run forward-only and allow rolling upgrade of API and worker. | M | T, D | OS-15 |
| AM-OPS-07 | The project shall ship a container image and a reference compose deployment (API, worker, Postgres). | M | D | spec §16 |
| AM-OPS-08 | Configuration shall come from one source (file plus environment overrides), validated at startup with a clear error on invalid values. | M | T | service-design standards |
| AM-OPS-09 | The service shall purge payload bodies older than a configured retention period, keeping metadata and hashes. | S | T | spec §11 |

### 3.10 Scope for v1

| ID | Requirement | Pri | Ver | Source |
|----|-------------|-----|-----|--------|
| AM-V1-01 | v1 shall include one real executor plugin, chosen by the requester at implementation kickoff, that returns inverses and uses preconditions. | M | D | spec §16 |
| AM-V1-02 | v1 shall include a test-only fake executor plugin with controllable failures and conflicts. | M | I | spec §16 |
| AM-V1-03 | v1 shall include a Python client library for agents covering submission, idempotent retry, and long-poll. | M | T | spec §16 |

## 4. Capacity assumptions and performance targets

### 4.1 Capacity assumptions **[assumption — all rows]**

These size the design. They are the author's estimates for a single
organisation and must be confirmed. Every design target in §4.2 is set
at **2× these assumptions** for headroom.

| Quantity | Assumed (v1) | Design target (2×) |
|----------|--------------|--------------------|
| Human users | 200 | 400 |
| Active agents | 500 | 1,000 |
| Actions submitted per day | 50,000 | 100,000 |
| Peak submission rate (sustained 5 min) | 25 / s | 50 / s |
| Share of actions held for review | 10% | — |
| Pending actions at any time | 2,000 | 4,000 |
| Concurrent web UI users | 50 | 100 |
| Typical payload size | 10 KiB | — |
| Maximum payload size | 1 MiB | — |
| Rules in the active RuleSet | 200 | 500 |
| Executor and integration plugins | 10 | 20 |
| Hot retention of full payloads | 1 year | — |
| Database size after 1 year | ≈ 250 GiB | ≈ 500 GiB |

Database estimate: 50,000/day × 365 × (10 KiB payload + ~4 KiB
revisions, decisions, audit) ≈ 250 GiB.

### 4.2 Performance targets

Server-side latency, measured at the API, excluding client network,
on the reference deployment (§4.4) at the design-target load.

| ID | Measure | Target | Ver | Source |
|----|---------|--------|-----|--------|
| AM-PRF-01 | Action submission latency (validation + rules + persist) | p95 ≤ 150 ms, p99 ≤ 400 ms | A (load test) | OS-03 |
| AM-PRF-02 | Rule evaluation time for one action against 500 rules | p99 ≤ 10 ms | T (benchmark) | spec §9 |
| AM-PRF-03 | Sustained submission throughput | ≥ 50 / s for 5 min with targets 01 and 04 met | A (load test) | §4.1 |
| AM-PRF-04 | Approval to first delivery attempt | p95 ≤ 5 s, p99 ≤ 15 s | A (load test) | OS-03, OS-04 |
| AM-PRF-05 | Status change to long-poll response | p95 ≤ 1 s | T | OS-03 |
| AM-PRF-06 | Plugin callback handling | p95 ≤ 150 ms | A (load test) | spec §8.2 |
| AM-PRF-07 | Review queue first page load (API) with 4,000 pending | p95 ≤ 500 ms | A (load test) | OS-04 |
| AM-PRF-08 | Action detail with 20 revisions (API) | p95 ≤ 300 ms | A (load test) | OS-04 |
| AM-PRF-09 | Web UI time to interactive for review queue on a broadband connection | ≤ 2 s | A (browser test) | OS-04 |
| AM-PRF-10 | History search over 1 year of actions, filtered by agent and date | p95 ≤ 1 s | A (load test) | OS-06, OS-11 |
| AM-PRF-11 | Audit-chain verification throughput | ≥ 10,000 events / s | T (benchmark) | OS-14 |
| AM-PRF-12 | Agent disable to tokens rejected | ≤ 60 s | T | OS-11 |

### 4.3 Availability and recovery **[assumption]**

| ID | Measure | Target | Ver | Source |
|----|---------|--------|-----|--------|
| AM-AVL-01 | Agent API availability (monthly, excluding announced maintenance) | ≥ 99.5% | A (monitoring) | OS-12 |
| AM-AVL-02 | Recovery point objective (data loss on database failure) | ≤ 5 min | D (restore drill) | OS-15 |
| AM-AVL-03 | Recovery time objective | ≤ 4 h | D (restore drill) | OS-15 |
| AM-AVL-04 | Rolling upgrade with zero failed agent requests (given client retry) | 100% of upgrades | D | OS-15 |

99.5% allows ~3.6 hours of downtime a month. That suits a single-region
deployment with one database primary and managed backups. Agents must
tolerate outages by retrying (OS-12), which is acceptable because
actions are asynchronous anyway.

### 4.4 Reference deployment for measurement **[assumption]**

- API: 2 replicas × 2 vCPU / 4 GiB.
- Worker: 2 replicas × 1 vCPU / 2 GiB.
- Postgres: 4 vCPU / 16 GiB, SSD storage, one primary with a streaming
  replica.
- Plugins: the fake executor, configured to respond in 100 ms.

Targets are re-measured on every release by the benchmark suite
(ADR 0029), and regressions beyond 20% fail CI.

## 5. Open items for the requester

1. Confirm or replace the capacity assumptions in §4.1. They drive
   database sizing, the 2× design targets, and AM-SEC-06.
2. Confirm the availability and recovery targets in §4.3. A higher
   target (e.g. 99.9%) needs multi-zone database failover and changes
   the deployment design.
3. Confirm bulk revert (AM-HIS-07). It was added from the
   compromised-agent scenario (OS-11) and isn't in the spec yet.
