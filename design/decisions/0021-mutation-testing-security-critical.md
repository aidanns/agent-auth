<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0021 — Mutation testing on security-critical modules

## Status

Accepted — 2026-04-21.

## Context

`.claude/instructions/testing-standards.md` (§ Coverage — "Mutation
testing on security-critical paths") mandates a mutation-testing tool
on the modules whose correctness is a security property rather than a
functional one. Line and branch coverage (already gated at
`--cov-fail-under=74`) prove that a line executed during a test run,
but not that a test assertion would fail if that line's logic were
wrong. For a token HMAC routine, an encryption call, a scope
resolver, or the token-store access path, "executed" and "tested"
are not the same thing — a mutation that flips `>=` to `>` or omits
an `hmac.compare_digest` call can slip past every existing green
test.

Tracked as [#38](https://github.com/aidanns/agent-auth/issues/38) and
required as a 1.0 blocker under the `1.0/testing-rigour` label.

## Considered alternatives

### cosmic-ray

The other actively maintained Python mutation framework. More
configurable, supports baseline snapshots and custom operators.

**Rejected** because:

- Heavier setup (SQLite-backed session database per run, explicit
  `init`/`baseline`/`exec` orchestration). The incremental value over
  mutmut is small on a five-module target and the operational cost
  lands on every run.
- mutmut's CI/CD stats export (`mutmut export-cicd-stats`) writes a
  stable JSON schema that a 30-line score check can parse; the
  cosmic-ray equivalent would need to consume its SQL schema.
- We are optimising for "one nightly CI job that reports a score
  against a ratcheting floor," not for advanced mutation operators.

### mutpy

**Rejected** because: effectively unmaintained (last release 2019,
no Python 3.12 support).

### Run on every PR rather than nightly

**Rejected** because: a focused mutmut run over five modules with the
scoped runner described below is still tens of minutes of wall time
— unacceptable on every PR. Nightly catches regressions within 24 h
of landing, and `workflow_dispatch` lets a reviewer trigger an
on-demand run when touching a security-critical module.

## Decision

Adopt **mutmut v3.x** as the project's mutation-testing tool, gated
by a nightly CI job (`.github/workflows/mutation.yml`) against a
score floor configured in `pyproject.toml`.

Target five modules that together form the token-lifecycle and
cryptographic/storage trust base:

- `src/agent_auth/tokens.py` — HMAC signing and token parsing.
- `src/agent_auth/crypto.py` — AES-GCM field-level encryption.
- `src/agent_auth/keys.py` — keyring-backed key loading/generation.
- `src/agent_auth/scopes.py` — scope tier resolution and authorisation
  decisions.
- `src/agent_auth/store.py` — token-family persistence and encrypted
  column read paths.

The runner invokes pytest scoped to the unit-test files that directly
exercise those modules (`tests/test_tokens.py`, `tests/test_crypto.py`,
`tests/test_keys.py`, `tests/test_scopes.py`, `tests/test_store.py`)
rather than the full suite, so a single mutant triggers at most one
focused test run.

Score = killed / (killed + survived), ignoring `no_tests`, `skipped`,
`timeout`, and `segfault` mutants. The floor lives in
`[tool.mutation_score]` with a ratcheting-upward-only policy matching
`[tool.pytest.ini_options].addopts --cov-fail-under`; CONTRIBUTING.md
§ "Mutation score" documents the bump procedure.

`scripts/verify-standards.sh` gates the configuration (both
`[tool.mutmut]` in `pyproject.toml` and a scheduled workflow that
runs it) so a rename or accidental deletion of either half fails CI.

## Consequences

- New deterministic gate on assertion strength in the
  token/crypto/scope trust base. A line-coverage regression and an
  assertion-strength regression are now caught by separate signals.
- Nightly runtime cost of ≤ 60 minutes on a single `ubuntu-latest`
  runner (enforced via `timeout-minutes: 60`). The scoped runner keeps
  the growth rate bounded by the size of the five test files rather
  than the whole suite.
- The initial floor is deliberately permissive pending the first CI
  baseline. CONTRIBUTING.md documents the ratchet procedure; leaving
  the floor low indefinitely is a deferred-work signal rather than
  an acceptable resting state.
- A new trust boundary in dev tooling: `mutmut>=3.5` is executed in
  CI. Like other dev tools (mypy, pyright) it inherits the repository's
  Dependency Review PR-time gate and Dependabot alerts coverage for
  its transitive dep closure.
- Mutation testing covers only mutants on the five target paths.
  Extending coverage to the HTTP servers (`server.py`,
  `things_bridge/server.py`) is tracked as follow-up rather than
  blocking 1.0 — the mutation delta there is shaped much more by
  request-handler code than by security primitives.

## Follow-ups

- [#38](https://github.com/aidanns/agent-auth/issues/38) — initial
  landing of mutation testing (this ADR).
- Extend mutmut coverage to the HTTP server validation paths once the
  baseline on the core five modules is stable.
