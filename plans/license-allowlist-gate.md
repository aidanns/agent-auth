<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Per-package dependency license allowlist gate

Issue: [#575](https://github.com/aidanns/agent-auth/issues/575).

Source standard: `.claude/instructions/python.md` (Python tooling),
`.claude/instructions/tooling-and-ci.md` (workflow layout, where new
checks live).

## Goal

A per-package CI gate that enumerates each workspace member's
resolved dependency closure (runtime + dev) and fails the PR if any
dep declares a license outside a permissive allowlist. The gate
mirrors the per-package shape of `scripts/check-package-coverage.sh`
and `.github/workflows/test-unit.yml` — one matrix job per
workspace member running in parallel.

The triage Agent Brief on #575 locks in:

- **Allowed:** `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`,
  `ISC`, `Python-2.0`, `MPL-2.0`.
- **Rejected:** `GPL-*`, `LGPL-*`, `AGPL-*`, `SSPL-*`, `BUSL-*`,
  anything custom or unrecognised.
- **SPDX `OR` disjunction:** pick the first allowlisted alternative;
  fail only if no alternative is on the allowlist.
- **Dev and runtime parity:** same gate for both sets.
- **Per-package shape:** matrix job per workspace member.
- **Exception file:** `packages/<svc>/licenses.exceptions.yml`,
  list of `{name, version, license, reason, expires}` entries.
  Mandatory `reason` and `expires`; expired entries fail the gate.

## Non-goals

- License compliance for source-file SPDX headers
  (already covered by `spdx-license-headers.yml` / REUSE).
- Automated remediation (raising a follow-up PR to swap a flagged
  dep) — the gate prints the violation and the operator decides.
- Submodule / vendored-code license auditing — Python dependency
  closure only.
- A workspace-wide single check — explicitly per-package.
- License compliance for the `tool-versions.yml` external binaries
  (shellcheck, shfmt, taplo, etc.) — those don't enter the Python
  closure and have their own provenance trail under
  `setup-toolchain/action.yml`.

## Tooling choice

`pip-licenses>=5.0` driven by Python 3.11+ — the project's pinned
runtime baseline. Reasons:

- **Native SPDX expression handling.** `pip-licenses` reads each
  installed dist's `License` / `License-Expression` metadata
  verbatim, including disjunction strings like
  `Apache-2.0 OR BSD-3-Clause`. Our gate parses that string with
  the same allowlist logic so multi-licensed deps resolve without
  ambiguity.
- **PyPI-only install path.** Drops into the existing per-OS/arch
  venv via `uv tool install pip-licenses` (or `uv pip install`
  into the resolved env per matrix job) without touching
  `tool-versions.yml`.
- **Workspace-aware via `uv export`.** Each matrix job uses
  `uv export --package <pkg>` to enumerate the runtime closure,
  unions with the workspace-root dev closure
  (`uv export --extra dev`), and feeds the (name, version) set
  to a Python helper that reads license metadata from the
  resolved env.

Rejected alternatives:

- `reuse` — covers source-file SPDX headers, not deps.
- `licensecheck` — heavier, fewer SPDX-expression hooks.
- `cyclonedx-py` SBOM diff — useful longer-term but introduces a
  schema-validation layer we don't currently need for a simple
  allowlist gate.

## Deliverables

01. **`scripts/check-license-allowlist.sh`** — new per-package
    driver that iterates `packages/*/`, dispatches to a Python
    helper per package with the allowlist, the package's resolved
    closure (`uv export --package <pkg>`), the workspace dev
    closure (`uv export --extra dev` from root), and the package's
    `licenses.exceptions.yml` (if present). Exits non-zero on the
    first package that fails, but prints every offending package
    (matching `check-package-coverage.sh`'s "list all then fail"
    shape).
02. **`scripts/ci/check_license_allowlist.py`** — Python helper
    invoked per package by the bash driver. Reads the exception
    file, parses `pip-licenses --format=json` output for the
    resolved env, applies the allowlist + disjunction logic +
    exception matching, and emits a clear violation list. Exits
    non-zero if any dep fails.
03. **`packages/<svc>/licenses.exceptions.yml`** — placeholder
    files (one per workspace member) containing an explanatory
    header and an empty `entries: []` list. Documents the format
    so contributors can add entries by example. SPDX header per
    project convention.
04. **`.github/workflows/check-license-allowlist.yml`** — new
    `workflow_call` child of `ci.yml`. Per-package matrix mirrors
    `test-unit.yml` (one job per workspace member). Each job:
    - bootstraps the venv via `setup-toolchain` + `uv sync --extra dev`,
    - installs `pip-licenses` into the resolved env (one-shot, not
      a workspace dev dep — so license-check tooling itself is not
      subject to the gate),
    - runs `scripts/check-license-allowlist.sh <pkg>`.
05. **`ci.yml` wiring** — add `check-license-allowlist` to the
    `jobs:` block (workflow_call child) and append it to the
    `required-checks-passed.needs:` list and the
    `DIFF_DEPENDENT_JOB_IDS` env block.
06. **`tests/test_ci_diff_dependent_probe.py`** — extend the
    golden `expected_leaves` set with the new matrix's seven
    leaves (one per workspace member).
07. **`Taskfile.yml`** — add `task check-license-allowlist` so the
    gate is locally reproducible. Dispatches to
    `scripts/check-license-allowlist.sh`.
08. **`CONTRIBUTING.md`** — new "Dependency license policy"
    section documenting the allowlist, the exception process
    (mandatory `reason` + `expires`, ISO-8601 date format,
    "remove the dep instead" preference), and the multi-license
    disjunction rule.
09. **`design/decisions/0048-dependency-license-allowlist-gate.md`** —
    ADR recording the allowlist, the multi-license disjunction
    policy, the per-package shape, and the dev+runtime parity
    decision.
10. **`design/decisions/README.md`** — append the ADR 0048 index
    entry.
11. **`changelog/@unreleased/pr-<N>-license-allowlist-gate.yml`** —
    hand-authored changelog entry; type is `feature`.
12. **`pyproject.toml`** — no change. `pip-licenses` is installed
    one-shot inside the CI job rather than as a dev extra, so a
    GPL-licensed transitive of `pip-licenses` itself can never
    poison the workspace's own gated set.

## Verification before push

- `bash -n scripts/check-license-allowlist.sh` and `shellcheck` pass.
- `task check-license-allowlist` runs locally end-to-end and
  reports zero violations across all packages (green-on-main
  baseline).
- A targeted manual probe — temporarily edit the allowlist to
  remove `MIT` — should fail the gate and list every MIT-licensed
  dep in each package's closure. Revert before commit.
- `task lint` and `task format -- --check` pass.
- `task test -- --unit` runs `test_ci_diff_dependent_probe.py`
  and the updated golden set matches the new matrix leaves.
- `scripts/verify-standards.sh` passes — the new workflow's
  `name:` field equals its filename minus `.yml`, the matrix
  uses the `name: <job> (<row>)` parens convention.
- ADR + changelog entry + CONTRIBUTING.md update all land in the
  same PR.

## Design and verification notes

- **Threat model.** The gate widens supply-chain coverage: a
  Dependabot-introduced GPL transitive in the runtime closure
  would otherwise ship silently and create downstream MIT-
  compliance friction. The gate runs in CI and consumes only the
  resolved closure from `uv export` — no network calls beyond
  the existing `uv` resolver, so it does not change the trust
  boundary.
- **QM / SIL.** Developer-tooling change with no production
  code-path impact. ASSURANCE.md's QM level requires every
  releasable artefact to have a declared license; this gate is
  the implementation check that enforces it.
- **Cybersecurity standard (NIST SSDF / OWASP ASVS).** Reinforces
  SSDF practice PS.3.2 ("inventory all third-party components")
  and PW.1.1 ("verify the security of acquired components") by
  surfacing license metadata at PR time. Not a blocker for any
  control we already meet.

## Post-implementation standards review

- **`coding-standards.md`** — script function names use verbs
  (`check_license_allowlist`, `parse_disjunction`, `match_exception`).
  License set is a frozenset constant; allowlist policy lives at
  one site (the Python helper) so the bash driver carries no
  duplicate logic.
- **`service-design.md`** — N/A (no new service surface).
- **`tooling-and-ci.md`** — new check is a direct workflow_call
  child of `ci.yml`, alongside `check-security`, per the brief's
  "or a new dedicated workflow if cleaner" carve-out. The matrix
  shape mirrors `test-unit.yml` exactly. Workflow `name:` field
  equals filename minus `.yml`. Required-checks aggregator
  extended in the same PR.
- **`testing-standards.md`** — the gate IS a test of the resolved
  closure. The golden test
  (`test_ci_diff_dependent_probe.py::test_helper_emits_expected_leaf_set`)
  pins the per-package matrix expansion so a new workspace member
  must extend both the matrix and the golden set together.
- **`release-and-hygiene.md`** — changelog entry required because
  the prefix is `feature(ci):` (release-entry-bearing).
- **`design.md`** — new ADR 0048 captures the allowlist rationale
  and the multi-license disjunction policy. README index extended.
