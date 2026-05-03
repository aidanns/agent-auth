<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0048 — macOS Tart-VM CI lane with sqlite3-direct TCC seed

## Status

Accepted — 2026-05-03.

## Context

Today's `macos-applescript` job in `test-system.yml` runs the
Darwin-gated suite for `things-client-cli-applescript` against a
hosted `macos-14` runner that has neither Things 3 installed nor an
Automation TCC grant. The test file's `@_requires_things3` checks
auto-skip on hosted runners, so no CI surface exercises the
AppleScript CLI against a real, running Things 3 instance.

The next-layer e2e (#567) builds an HTTP path
`agent-auth -> things-bridge -> things-client-cli-applescript -> Things 3` end-to-end inside a macOS guest. Both PRs need a way to
boot a clean macOS guest per relevant PR, install Things 3, and
grant `osascript -> com.culturedcode.ThingsMac` Automation
permission without manual UI interaction. This ADR records the
plumbing that #567 will sit on top of.

`macos-15` (Apple Silicon) GitHub-hosted runners support nested
virtualisation via Apple's Virtualization.framework, which is what
the Tart CLI drives. The cirruslabs `macos-sequoia-base` Tart image
ships with SIP off so `/Library/Application Support/com.apple.TCC/ TCC.db` is writable by `sudo`-elevated callers.

## Considered alternatives

### Option A — pre-baked Tart image with Things 3 + TCC seed

Build a custom Tart image off `macos-sequoia-base` that already has
Homebrew, Things 3, and the TCC grant baked in; publish to GHCR
under our org. Per-PR CI just `tart pull`s the pre-baked image and
runs the smoke test.

**Rejected for now** because:

- Per-PR runtime drops by ~3-4 minutes (no `brew install --cask things` and no TCC seed at boot), but the image-publishing
  pipeline is non-trivial: signed image build, GHCR push, digest
  rotation cadence, image-versioning policy.
- Pre-baked image goes stale against Things 3 cask updates and
  Sequoia minor bumps; the rebuild cadence question itself needs
  triage and ownership.
- This PR's only job is to land the plumbing the e2e in #567 sits
  on. Option A is a per-PR-cost optimisation that's only worth
  paying once we have evidence the install-time cost is recurring
  pain (≥3 install-time flakes/month, or per-PR runtime sustained
  > 20 min).

Tracked as #568 with explicit reactivation criteria so it doesn't
get picked up under normal triage cadence.

### Option B — runtime `tccplus` daemon-restart hack

`tccplus` is a community CLI that wraps `sqlite3` writes against
TCC.db plus a `tccd` reload. Has had Sequoia compatibility issues
and adds a third-party tool to the supply chain that we'd need to
SHA-pin and bump.

**Rejected** because:

- Direct sqlite3 writes plus `launchctl` reload are ~15 lines of
  bash and require no third-party dependency.
- `tccplus`'s daemon-restart sequence is undocumented and varies
  across macOS versions; we'd carry the same Sequoia-version
  ownership cost (next section) plus the upstream-tool cost.

### Option C — label-gated incubation lane

Hide the macOS-Tart job behind a `macos-tart` PR label so it only
runs on opt-in. Defers the runtime cost without buying signal.

**Rejected** because:

- The whole point is to gate the AppleScript CLI's read-side
  contract against a live Things 3 instance. Hiding it behind a
  manual label means most PRs that touch the CLI will skip the
  check, defeating the purpose.
- The path-filter gating in this ADR (only run when one of three
  watched paths changed) gives the same cost-control without the
  human-in-the-loop step.

## Decision

A `macos-15` Tart-VM smoke lane lives in
`.github/workflows/test-system-macos-tart.yml`, gated by a
`decide` job that ORs three new dorny/paths-filter outputs in
`ci.yml`'s `plan` job:

- `things_client_cli_applescript_updated` —
  `packages/things-client-cli-applescript/**`
- `agent_auth_common_updated` — `packages/agent-auth-common/**`
- `macos_tart_plumbing_updated` —
  `.github/workflows/test-system-macos-tart.yml`,
  `scripts/ci/macos-tart/**`

When `decide.outputs.should_run == 'true'`, the `macos-tart-smoke`
job:

1. Installs the Tart CLI from a SHA-pinned release tarball
   (verified against an in-tree `TART_TARBALL_SHA256` constant).
2. `tart pull`s a digest-pinned `cirruslabs/macos-sequoia-base`
   image and clones it to a per-run VM.
3. Boots the VM headless, waits for SSH, rsyncs the workspace in.
4. Runs `scripts/ci/macos-tart/bootstrap.sh` over SSH:
   - Installs Homebrew + `brew install --cask things`.
   - Stops `tccd` in both user and system domains.
   - `INSERT OR REPLACE` into `TCC.db`'s `access` table for
     `kTCCServiceAppleEvents`, client `/usr/bin/osascript`,
     indirect_object `com.culturedcode.ThingsMac`. `csreq` and
     `indirect_object_code_identity` are NULL — the path-based
     `client_type=1` grant does not require them on Sequoia, and
     leaving them NULL keeps the seed forward-compatible across
     Sequoia minor versions whose csreq blob format may drift.
   - Restarts `tccd`.
   - Probes `osascript -e 'tell application "Things3" to count to dos'` to fail fast if the grant didn't take.
   - Installs `uv`, `uv sync --extra dev`.
   - Seeds exactly one to-do via raw `osascript`
     (`make new to do with properties {name:"ci-smoke-todo"}`).
5. Runs the smoke test
   `packages/things-client-cli-applescript/tests/system/test_macos_tart_smoke.py`
   under `AGENT_AUTH_REAL_THINGS3=1`. The test invokes
   `things-client-cli-applescript todos list --status open` and
   asserts exactly the seeded `ci-smoke-todo` comes back through
   the JSON envelope.
6. On `if: always()`, rsyncs the in-VM artefact directory back to
   the runner and uploads the bundle via
   `actions/upload-artifact`. Bundle covers boot-prep stdout/stderr,
   TCC.db dump, pytest log, the `set -x`-traced osascript seed
   call, `system_profiler` / `sw_vers`, and any
   `~/Library/Logs/DiagnosticReports/*.crash` files.
7. Tears down the VM with `tart delete`.

The job ID `test-system-macos-tart` joins
`ci.yml`'s `required-checks-passed.needs:` and the aggregator's
`DIFF_DEPENDENT_JOB_IDS` env list, so the carve-out for label-only
re-runs (#527) extends to the new lane automatically. The
`scripts/ci/diff-dependent-jobs.sh` helper enumerates the new
leaves dynamically via its yq-driven walk; no hand edit required
there.

The smoke test is plumbing only. Full
`agent-auth -> things-bridge -> CLI -> Things 3` e2e is tracked
separately as #567 — it will sit on top of this ADR's boot-prep
without needing a parallel macOS lane.

## Consequences

### Positive

- The `things-client-cli-applescript` CLI now has a CI surface that
  exercises the real osascript -> Things 3 path on every PR that
  touches it (or its `agent-auth-common` Things-models dependency).
  The `@_requires_things3` skip in the existing
  `macos-applescript` job is no longer the only barrier to
  catching a regression in the AppleScript dictionary or runner.
- The plumbing — workflow shape, boot-prep script, TCC seed,
  artefact bundle — is reusable for #567's e2e without needing a
  parallel lane.
- Path-filter gating bounds the cost: PRs that don't touch any
  of the three watched paths skip the macOS lane entirely
  (`decide` job on `ubuntu-latest` is the only thing that runs,
  ~15 seconds).

### Negative

- **TCC.db schema is now an owned dependency scoped to Sequoia
  minor versions.** Apple has historically rearranged the `access`
  table's columns between macOS major versions and occasionally
  between minor versions. When the seed `INSERT` starts failing
  after a runner OS bump, the boot-prep's `tccd` probe will fail
  fast and the artefact bundle's `tcc-access-schema.txt` dump
  will show the new column set. The fix is a one-line update to
  the `INSERT` column list in `scripts/ci/macos-tart/ bootstrap.sh`. See `docs/operations/macos-tart-ci.md` -> "TCC
  schema mismatch on Sequoia minor bump" for the diagnosis recipe.
- Tart base image is **not** in `actions/cache`: the
  `cirruslabs/macos-sequoia-base` image is ~30 GB, well over
  GitHub's 10 GB per-repo cache cap. Each relevant PR pays the
  ~5-min cold pull. Reactivation of Option A is the path to
  removing this cost; reactivation criteria are in #568.
- `brew install --cask things` floats on the upstream Cultured
  Code release channel. Pinning the cask is not viable without
  re-distributing the binary, so a Things 3 update that breaks
  the AppleScript dictionary will surface as a smoke-test failure
  here. The artefact bundle's `bootstrap.log` (with `set -x`
  trace around the seed call) is the diagnosis surface; see
  `docs/operations/macos-tart-ci.md` -> "Things 3 dictionary
  breakage".
- Homebrew install and uv install both use `curl | sh` with
  unverified script bodies. Acceptable here because the install
  runs inside a throwaway VM that holds no secrets; documented
  in the bootstrap script's inline rationale comment so a future
  contributor doesn't unwind the trade-off without context.

### Affected surfaces

- New: `.github/workflows/test-system-macos-tart.yml`,
  `scripts/ci/macos-tart/bootstrap.sh`,
  `packages/things-client-cli-applescript/tests/system/test_macos_tart_smoke.py`,
  `docs/operations/macos-tart-ci.md`.
- Edited: `.github/workflows/ci.yml` (three new path filters,
  three new outputs, convention-doc comment, new
  `test-system-macos-tart` job, aggregator `needs:` and
  `DIFF_DEPENDENT_JOB_IDS` env extended), `pyproject.toml`
  (new `requires_real_things3` pytest marker registration),
  `tests/test_ci_diff_dependent_probe.py` (new job ID added to the
  pinned set + expected-leaves), `design/DESIGN.md` (one-paragraph
  test-tier addition).

## Follow-ups

- #567 — full agent-auth -> things-bridge -> CLI -> Things 3 e2e
  in macOS Tart VM. Uses this ADR's boot-prep as the foundation.
- #568 — pre-baked Tart image with Things 3 + TCC seed (Option A).
  Deferred breadcrumb with reactivation criteria documented in the
  body.
