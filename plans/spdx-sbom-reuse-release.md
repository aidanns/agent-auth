<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

<!-- REUSE-IgnoreStart -->

# Plan: Release Supply-Chain Artifacts (Release Please + cosign + SPDX SBOM + REUSE)

Issues:
[#106](https://github.com/aidanns/agent-auth/issues/106),
[#110](https://github.com/aidanns/agent-auth/issues/110),
[#111](https://github.com/aidanns/agent-auth/issues/111),
[#115](https://github.com/aidanns/agent-auth/issues/115).

Source standards:
`.claude/instructions/release-and-hygiene.md`,
`.claude/instructions/tooling-and-ci.md`.

## Goal

Ship a CI-driven release pipeline that produces provenance-bearing
artifacts and a machine-readable licensing story, in a single bundle
because the pieces are tightly coupled (SBOM signing requires cosign,
cosign needs an OIDC-enabled publish workflow, REUSE/SPDX headers
round out the SPDX strategy).

Concretely, after this PR:

1. Pushes to `main` open/update a Release Please PR.
2. Merging that PR creates a `vX.Y.Z` tag and a draft GitHub release.
3. A tag-triggered workflow builds the sdist and wheel, generates an
   SPDX SBOM per artifact, signs each artifact and the SBOM with
   keyless cosign (Sigstore OIDC), and attaches all of it — plus
   signature bundles — to the release.
4. Every source file carries an `SPDX-License-Identifier: MIT`
   header (where the file format supports comments). Everything
   that can't carry a header is covered by `REUSE.toml`.
5. `reuse lint` runs on every PR and fails if a header is dropped.

## Non-goals

- SLSA build provenance attestation (#109). Out of scope; add after
  cosign is proven in production.
- PyPI publishing. The GitHub release is the distribution surface
  for now.
- Retiring the local `scripts/release.sh`. It is retained as the
  documented break-glass path. #18 stays open, but the default
  release path flips to the CI flow.
- Tag write-protection for the `v*` namespace (#93).
- Branch protection / required-checks configuration on the Release
  Please PR — this has to be set in the GitHub UI; we document the
  required settings in `CONTRIBUTING.md`.
- Automatic migration of the SPDX/REUSE headers in existing plan
  files and design/decisions ADRs: these will be covered by the
  `reuse annotate` sweep, not hand-edited, so no special handling.

## Deliverables

### REUSE / SPDX (#115)

1. `REUSE.toml` at the repo root declaring default copyright /
   licence plus per-glob overrides for files that cannot carry an
   inline header (binary fixtures, generated diagrams, the
   `LICENSE.md` file itself).
2. `SPDX-FileCopyrightText` / `SPDX-License-Identifier: MIT`
   headers on every text file that supports comments, added
   mechanically with `reuse annotate`.
3. `reuse` added as a dev dependency in `pyproject.toml`.
4. `task reuse-lint` task + `scripts/reuse-lint.sh` wrapper.
5. `.github/workflows/reuse.yml` running `fsfe/reuse-action@v5` on
   push/PR.
6. REUSE badge on `README.md`.

### Release Please (#106)

7. `.github/workflows/release-please.yml` — runs on push to `main`,
   uses `googleapis/release-please-action@v4`, `release-type: simple`
   so the only generated artefact is a CHANGELOG update and a tag.
   Runtime version continues to come from `setuptools-scm`.
8. `.release-please-config.json` and `.release-please-manifest.json`
   at the repo root.
9. Pre-v1.0.0 guardrail: document in `CONTRIBUTING.md` that the
   release PR must be reviewed and merged manually; Release Please
   will batch commits until a human hits merge. No separate manual
   gate in the workflow.

### Tag-triggered publish (#106 + #110 + #111)

10. `.github/workflows/release-publish.yml` — triggered on
    `push: tags: v*`. Jobs:
    - `build`: `uv build` → `dist/*.tar.gz`, `dist/*.whl`.
    - `sbom`: `anchore/sbom-action@v0` produces
      `<artifact>.spdx.json` for each distribution.
    - `sign`: `sigstore/cosign-installer@v3` + `cosign sign-blob --yes --bundle <file>.sig.bundle <file>` for each dist and
      each `*.spdx.json`. Keyless OIDC, no PATs.
    - `upload`: attach artefacts, SBOMs, and `.sig.bundle` files
      to the GitHub release that Release Please drafted.
    - Minimal permissions (`contents: write`, `id-token: write`).

### Documentation

11. ADR `design/decisions/0016-release-supply-chain.md` covering
    the bundled decision (Release Please + cosign + SPDX SBOM +
    REUSE). Records the `release-type: simple` and keyless-cosign
    choices.
12. `SECURITY.md`: new section documenting SBOM location, format,
    signature scheme, and a copy-pasteable verification recipe
    (`cosign verify-blob --bundle ...`).
13. `CONTRIBUTING.md`: replace the current release instructions
    with the Release Please flow; keep `scripts/release.sh` as a
    break-glass subsection.
14. `README.md`: REUSE compliance badge; short note pointing to
    `SECURITY.md` for signature verification.
15. `CHANGELOG.md`: `[Unreleased]` entry summarising the new
    supply-chain artefacts (so the next Release Please PR picks
    them up).

## Design and verification

Per `.claude/instructions/plan-template.md`:

- **Verify implementation against design doc** — mostly not
  applicable. This change is release-infrastructure, not a
  behavioural change to the agent-auth service. No updates to
  `design/DESIGN.md`, `functional_decomposition.yaml`, or
  `product_breakdown.yaml` are required. The ADR captures the
  design rationale.
- **Threat model** — SBOM + signatures *are* part of the supply-
  chain threat model. Add a short subsection to `SECURITY.md` on
  the supply-chain trust boundary (runner identity, OIDC, Sigstore
  transparency log) and the residual risks (compromised GitHub
  runner, compromised Sigstore CA).
- **Architecture Decision Records** — one ADR (0016) for the
  bundled decision; sub-decisions (release-type=simple, keyless
  cosign, SPDX over CycloneDX) are recorded inside it rather than
  spun into separate ADRs.
- **Cybersecurity standard compliance** — the project's declared
  standard is in `design/ASSURANCE.md`; walk relevant supply-chain
  controls once the implementation is in place, and raise issues
  for any gaps (e.g. SLSA still open as #109).
- **QM / SIL compliance** — no production-code change; no
  additional evidence required beyond the ADR and threat-model
  update.

## Implementation steps

1. **REUSE annotation first** — the largest mechanical diff.
   - Install `reuse` via `uv sync --extra dev`.
   - Author a minimal `REUSE.toml` covering
     `LICENSE.md` and any binary assets (`design/*.png`,
     `design/*.svg`, `design/*.csv` if generated, test binary
     fixtures).
   - Run `uv run reuse annotate --copyright "Aidan Nagorcka-Smith <aidanns@gmail.com>" --license MIT --recursive <tree>` on
     `src/`, `tests/`, `scripts/`, `.github/`, and top-level
     text files (`Taskfile.yml`, `pyproject.toml`, `README.md`,
     etc.). Commit a clean tree.
   - Iterate until `uv run reuse lint` passes. Expect to add
     `REUSE.toml` entries for any stragglers `reuse annotate`
     can't handle.
2. **CI REUSE check** — `.github/workflows/reuse.yml` using
   `fsfe/reuse-action@v5`; no Python setup needed inside the
   workflow. Add `task reuse-lint` via `scripts/reuse-lint.sh` so
   the same check runs locally. The script follows the project's
   standard bash header.
3. **Release Please config** — `.release-please-manifest.json`
   seeded with the current `0.1.0` tag; `.release-please-config.json`
   declares `release-type: simple` and `prerelease: false` (we'll
   handle pre-1.0 via reviewer discipline on the PR, not
   workflow-level gates).
4. **Release Please workflow** — minimal workflow calling
   `googleapis/release-please-action@v4` on `push` to `main`;
   outputs `release_created`, `tag_name` for chaining.
5. **Publish workflow** — a single workflow file with jobs
   `build`, `sbom`, `sign`, `upload` (or one job with sequential
   steps; single-job is simpler and enough for the first
   iteration). Must declare `permissions: { contents: write, id-token: write }` at the workflow level and `packages: read`
   as needed.
6. **Documentation** — ADR 0016, SECURITY.md section, CONTRIBUTING
   update, README badge, CHANGELOG `[Unreleased]` entry.
7. **Taskfile wiring** — add `reuse-lint` task. No other
   task changes.
8. **Local verification** — run `uv run reuse lint`,
   `task check`, `task test`, `scripts/verify-standards.sh`,
   `scripts/verify-dependencies.sh`.

## Deterministic regression check

- `reuse lint` on CI fails if a header is dropped. This is the
  #115 acceptance criterion.
- `release-please.yml` is idempotent — we can let it run on merge
  and verify it opens a release PR. Failure mode is visible.
- Publish workflow can only be verified by cutting a real release;
  this is called out as a follow-up in the PR description (cut a
  `v0.1.1` or `v0.2.0-rc.1` release after merge and verify
  artefacts + signatures, then close #106/#110/#111).

## Post-implementation standards review

Per `CLAUDE.md` → *Post-Change Review*:

- [ ] `/simplify` on the diff.
- [ ] Independent code-review subagent; address findings.
- [ ] One subagent reviewing the diff against every file in
  `.claude/instructions/` in sequence; address findings.

Specifically verify:

- **`coding-standards.md`** — new scripts (`reuse-lint.sh`) have
  verb names; no implicit units introduced.
- **`bash.md`** — any new `*.sh` follows the standard header.
- **`service-design.md`** — not applicable (no service changes).
- **`testing-standards.md`** — no new unit tests; `reuse lint`
  and the publish workflow itself are the regression checks.
- **`tooling-and-ci.md`** — every new check script is wired into
  a CI workflow.
- **`release-and-hygiene.md`** — release instructions in
  `CONTRIBUTING.md` updated; SBOM/signature location documented
  in `SECURITY.md`.
- **`python.md`** — no Python-code changes other than a dev-dep
  addition.
- **`design.md`** — ADR 0016 added.

<!-- REUSE-IgnoreEnd -->
