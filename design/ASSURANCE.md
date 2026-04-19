# agent-auth Assurance Level

## Level

**QM** — Quality Management, per ISO 9000-style practice.

Declared: 2026-04-19. This is a project-level decision; changing it
requires an ADR under `design/decisions/` that supersedes this file.

## Rationale

agent-auth gates AI-agent access to user-facing host applications
(Things 3 today, more to come). A failure of agent-auth leaks or
denies access to the user's own data via the user's own applications
— it does not cause physical harm, regulated-data exposure beyond the
user's own scope, or financial settlement. The blast radius of a
defect is bounded by what the connected applications themselves
expose.

The project therefore does not warrant a safety-integrity level
(IEC 61508 SIL 1–4 exist for functional safety in E/E/PE systems
where failure causes physical harm) or an automotive-style ASIL
classification. It does warrant disciplined quality management: the
keyring handling, refresh-token reuse detection, and JIT-approval
plumbing all need to be correct or the security posture collapses.

The QM declaration here exists so each implementation plan has a
concrete bar to verify against in the *Verify QM / SIL compliance*
step of `.claude/instructions/plan-template.md`.

## Required activities

Every change that lands on `main` must include, where applicable:

- **Code review** — every change ships via pull request with at least
  one reviewer (self-review + Claude reviewer agents count for this
  solo-developer project; see the PR-review workflow in
  `~/.claude/CLAUDE.md`).
- **Architecture Decision Records** — significant design decisions
  recorded in `design/decisions/` following `TEMPLATE.md`; the ADR
  gate in `scripts/verify-standards.sh` blocks drift.
- **Threat modelling** — security-relevant changes refresh
  `SECURITY.md` before landing (see plan-template.md "Threat
  model").
- **Testing** — new behaviour covered by unit tests that drive the
  public API only; integration tests that cross process boundaries
  use the per-test Docker harness (ADR 0004 / 0005). Coverage and
  mutation thresholds live in `.claude/instructions/testing-standards.md`.
- **CI gating** — `task check`, `task test`, `task verify-standards`, `task verify-function-tests`, and
  `task verify-dependencies` all run on every PR. Gates are
  non-advisory: a red check blocks merge.
- **Audit logging** — every token operation and authorization
  decision inside `agent-auth serve` emits a structured audit log
  line. Changes that add a new token-lifecycle operation also add
  an audit entry.
- **Dependency hygiene** — `pip-audit` runs in CI; Dependabot opens
  grouped minor/patch PRs per ecosystem.
- **Plan for each change** — non-trivial PRs commit a plan under
  `plans/` following `plan-template.md`. Small docs / config fixes
  may skip the plan (see `~/.claude/CLAUDE.md` "Starting
  Implementation Work").

## Required documentation

The following artefacts are kept current as the system evolves:

- `README.md` — scope, install, usage.
- `CONTRIBUTING.md` — dev setup, testing, release, commit signing.
- `SECURITY.md` — threat model, cybersecurity-standard selection.
- `design/DESIGN.md` — system architecture, interfaces, behaviour.
- `design/ASSURANCE.md` — this file.
- `design/decisions/` — ADR per significant decision, indexed by
  `design/decisions/README.md`.
- `design/functional_decomposition.yaml` — functions traceable to
  tests.
- `design/product_breakdown.yaml` — components and deliverables.
- `CHANGELOG.md` — keep-a-changelog entries per release.
- `plans/<feature>.md` — implementation plans for every non-trivial
  change.

## Required evidence

For any given release:

- Green CI on the merge commit (all gates above).
- Test artefacts retained in the CI run (pytest output, coverage
  report).
- ADR index `design/decisions/README.md` lists every file in
  `design/decisions/` (other than `README.md` / `TEMPLATE.md`).
- `scripts/verify-standards.sh` passes, asserting portable project
  standards are met — including the QM/ASSURANCE gate that proves
  this file exists with the required sections.

## Per-change conformance

`.claude/instructions/plan-template.md` mandates a *Verify QM / SIL
compliance* step in every implementation plan. That step walks this
document's Required-activities list against the PR and records any
gaps (or justified skips) in the plan's *Design and verification*
section.

## Changing this declaration

Promoting to SIL 1 or above, or downgrading below QM, is a
significant design decision. It requires:

1. A new ADR under `design/decisions/` superseding this one,
   covering the new level, its rationale, and the migration plan.
2. Updates to the Required-activities / documentation / evidence
   lists to reflect the new level's demands.
3. Updates to `scripts/verify-standards.sh` if the new level
   introduces regression-checkable invariants.
