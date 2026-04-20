<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
SPDX-License-Identifier: MIT
-->

<!-- REUSE-IgnoreStart -->

# ADR 0014 — Release supply chain: Release Please + keyless cosign + SPDX SBOM + REUSE

## Status

Accepted — 2026-04-20.

## Context

Until this ADR, `task release` on a developer laptop was the only way
to cut a release. That worked as a floor (the release is scripted
and reproducible) but produced no supply-chain artefacts: no SBOM,
no signature, no attestation, no machine-readable licensing story.
Downstream consumers and compliance frameworks (SLSA, SSDF,
EO 14028) want all of those alongside the release.

The release-artefacts work was broken into four tracking issues —
[#106](https://github.com/aidanns/agent-auth/issues/106) (autorelease
workflow), [#110](https://github.com/aidanns/agent-auth/issues/110)
(cosign signatures),
[#111](https://github.com/aidanns/agent-auth/issues/111) (SPDX SBOM),
and [#115](https://github.com/aidanns/agent-auth/issues/115) (REUSE
per-file licensing). The pieces are tightly coupled: signing needs
the CI publish path, SBOM signing reuses that cosign step, and the
SPDX story spans both the release artefacts and the source tree.
Bundling the decision into one ADR keeps the rationale in one place.

## Considered alternatives

### `semantic-release` instead of Release Please

**Rejected** because:

- Cuts a release on every qualifying merge rather than batching
  changes into a reviewable release PR; the reviewable PR is the
  pre-1.0 guardrail.
- Heavier plugin ecosystem than we need for CHANGELOG + tag
  management.

### CycloneDX instead of SPDX

**Rejected** because:

- SPDX is ISO/IEC 5962:2021 and the identifier standard
  (`SPDX-License-Identifier`) is already in use by REUSE and the
  broader Linux ecosystem.
- CycloneDX is more common for vulnerability-focused tooling, but
  Syft emits both formats, so we can add CycloneDX later without
  churn if a consumer asks.

### Signed cosign keys instead of keyless OIDC

**Rejected** because:

- Long-lived signing keys require rotation, storage, and a recovery
  plan. Sigstore keyless mode ties every signature to the runner's
  ephemeral OIDC identity and the transparency log — no key to
  steal.

### PyPI publish in the same workflow

**Rejected for now** because:

- Adds a trust root (the PyPI API token / trusted publisher
  binding) that is out of scope for this change. GitHub releases
  are the distribution surface pre-1.0.

### Retire `scripts/release.sh` entirely

**Rejected** because:

- The local path is cheap to keep and is the only way to cut a
  release when GitHub Actions is unavailable. It becomes the
  break-glass fallback.

## Decision

Adopt Release Please as the autorelease driver and keyless cosign
as the signing scheme, with SPDX as the SBOM format and REUSE as
the per-file licensing convention.

- **Release Please** (`googleapis/release-please-action@v4`,
  `release-type: simple`) runs on every push to `main`, maintains
  one release PR, and pushes a `vX.Y.Z` tag when the PR is merged.
  `setuptools-scm` remains the runtime version source; Release
  Please only manages the CHANGELOG and the tag.
- **Publish workflow** (`.github/workflows/release-publish.yml`)
  triggers on `push: tags: v*`. It builds the sdist and wheel with
  `uv build`, generates an SPDX JSON SBOM per artefact via Syft
  (`anchore/sbom-action`), signs each artefact and each SBOM with
  `cosign sign-blob --bundle` (keyless, OIDC), and uploads the
  bundle to the release.
- **REUSE 3.3** is adopted across the source tree. Every file
  carries an `SPDX-License-Identifier: MIT` header or is covered by
  `REUSE.toml`; `fsfe/reuse-action@v5` gates PRs.
- **Pre-1.0 guardrail** is reviewer discipline on the release PR —
  no workflow-level manual gate.
- **`scripts/release.sh`** is retained as the documented break-glass
  path.

## Consequences

**Positive**

- Release artefacts now come from an ephemeral GitHub-hosted
  runner with SBOM and transparency-logged signatures; the local
  laptop is no longer in the supply-chain trust path for the
  default release flow.
- `SPDX-License-Identifier` headers give scanners an unambiguous
  licensing answer per file.
- Downstream consumers can verify artefacts with a documented
  `cosign verify-blob` recipe without holding any long-lived
  public key.

**Negative / trade-offs**

- A compromised GitHub-hosted runner could produce a signed
  malicious bundle. Residual risk accepted; Rekor transparency-log
  inclusion is the detection signal.
- Release Please requires a PAT or GitHub App token stored as a
  repository secret (`RELEASE_PLEASE_TOKEN`) because tags created
  with the default `GITHUB_TOKEN` do not fire downstream workflow
  triggers. This adds one long-lived credential to the trust root
  — weaker than the keyless cosign posture elsewhere in this
  pipeline. Rotation burden is on the maintainer; a GitHub App
  installation token is the preferred mitigation if we spin one
  up.
- `release-type: simple` means Release Please will generate its
  own CHANGELOG section on first run, which may not match the
  existing hand-maintained Keep-a-Changelog format perfectly. We
  accept one round of manual clean-up on the first release PR.
- Adding `reuse` as a dev dependency and `fsfe/reuse-action` as a
  required CI check shifts some contribution friction onto new
  contributors; mitigated by `task reuse-lint`.

## Follow-ups

- [#109](https://github.com/aidanns/agent-auth/issues/109) — add
  SLSA build provenance attestation on top of the publish workflow.
- [#93](https://github.com/aidanns/agent-auth/issues/93) —
  write-protect the `v*` tag namespace to CI only.
- [#18](https://github.com/aidanns/agent-auth/issues/18) — decide
  whether to collapse `scripts/release.sh` into a smaller local
  validator once the CI path has produced a few real releases.
- [#127](https://github.com/aidanns/agent-auth/issues/127) — pin
  release-affecting GitHub Actions to commit SHAs.
- [#128](https://github.com/aidanns/agent-auth/issues/128) — migrate
  `release-please-action` from a PAT to a GitHub App installation
  token.

<!-- REUSE-IgnoreEnd -->
