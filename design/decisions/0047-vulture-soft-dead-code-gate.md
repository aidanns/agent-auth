<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0047 — Vulture as a per-package soft dead-code gate

## Status

Accepted — 2026-05-03.

## Context

There was no static check for unused functions, classes, methods,
imports, or variables in the workspace. Dead code accumulates across
refactors and is increasingly expensive to remove later — it confuses
readers, agents, and grep-driven impact analysis.

Tracked as
[#578](https://github.com/aidanns/agent-auth/issues/578). The issue
locked four design points during triage that this ADR records as
authoritative:

1. **Confidence threshold** — `--min-confidence 80`. Conservative
   default with low false-positive rate.
2. **Suppression mechanism** — annotation-driven (`# noqa: F841` at
   the call site). No `vulture-whitelist.py` (or any other workspace-
   wide whitelist module).
3. **Per-package shape** — mirroring `scripts/check-package-coverage.sh`,
   not a single workspace-wide invocation.
4. **Soft-gate posture** — advisory only, indefinitely. Promotion to
   a required check is tracked separately so the noise floor can
   stabilise on real PR data first.

## Considered alternatives

### Whitelist module (`vulture-whitelist.py`)

Vulture's documented mechanism: run `vulture --make-whitelist` to
generate a Python file naming every reported symbol, commit it, and
include it in subsequent runs.

**Rejected** because:

- A whitelist module is a separate file from the call site, so a
  reviewer cannot tell at a glance whether a particular suppression
  is still justified.
- The file is generated, not authored — diffs are noisy and
  attributing the entry to a specific architectural reason becomes a
  git-blame archaeology exercise.
- An inline `# noqa: F841` carries the suppression next to the
  parameter / variable it covers, which is the same locality
  property `# type: ignore[…]` and `# noqa: <ruff-rule>` already
  provide elsewhere in the workspace.

### Hard gate from day one

**Rejected** because: the initial run will surface a long tail of
project-specific false positives (HTTP framework callbacks,
plugin-loader entrypoints, structural reflection patterns) that we
have not enumerated. Failing CI on that tail discourages contribution
without yielding security or correctness signal. The soft-gate
posture lets the noise floor stabilise on real PR data; promotion is
a separate decision driven by that data.

### Workspace-wide single invocation

A single `vulture packages/` call would be simpler.

**Rejected** because: per-package shape mirrors the existing per-
package checks (`check-package-coverage.sh`, `pkg-test.sh`,
`pkg-lint.sh`) and keeps each package's findings attributable in the
output. A single run would also make any future per-package
threshold relaxation harder to add without a refactor.

### Lower confidence threshold (60)

**Rejected** because: at `--min-confidence 60` vulture flags every
HTTP handler method (`do_GET`, `do_POST`, `_handle_*`), every
exception class declared but only raised, and every metrics constant
exported but only consumed by tests. The 60% baseline is overwhelmingly
false positives on this codebase; 80% retains the actionable signal
(unused imports, unused locals, genuinely orphaned helpers) without
the noise.

## Decision

Adopt **vulture v2.16+** as a per-package advisory gate at
`--min-confidence 80`, wired through a new `dead-code` job in
`.github/workflows/check-lint.yml`. The job:

- runs `scripts/check-dead-code.sh`, which iterates `packages/*/src/`
  and invokes vulture per package,
- emits findings to the workflow summary so reviewers see them on
  the PR's Checks tab,
- always exits 0 — a finding never blocks merge.

Suppression is annotation-driven via `# noqa: F841` at the false-
positive site. No workspace-wide whitelist module is committed; no
per-package `[tool.vulture]` block is needed because the script
passes `--min-confidence 80` and the package's `src/` path on the
command line.

## Consequences

- **New advisory signal on every PR.** The workflow summary lists
  unused functions / classes / imports / variables surfaced by
  vulture at confidence ≥ 80%. Reviewers and authors see the list
  but the merge gate does not change.
- **No new mandatory tooling on the host.** Vulture installs through
  the existing per-OS/arch venv (`uv sync --extra dev`), like mypy
  and pyright.
- **Suppression policy is locality-based.** Every false positive is
  marked at its call site with `# noqa: F841` and a short comment
  explaining why the parameter / variable cannot be removed. A
  whitelist file would have hidden the rationale; the inline
  annotation is the rationale.
- **Initial false-positive sweep is small.** Six `BaseHTTPRequestHandler`
  `log_message` overrides, two `log_request` overrides, and one
  `Protocol` parameter were the only structural false positives at
  `--min-confidence 80`. Future structural FP categories are added
  case-by-case as they appear.
- **Promotion to a required check is deferred** to a follow-up issue.
  The plan is not "stay soft forever" — it is "stay soft until the
  noise floor stabilises across enough merges to be confident the
  gate would not regress on legitimate dynamic-dispatch patterns".
- **Mutation-testing interaction is favourable.** Dead code suppresses
  mutation scores (no test ever runs the line, so every mutant on it
  survives). Removing dead code surfaced by vulture incrementally
  cleans up that signal.

## Follow-ups

- [#593](https://github.com/aidanns/agent-auth/issues/593) — promote
  the gate from soft (advisory) to hard (required), once the noise
  floor stabilises.
