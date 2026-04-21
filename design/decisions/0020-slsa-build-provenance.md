<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
SPDX-License-Identifier: MIT
-->

<!-- REUSE-IgnoreStart -->

# ADR 0020 — SLSA Build Level 3 provenance via slsa-github-generator

## Status

Accepted — 2026-04-21.

## Context

ADR 0016 established the release supply chain (Release Please, keyless
cosign, SPDX SBOM, REUSE) and explicitly deferred
[SLSA](https://slsa.dev) build provenance to
[#109](https://github.com/aidanns/agent-auth/issues/109). Without
provenance, a verifier can confirm *that* the runner-signed artefact
was produced by our `release-publish.yml` workflow (via cosign), but
cannot independently verify the *build facts* — commit SHA, workflow
ref, invocation metadata — bound to the artefact's digest. SLSA fills
that gap and is a prerequisite for several downstream frameworks
(EO 14028, SSDF PS.3) that consume in-toto attestations directly.

[SLSA v1.0](https://slsa.dev/spec/v1.0/) defines Build Levels 1–3:

- **L1** — provenance exists, no integrity guarantees.
- **L2** — provenance is signed by a hosted builder.
- **L3** — provenance is signed by a hosted builder that runs in
  isolation from the user-controlled workflow, so a compromised step
  in the user workflow cannot forge the attestation. Also requires
  non-falsifiable provenance (in-toto + Sigstore) and a clear
  separation between the builder's identity and the user's identity.

The 1.0 target recorded in #109 is Level 3; 0.x accepts Level 2 as a
floor.

## Considered alternatives

### Roll our own in-toto attestation inside `release-publish.yml`

**Rejected** because:

- A step inside the same job that produced the artefact cannot meet
  SLSA L3's isolation requirement — by definition the runner that
  built the artefact also holds the signing credentials. Best case
  L2.
- Recreates code that `slsa-github-generator` already maintains,
  tests, and publishes signed provenance for.

### GitHub-native artifact attestations (`actions/attest-build-provenance`)

GitHub Actions ships a first-party builder-attestation action that
emits SLSA-format provenance signed by a GitHub-issued trust root.

**Rejected (for now)** because:

- The GitHub-native attestation pipeline is tied to GitHub's trust
  root (Sigstore `githubusercontent` issuer) rather than the public
  Sigstore PKI we already anchor cosign signatures on. Using two
  separate trust roots in one release bundle would fragment the
  verification story.
- `slsa-github-generator` has broader SLSA-ecosystem tooling support
  (`slsa-verifier`, spec compliance tables) and is explicitly the
  reference builder called out by the SLSA spec.
- Re-evaluate once GitHub's builder either anchors on public
  Sigstore or the SLSA ecosystem shifts its recommended default.

### Attest SBOMs as well as artefacts

**Rejected for now** because:

- The SLSA builder attests what was *produced*, not what was
  *described*. SBOMs are metadata about the artefacts and are
  already cosign-signed; layering a second attestation on them adds
  verification complexity for limited value.
- Can be added later by feeding the SBOM hashes into the generator's
  subjects list if a downstream consumer asks for it.

### Keep cosign as the only attestation

**Rejected** because:

- Cosign verifies the signature *on* the artefact but says nothing
  structured about *how it was built*. SLSA provenance is the
  canonical way to publish build facts in a consumer-verifiable
  shape.

## Decision

Adopt `slsa-framework/slsa-github-generator`'s
`generator_generic_slsa3.yml` reusable workflow and target **SLSA
v1.0 Build Level 3**.

- The generator runs as a separate `provenance` job in
  `release-publish.yml`, sequenced after `publish` via
  `needs: [publish]`. GitHub schedules the reusable workflow on its
  own SLSA-generator runner, which is isolated from the `publish`
  runner and holds its own ephemeral OIDC identity — this is what
  earns Level 3 over Level 2.
- The `publish` job outputs a base64-encoded `sha256sum(basename)`
  list for the sdist + wheel via
  `outputs.hashes`; the generator consumes it as `base64-subjects`
  and binds each artefact's digest to the workflow run in the
  emitted `multiple.intoto.jsonl`.
- `upload-assets: true` attaches the provenance to the GitHub release
  alongside the cosign-signed sdist, wheel, SBOMs, and their
  signature bundles.
- Verification uses
  [`slsa-verifier verify-artifact`](https://github.com/slsa-framework/slsa-verifier)
  with `--source-uri` + `--source-tag` pinned to this repo's tag —
  recipe in `SECURITY.md` § *Supply-chain artifacts*.
- SBOMs are **not** attested in provenance; they stay cosign-signed
  only. Revisit if a consumer asks for SBOM attestations.

## Consequences

**Positive**

- Independent build-facts attestation: a verifier can confirm the
  sdist/wheel were produced by `aidanns/agent-auth`'s
  `release-publish.yml` at a specific tag, on an isolated
  GitHub-hosted runner, without trusting any key we control.
- Meets the 1.0 SLSA target now, not later — no carry-over debt for
  the 1.0 graduation.
- `slsa-verifier verify-artifact` is a one-command check; downstream
  policies (Kyverno, admission controllers, `pip install`
  gating) can adopt it without bespoke tooling.

**Negative / trade-offs**

- The `provenance` job adds ~30–60 s of extra wall time per release.
  The release path is not latency-sensitive, so this is acceptable.
- The reusable workflow ref **cannot** be SHA-pinned; it must be
  referenced by semantic-version tag (the generator introspects its
  own ref to certify builder identity in the emitted attestation).
  This is an explicit exception to the SHA-pin policy in
  `.claude/instructions/tooling-and-ci.md`, documented at the
  call-site and in the policy text.
- Trust surface expands to include the generator's own signing
  infrastructure. That is the same Sigstore (Fulcio/Rekor) trust
  root we already rely on for cosign, so no new PKI — but a
  compromise of the generator's runner would still forge
  provenance. Residual risk accepted; Rekor transparency-log
  inclusion is the detection signal, mirroring the cosign story.
- Tag-pinned ref means we depend on `slsa-github-generator`
  maintainers not re-pointing the `v2.1.0` tag. The SLSA project
  treats these as immutable releases; Dependabot will open a PR on
  every future major/minor bump.

## Follow-ups

- [#128](https://github.com/aidanns/agent-auth/issues/128) — replace
  the PAT used by Release Please with a GitHub App installation
  token to shrink the remaining long-lived credential surface.
- Revisit GitHub's native `actions/attest-build-provenance` as an
  alternative once its trust root aligns with public Sigstore, or
  the SLSA spec shifts its recommended default builder.

<!-- REUSE-IgnoreEnd -->
