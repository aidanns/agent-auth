<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0048 — Per-package dependency license allowlist gate

## Status

Accepted — 2026-05-03.

## Context

A Dependabot bump can introduce a transitive dependency under a
copyleft (GPL / LGPL / AGPL) or non-permissive license without any
automated check at PR time. The repository's own license is MIT (per
the SPDX headers and the project LICENSE.md); a copyleft transitive
in the runtime closure of a shipped artefact would create downstream
MIT-compliance friction silently.

The existing `spdx-license-headers.yml` workflow uses `reuse` to
verify every source file in this repo carries an SPDX header, but
that's a check on **our own code**, not a check on the licenses of
**deps we pull in**. The two are complementary; this ADR adds the
deps-side gate.

Tracked as
[#575](https://github.com/aidanns/agent-auth/issues/575). The triage
Agent Brief locked six design points that this ADR records as
authoritative; they are not relitigated during implementation.

## Considered alternatives

### `actions/dependency-review-action` license filter

`actions/dependency-review-action` (already wired via
`check-dependency-review.yml` for vulnerability advisories) accepts
a `licenses` allowlist and a `licenses-deny` block.

**Rejected** because:

- Action runs only on events that carry a base/head diff
  (`pull_request`, `pull_request_target`, `merge_group`); it cannot
  check the resolved closure on `push: branches: [main]` or on a
  `workflow_dispatch` re-run.
- The action consumes whatever the GitHub Dependency Graph
  snapshotted for the head SHA, which lags `uv.lock` by however
  long the dependency-submission POST takes to land. A flagged
  license would manifest as a sticky comment rather than a
  per-package matrix failure.
- Per-package shape is awkward inside a single action invocation —
  the action is a workspace-wide check, not a matrix step.

### `licensecheck`

Heavier, fewer SPDX-expression hooks, and ships its own opinionated
allowlist.

**Rejected** because: the gate's policy is one allowlist constant
(see `scripts/ci/check_license_allowlist.py`); we don't need a tool
that ships its own.

### Whitelist module instead of per-package YAML exceptions

A single `licenses-whitelist.py` (analogous to `vulture-whitelist.py`)
listing every excepted dep.

**Rejected** because: the brief explicitly chose **per-package**
YAML exception files. Per-package keeps the exception scope narrow:
a `things-bridge` exception cannot accidentally cover an
`agent-auth` dep.

### Workspace-wide single check (not per-package)

A single `scripts/check-license-allowlist.sh` invocation that
reports across the whole workspace.

**Rejected** because: the brief chose per-package shape mirroring
`scripts/check-package-coverage.sh` and `.github/workflows/test-unit.yml`.
Per-package fans out across runners (faster wall-clock) and pins
the per-package exception scope.

## Decision

Add a per-package CI gate that enumerates each workspace member's
resolved dependency closure (runtime + dev) and fails the PR if any
dep declares a license outside the permissive allowlist.

The six locked design points:

1. **Allowlist** — `MIT`, `Apache-2.0`, `BSD-2-Clause`,
   `BSD-3-Clause`, `ISC`, `Python-2.0`, `MPL-2.0`.

2. **Reject globs** — `GPL-*`, `LGPL-*`, `AGPL-*`, `SSPL-*`,
   `BUSL-*`, anything custom or unrecognised. The reject globs
   only drive clearer violation messages; the allowlist itself is
   the source of truth (a license that matches neither the
   allowlist nor a reject glob is still a violation).

3. **SPDX disjunction (`A OR B`)** — pick the first allowlisted
   alternative; fail only when no alternative passes. SPDX
   conjunction (`A AND B`) requires every component to be on the
   allowlist (you must comply with all of them).

4. **Dev and runtime parity** — same gate. The brief explicitly
   chose **not** to relax the gate for dev-only deps. A
   GPL-licensed dev tool gets an exception entry with a `reason`
   and `expires`, not a softer allowlist.

5. **Per-package shape** — one matrix job per workspace member
   that ships as a release artefact. The
   `check-license-allowlist.yml` workflow is a `workflow_call`
   child of `ci.yml` mirroring `test-unit.yml`'s shape.

6. **Exception file format** — checked-in
   `packages/<svc>/licenses.exceptions.yml` per package. Each
   entry MUST set `name`, `version`, `license`, `reason`, and
   `expires` (ISO-8601 date). Expired entries fail the gate so
   the operator must either renew (with a fresh reason) or
   remove the dep.

## Implementation outline

- **`scripts/check-license-allowlist.sh`** — per-package driver
  mirroring `scripts/check-package-coverage.sh`'s "list every
  offending package then exit non-zero" shape.
- **`scripts/ci/check_license_allowlist.py`** — Python helper that
  reads PEP 639 `License-Expression` (preferred), legacy
  free-form `License`, and the `License ::` classifier list per
  installed dist via `importlib.metadata`. The bash driver
  invokes it once with `--emit-metadata` to dump every dist's
  metadata, then once per package with `--package <name> --closure <file> --metadata <file>` to evaluate the gate.
- **`.github/workflows/check-license-allowlist.yml`** — new
  `workflow_call` child of `ci.yml`. Per-package matrix mirrors
  `test-unit.yml` (one job per workspace member that ships as a
  release artefact). Each job syncs the workspace venv via
  `uv sync --extra dev` and dispatches the bash driver.
- **`packages/<svc>/licenses.exceptions.yml`** — one file per
  workspace member that ships. Initially carries two entries each
  for `reuse>=6` (workspace dev tool, GPL-3.0-or-later component
  in its conjunction) and `python-debian` (transitive of `reuse`,
  GPL-2.0-or-later). Both are dev-only and never enter the
  runtime closure of any shipped wheel.

## Consequences

- **A Dependabot PR introducing a GPL transitive in the runtime
  closure fails the new check.** The author either swaps the dep
  or hand-authors an exception entry with a justification and an
  expiry. Both paths are reviewable in the PR diff.
- **Per-package matrix fan-out costs ~7 runners per PR,** each
  bootstrapping the workspace venv and running a sub-second
  metadata walk. The per-package shape is favoured over a single
  workspace-wide invocation per the brief.
- **Exception files require maintenance.** An entry's `expires`
  date is a forcing function: the operator either renews the
  reason annually or removes the dep. The current `reuse` /
  `python-debian` entries expire 2027-05-03; on or before that
  date the maintainer either swaps `reuse` for a different SPDX
  verifier, accepts a fresh reason, or removes the deps.
- **Multi-license dists with mixed AND/OR.** SPDX semantics:
  `A OR B` lets the licensee choose either; `A AND B` requires
  compliance with both. The gate matches that — `A OR B` passes
  when either is on the allowlist; `A AND B` passes only when
  both are. A dist declaring
  `Apache-2.0 AND CC0-1.0 AND GPL-3.0-or-later` fails because
  `GPL-3.0-or-later` is rejected.
- **Linux-only marker filtering.** The CI matrix runs on
  `ubuntu-latest` only. Deps gated by Windows or macOS env
  markers (`pywin32-ctypes`, `colorama`) aren't installed in the
  Linux venv and the Python helper silently skips them. If the
  matrix grows a non-Linux runner, expand the metadata-emit step
  per-platform — every platform's metadata dump must feed back
  into the gate independently.
- **Tooling-vs-policy split is unchanged.** The Dependency Review
  Action (`check-dependency-review.yml`) still runs against the
  Dependency Graph diff for vulnerability advisories; the
  license-allowlist gate is a separate, per-package check on the
  resolved closure. The two are complementary, not overlapping.

## Follow-ups

- None planned. The allowlist and reject-glob set are static. A
  future expansion (e.g. relaxing to allow `LGPL-2.1+` for
  dev-only static-analysis deps) would lift the dev/runtime
  parity rule and warrants a fresh ADR.
