<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0036 — Workspace dep graph is an explicit allowlist verified in CI

## Status

Accepted — 2026-04-24.

## Context

ADR 0032 (#257) split the repository into a uv workspace of per-service
packages under `packages/*/`. The workspace currently has eight
members: `agent-auth-common` (shared library), `agent-auth`,
`gpg-backend-cli-host`, `gpg-bridge`, `gpg-cli`, `things-bridge`,
`things-cli`, and `things-client-cli-applescript`. Each service
package is meant to lean on `agent-auth-common` for typed HTTP clients
and shared models — nothing else.

Eight packages is enough that cross-package edges are easy to
introduce unintentionally. Three shapes of unintended edge would each
be a regression rather than a refactor:

- **Reverse deps into the library.** `agent-auth-common` picking up
  `agent-auth` (or any service) as a runtime dependency would re-couple
  the common library to the services it was extracted from and defeat
  the whole reason for the split. This can happen via a misguided
  `from agent_auth.config import ...` import landing in
  `agent-auth-common/src/` plus an IDE "add missing dependency"
  autofix.
- **Service-to-service leaks.** `things-cli` picking up `things-bridge`
  as a runtime dep, or `gpg-cli` picking up `gpg-bridge`, would make a
  client pull in its server's dependency closure — exactly the coupling
  #105 wanted to break.
- **CLI-to-service-and-back cycles.** Any edge that creates a cycle in
  the dep graph blocks the per-package release automation that ADR
  0032 named as its load-bearing follow-up.

Issue #274 observes that pyproject.toml review alone has not been
enough to catch these — the graph is a product of the eight files, and
a diff against any one of them doesn't surface the wider shape.

## Considered alternatives

### Rely on code review

Keep the enforcement informal; trust that a reviewer spots an
unintended workspace edge when a `pyproject.toml` diff lands.

**Rejected** because:

- Cross-package review is global: a `pyproject.toml` diff shows one
  file while the invariant lives across eight. Reviewers don't
  reliably hold the whole graph in their head.
- The cost of a missed reverse dep is high — by the time it lands on
  `main` the release-automation layering is already compromised and
  the fix is a breaking change to the consumer graph.
- Automated gates on similarly structural invariants (design artefact
  drift via `scripts/verify-design.sh`, dependency ecosystem coverage
  via `scripts/verify-standards.sh`) are already the project pattern;
  an allowlist check slots into the same shape.

### Derive the allowlist from directory layout

Infer the allowed edges from some convention — e.g. "anything named
`*-cli` may depend on anything named `*-bridge`" — rather than
enumerate them.

**Rejected** because:

- The current graph has no such pattern: every service points at
  `agent-auth-common` and nothing else. A naming-derived rule would
  need to reject edges that happen to match the naming but are not
  actually wanted today.
- Any future edge beyond the shared library needs an ADR anyway (so
  the reasoning is captured). Enumerating the ADR-blessed edges
  directly is both clearer and strictly more restrictive — no surprise
  edges slip through because they accidentally match a pattern.

## Decision

`scripts/verify_workspace_deps.py` parses every
`packages/*/pyproject.toml`, extracts each package's
`[project].dependencies` list, narrows to workspace-member names, and
asserts the resulting edge set matches the allowlist baked into the
script. Both unexpected edges and missing allowlisted edges fail the
check — the allowlist must stay in sync with the pyproject.toml
tree in both directions.

The allowlist today is the seven "service → `agent-auth-common`" edges:

- `agent-auth` → `agent-auth-common`
- `gpg-backend-cli-host` → `agent-auth-common`
- `gpg-bridge` → `agent-auth-common`
- `gpg-cli` → `agent-auth-common`
- `things-bridge` → `agent-auth-common`
- `things-cli` → `agent-auth-common`
- `things-client-cli-applescript` → `agent-auth-common`

Adding a new edge — including a second "service → library" if a
second shared library ever emerges — requires amending this ADR with
the justification and extending `ALLOWED_EDGES` in the script. The
script is wired into `task check` (and therefore `.github/workflows/check.yml`)
so every PR exercises it.

## Consequences

Positive:

- Reverse deps, service-to-service leaks, and accidental closure
  expansions all fail the PR gate rather than landing silently. The
  failure message names the offending edge(s) and the remediation.
- The allowlist lives next to the script and is diff-visible — any
  future intended edge is a three-line change (allowlist + ADR
  entry + the pyproject.toml change) reviewed together.
- The structural invariant is machine-checked, freeing code review
  to focus on the content of a change rather than its packaging-layer
  coupling.

Negative:

- Legitimate architectural changes now carry an ADR-and-allowlist
  update in addition to the pyproject.toml edit. Acceptable: the cost
  is proportional to the decision, and "introduce a new cross-service
  runtime dependency" is genuinely worth writing an ADR for.
- The script enforces `[project].dependencies` only; `[project.optional-dependencies]`
  (extras) is out of scope. Extras are currently empty across the
  workspace (only `agent-auth-common[testing]` uses them, and that
  extra has no workspace deps); revisit if extras grow.

## Follow-ups

- Extend the script to include every `[project.optional-dependencies]`
  group if and when extras start carrying workspace-internal edges —
  currently not worth the code because no extra does.
