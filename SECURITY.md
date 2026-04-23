<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Security

## Trust boundaries

agent-auth is a **local, single-user** authorization system. All components
bind to `127.0.0.1` by default; they are not designed for multi-tenant or
network-exposed deployment.

```
┌──────────────────────┐            ┌─────────────────────────────────────────────┐
│  Devcontainer        │            │  Host machine                               │
│                      │            │                                             │
│  things-cli ──────HTTP────────────▶  things-bridge ──────────────▶ Things 3     │
│              │       │            │    │                                        │
│              │       │            │    │ HTTP (validate, approve)               │
│              │       │            │    ▼                                        │
│              └────HTTP────────────▶  agent-auth                                  │
│                      │            │    ├─ tokens.db (SQLite + AES-256-GCM)      │
│                      │            │    └─ signing key (system keyring)          │
└──────────────────────┘            └─────────────────────────────────────────────┘
```

Trust boundary decisions:

- **agent-auth** is the trust root. Only it holds the signing key and token
  store. All other components validate tokens by calling agent-auth's HTTP API;
  they never access the store or key directly.
- **things-bridge** trusts agent-auth's validation response and the configured
  Things-client CLI's stdout. It does not trust the bearer token it receives
  from things-cli — it always re-validates with agent-auth before acting.
- **things-cli** trusts agent-auth for token issuance and refresh, and
  things-bridge for data responses.
- **things-client-cli-applescript** runs on the host with the user's macOS
  Automation permission. It receives argv from things-bridge and emits JSON on
  stdout; its only trust assumption is that the invoking process (things-bridge)
  is legitimate. No authentication between bridge and client CLI.
- **Notification plugin** (JIT approval): currently loaded in-process in the
  agent-auth server via `importlib.import_module`, which means a malicious
  plugin would run inside the process that holds the signing and encryption keys.
  Migration to an out-of-process plugin boundary is tracked in
  [#6](https://github.com/aidanns/agent-auth/issues/6).

## Token management endpoints

The management endpoints (`POST /agent-auth/v1/token/create`,
`GET /agent-auth/v1/token/list`, `POST /agent-auth/v1/token/modify`,
`POST /agent-auth/v1/token/revoke`, `POST /agent-auth/v1/token/rotate`) require
`Authorization: Bearer <token>` where the token's family carries
`agent-auth:manage=allow` in its scopes.

On first startup the server creates this management token family directly via
the store and stores the refresh token in the OS keyring. Operators retrieve
it with `agent-auth management-token show` and exchange it for an access
token via `POST /agent-auth/v1/token/refresh`. External clients must refresh
before each management session (access tokens expire after 900 s by default).

The `agent-auth:manage` scope is reserved. The management token family is
excluded from `GET /agent-auth/v1/token/list` responses. If the management family is rotated
or revoked, the server recreates it automatically on the next restart. See
[ADR 0014](design/decisions/0014-management-endpoint-auth.md) for the full
rationale.

## Threat model

Each threat is assessed using a qualitative risk matrix following
**NIST SP 800-30 Rev 1** guidance. **Impact** and **Likelihood** are each rated
High, Medium, or Low independently; the overall **Rating** is their product
(High × Low = Medium, High × Medium = High, etc.). Each mitigation notes whether
it targets Impact, Likelihood, or both, and links to the implementing function in
the [functional decomposition](design/functional_decomposition.yaml) or to the
tracking issue.

The STRIDE tables below capture per-asset threats at the implementation
level. [`design/SELF_ASSESSMENT.md`](design/SELF_ASSESSMENT.md) is the
companion document and rolls the overall system security posture up to
the [CNCF TAG-Security self-assessment
template](https://tag-security.cncf.io/community/assessments/guide/self-assessment/)
structure — actors, actions, goals / non-goals, compliance standards,
development pipeline, and incident-response posture. Use it as the
starting point for an external review; drill into this threat model for
per-asset detail.

### Spoofing

| Threat                                                             | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------ | ------ | ---------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Forged token presented to agent-auth `/validate`                   | High   | Low        | Medium | HMAC-SHA256 signature over `prefix + token-id` prevents forgery without the signing key. Targets: **likelihood**. Implemented: [Verify Token Signature](design/functional_decomposition.yaml#L24), [Load Signing Key](design/functional_decomposition.yaml#L51) |
| Cross-type token substitution (access token used as refresh token) | Medium | Low        | Low    | The token prefix (`aa_` vs `rt_`) is included in the HMAC input; a valid access-token signature does not verify for the refresh-token type. Targets: **likelihood**. Implemented: [Verify Token Signature](design/functional_decomposition.yaml#L24)            |
| Rogue process binding to 127.0.0.1:9100 before agent-auth          | High   | Low        | Medium | Mitigated by user being the sole operator of the host machine. No cryptographic protection against a co-located rogue process winning the bind race. Targets: **neither** (accepted risk for a local-only single-user deployment).                              |

### Tampering

| Threat                                               | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------------- | ------ | ---------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Direct modification of `tokens.db`                   | High   | Low        | Medium | Scope and HMAC-signature fields are AES-256-GCM encrypted at rest; modification without the key produces authentication-tag failures on read. Targets: **impact** (modification detected, scopes unreadable). Implemented: [Encrypt Field](design/functional_decomposition.yaml#L69), [Decrypt Field](design/functional_decomposition.yaml#L72), [Query Tokens](design/functional_decomposition.yaml#L67)            |
| Replay of a revoked token                            | High   | Low        | Medium | Revocation writes `revoked_at` to the token record; validation checks `revoked_at IS NULL` before accepting. Reuse of a refresh token triggers family-wide revocation. Targets: **likelihood**. Implemented: [Mark Family Revoked](design/functional_decomposition.yaml#L65), [Detect Refresh Token Reuse](design/functional_decomposition.yaml#L19), [Check Token Expiry](design/functional_decomposition.yaml#L26) |
| Tampering with the signing key in the system keyring | High   | Low        | Medium | Requires OS-level access to the keyring (macOS Keychain or libsecret). If the key is replaced, all previously issued tokens become invalid on next validation. Targets: **likelihood** (OS keyring restricts access). Implemented: [Load Signing Key](design/functional_decomposition.yaml#L51), [Generate Signing Key](design/functional_decomposition.yaml#L49)                                                    |

### Repudiation

| Threat                                         | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                                                                                |
| ---------------------------------------------- | ------ | ---------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent denies performing a privileged operation | Medium | Low        | Low    | All token operations and authorization decisions are written to agent-auth's audit log before the response is sent. Targets: **likelihood** (comprehensive logging). Implemented: [Log Token Operation](design/functional_decomposition.yaml#L89), [Log Authorization Decision](design/functional_decomposition.yaml#L91) |
| Audit log tampered post-hoc                    | High   | Low        | Medium | agent-auth's audit log is append-only in the current implementation. Targets: **likelihood** (append-only reduces accidental or casual tampering). Cryptographic chaining is tracked in [#103](https://github.com/aidanns/agent-auth/issues/103).                                                                         |

### Information disclosure

| Threat                                  | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                                                                                      |
| --------------------------------------- | ------ | ---------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Token scopes exposed via database read  | Medium | Low        | Low    | Scope fields are AES-256-GCM encrypted at rest; plaintext is only available in-process after decryption. Targets: **impact** (data unreadable without key). Implemented: [Encrypt Field](design/functional_decomposition.yaml#L69), [Query Tokens](design/functional_decomposition.yaml#L67)                                    |
| HMAC signing key extracted from keyring | High   | Low        | Medium | The key is held in the OS keyring (Keychain on macOS, libsecret on Linux). No in-memory caching beyond the process lifetime. Targets: **likelihood** (OS keyring restricts access). Implemented: [Load Signing Key](design/functional_decomposition.yaml#L51), [Generate Signing Key](design/functional_decomposition.yaml#L49) |
| Token value logged in plaintext         | High   | Low        | Low    | Tokens are never written to logs. Audit records reference token family IDs only. Targets: **likelihood**. Implemented: [Log Token Operation](design/functional_decomposition.yaml#L89), [Log Authorization Decision](design/functional_decomposition.yaml#L91)                                                                  |

### Denial of service

| Threat                                       | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| -------------------------------------------- | ------ | ---------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Oversized request body exhausting agent-auth | Low    | Medium     | Low    | Request bodies are capped at 1 MiB. Targets: **likelihood** (attacker cannot send arbitrarily large payloads). Implemented: [Serve Validate Endpoint](design/functional_decomposition.yaml#L76)                                                                                                                                                                                                                                                                                       |
| Rapid token-creation filling `tokens.db`     | Low    | Low        | Low    | Per-token-family in-memory token-bucket on every authenticated endpoint (`rate_limit_per_minute` in `Config`, default 600/min). An exhausted bucket returns `429 rate_limited` with `Retry-After`. Targets: **likelihood** (caps the attacker's issuance rate). Rationale: [ADR 0027](design/decisions/0027-rate-limiting-implementation.md); supersedes [ADR 0022](design/decisions/0022-rate-limiting-posture.md). Closes [#102](https://github.com/aidanns/agent-auth/issues/102). |

### Elevation of privilege

Scope tiers define what approval a request requires: `allow` = immediately
permitted if the token holds the scope; `prompt` = the operation is held pending
real-time human approval via the JIT notification flow even if the token holds
the scope. An AI agent cannot self-approve a `prompt`-tier request regardless of
what scopes its token carries; a human must respond to the notification to
unblock the operation.

| Threat                                                                 | Impact | Likelihood | Rating | Mitigation                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ---------------------------------------------------------------------- | ------ | ---------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AI agent invokes a `prompt`-tier scope without triggering JIT approval | High   | Low        | Medium | Scope tier is resolved server-side on every validation call; the agent cannot bypass the approval flow by presenting a token that holds the scope. Targets: **likelihood**. Implemented: [Check Scope Authorization](design/functional_decomposition.yaml#L28), [Resolve Access Tier](design/functional_decomposition.yaml#L30), [Request Approval](design/functional_decomposition.yaml#L35)                                    |
| Malicious notification plugin runs in-process                          | High   | Low        | Medium | Plugin runs inside the agent-auth process that holds signing and encryption keys. Targets: **likelihood** (partial: user controls which plugin is installed). Current mitigation: only install plugins from trusted sources under your user account. Out-of-process migration tracked in [#6](https://github.com/aidanns/agent-auth/issues/6). Implemented: [Load Notification Plugin](design/functional_decomposition.yaml#L38) |
| things-bridge constructs arbitrary argv passed to things-client CLI    | Medium | Low        | Low    | things-bridge constructs the argv from validated, schema-matched request parameters, not from raw client input. Targets: **likelihood**. Implemented: [Delegate Token Validation](design/functional_decomposition.yaml#L111), [Fetch Things Data](design/functional_decomposition.yaml#L113)                                                                                                                                     |

## Key handling

- The HMAC signing key and AES-256-GCM encryption key are generated on first
  run and stored in the system keyring (macOS Keychain or libsecret/gnome-keyring
  on Linux).
- Keys are loaded into memory at server startup and never written to disk in
  plaintext.
- Keys are not rotated automatically. Manual rotation requires revoking all
  existing token families (as their HMAC signatures will no longer verify) and
  generating a new key.
- The keyring service name is `agent-auth`; the key name is `signing-key` (HMAC)
  and `encryption-key` (AES-256-GCM).

## Revocation flow

1. **Explicit revocation**: `agent-auth token revoke <family-id>` marks all
   tokens in the family as revoked in `tokens.db`. Subsequent validation calls
   return `401 Unauthorized`.
2. **Refresh-token reuse detection**: presenting a previously used refresh token
   triggers immediate family-wide revocation (all access and refresh tokens in
   the family are invalidated). This limits the blast radius of a stolen refresh
   token.
3. **Token expiry**: access tokens carry an expiry timestamp; validation rejects
   expired tokens with `401 Unauthorized`. things-cli retries with the refresh
   token on `token_expired` responses.
4. **Key rotation**: replacing the signing key in the keyring invalidates all
   previously issued tokens on the next validation call, acting as a
   revocation-of-last-resort.

## Audit surface

The following events are written to **agent-auth's** audit log (stderr +
structured log). Consolidating audit events across all services (agent-auth,
things-bridge) into a single structured JSON schema is tracked in
[#100](https://github.com/aidanns/agent-auth/issues/100).

- Token family created (family ID, scopes, tier, timestamp)
- Token validated (family ID, scope checked, outcome, timestamp)
- Token refreshed (old family ID, new family ID, timestamp)
- Token revoked (family ID, reason, timestamp)
- Token rotated (old family ID, new family ID, timestamp)
- JIT approval requested (family ID, scope, timestamp)
- JIT approval granted or denied (family ID, scope, outcome, timestamp)
- Scope modified (family ID, changed scopes, timestamp)

Token values (the `aa_` or `rt_` strings) are never logged. All records reference
family IDs only.

## Cybersecurity standard

This project adopts **NIST SP 800-53 Revision 5** as its reference cybersecurity
standard. The five control families below are in scope because each maps to a
specific component of the current implementation:

- **AC — Access Control**: the three-tier scope model (`allow`/`prompt`/`deny`)
  and the per-family scope set enforced in `src/agent_auth/scopes.py` and the
  [Check Scope Authorization](design/functional_decomposition.yaml#L28) and
  [Resolve Access Tier](design/functional_decomposition.yaml#L30) leaf
  functions.
- **AU — Audit and Accountability**: the append-only audit log in
  `src/agent_auth/audit.py`, fed by every token lifecycle event and
  authorization decision.
- **IA — Identification and Authentication**: HMAC-SHA256 signed tokens with
  per-family revocation (`src/agent_auth/tokens.py`) and the agent-auth
  server as the sole validation authority
  (`src/agent_auth/server.py` — the `/validate` endpoint).
- **SC — System and Communications Protection**: AES-256-GCM field encryption
  (`src/agent_auth/crypto.py`) and the signing/encryption keys held in the
  system keyring (`src/agent_auth/keys.py`). Transport protection: both HTTP
  servers bind `127.0.0.1` by default (loopback-only satisfies SC-8 on a
  single host) and accept an optional TLS listener via
  `tls_cert_path` / `tls_key_path` when the trust boundary extends beyond
  loopback — e.g. a devcontainer reaching a host-side agent-auth. See
  [ADR 0025](design/decisions/0025-tls-for-devcontainer-host-traffic.md).
- **SI — System and Information Integrity**: request-body size caps and
  schema-validated parameters before subprocess argv construction
  (`src/things_bridge/server.py`).

Controls outside these families are out of scope for the current codebase; the
product is a local, single-user authorization system and does not cover
personnel, supply-chain, physical, or enterprise-scale controls. Applicability
assessments for new features are documented in ADRs under
`design/decisions/`.

### Control families relevant to this project

The table below lists selected controls with their current implementation status.
`Implemented` means the control is satisfied by a deployed function.
`Partial` means the control is partially satisfied with a known gap.
`Planned` means the control is selected but not yet implemented.

| Family                               | ID  | Selected controls                                                                                                                                                                                                                                                                                          | Status                                                                                                                                                                                                            |
| ------------------------------------ | --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Access Control                       | AC  | AC-3 (Access Enforcement) — scope-based token validation; AC-6 (Least Privilege) — scopes are narrowly granted per token family                                                                                                                                                                            | Implemented                                                                                                                                                                                                       |
| Audit and Accountability             | AU  | AU-2 (Event Logging) — token operations and authorization decisions logged; AU-3 (Content of Audit Records) — family ID, scope, outcome, timestamp per record; AU-9 (Protection of Audit Information) — append-only log; AU-12 (Audit Record Generation) — all token lifecycle events covered              | Partial — AU-9 lacks cryptographic integrity ([#103](https://github.com/aidanns/agent-auth/issues/103)); AU-3 schema is not yet shared across services ([#100](https://github.com/aidanns/agent-auth/issues/100)) |
| Identification and Authentication    | IA  | IA-5 (Authenticator Management) — HMAC-signed tokens with expiry and family-wide revocation; IA-9 (Service Identification and Authentication) — agent-auth is the sole token authority; bridges re-validate on every request                                                                               | Implemented                                                                                                                                                                                                       |
| System and Communications Protection | SC  | SC-8 (Transmission Confidentiality and Integrity) — loopback-only deployment (host-to-host); optional TLS listener on both services via `tls_cert_path` / `tls_key_path` for devcontainer-to-host deployments; SC-28 (Protection of Information at Rest) — AES-256-GCM encryption for sensitive DB columns | Implemented ([ADR 0025](design/decisions/0025-tls-for-devcontainer-host-traffic.md))                                                                                                                              |
| System and Information Integrity     | SI  | SI-10 (Information Input Validation) — request body size cap (1 MiB); schema-validated parameters before subprocess argv construction; SI-12 (Information Management and Retention) — token expiry enforced; consumed refresh tokens marked and not reused                                                 | Implemented                                                                                                                                                                                                       |

Control applicability assessments for new features should be documented in
`design/decisions/` ADRs at the time the feature is implemented.

## SDLC standard

This project adopts **NIST SP 800-218 v1.1 — Secure Software Development
Framework (SSDF)** as the reference standard for SDLC-side practices.
Per-practice conformance is tracked in [`design/SSDF.md`](design/SSDF.md),
covering the four SSDF practice groups:

- **PO — Prepare the Organization**: security requirements, toolchain
  selection, and per-PR security-check criteria.
- **PS — Protect the Software**: source-code protection, release
  integrity verification, and provenance archival.
- **PW — Produce Well-Secured Software**: threat modelling, secure
  design reviews, dependency hygiene, secure coding, code review,
  testing, and secure-by-default configuration.
- **RV — Respond to Vulnerabilities**: vulnerability intake, scanning,
  disclosure policy, and remediation.

SSDF pairs with NIST SP 800-53 (the cybersecurity standard named above):
SSDF specifies *how the project builds* the software, SP 800-53 specifies
*what the running system does*. Application-level verification under OWASP
ASVS is recorded in the next section
(see [`design/ASVS.md`](design/ASVS.md));
build-provenance mechanisms (SLSA, Sigstore/cosign, SBOM) that SSDF's PS
group references are tracked in
[#109](https://github.com/aidanns/agent-auth/issues/109),
[#110](https://github.com/aidanns/agent-auth/issues/110), and
[#111](https://github.com/aidanns/agent-auth/issues/111). The rationale
for selecting SSDF is recorded in
[`design/decisions/0015-nist-ssdf-sdlc-standard.md`](design/decisions/0015-nist-ssdf-sdlc-standard.md).

## Application security standard

This project adopts **OWASP Application Security Verification
Standard (ASVS) v5** as the reference standard for application-layer
verification, targeting **Level 2 (L2)**. Per-chapter conformance is
tracked in [`design/ASVS.md`](design/ASVS.md), covering the 17 ASVS v5
chapters.

The chapters in scope for agent-auth's HTTP surface are V1 Encoding
and Sanitization, V2 Validation and Business Logic, V4 API and Web
Service, V6 Authentication, V7 Session Management, V8 Authorization,
V9 Self-contained Tokens, V11 Cryptography, V12 Secure Communications,
V13 Configuration, V14 Data Protection, V15 Secure Coding and
Architecture, and V16 Security Logging and Error Handling. Chapters
scoped out — V3 Web Frontend Security (no browser UI), V5 File
Handling (no user file uploads), V10 OAuth and OIDC (custom token
scheme, not OAuth), and V17 WebRTC (no peer connections) — are listed
with their rationale in `design/ASVS.md`. L3 is not targeted because
its high-assurance / regulated-context bar does not fit a
solo-maintained, local-only, single-user project.

ASVS pairs with the companion standards named above: NIST SP 800-53
specifies *what the running system controls*, SSDF specifies *how
the project builds the software*, ASVS specifies *what the
application surface verifies*, and the supply-chain artefacts in the
next section specify *what the released artefact attests to*. The
rationale for selecting ASVS is recorded in
[`design/decisions/0019-owasp-asvs-application-security-standard.md`](design/decisions/0019-owasp-asvs-application-security-standard.md).

<!-- REUSE-IgnoreStart -->

## Supply-chain artifacts

Every GitHub release attaches the following alongside the sdist and
wheel:

- **`*.spdx.json`** — an SPDX 2.3 JSON Software Bill of Materials
  per distribution, generated by [Syft](https://github.com/anchore/syft)
  on the same GitHub-hosted runner that builds the artifact.
- **`*.sig.bundle`** — a keyless Sigstore signature bundle produced
  by `cosign sign-blob` using the runner's ephemeral OIDC identity.
  One bundle per signed file (sdist, wheel, and each SBOM).
- **`multiple.intoto.jsonl`** — a
  [SLSA v1.0](https://slsa.dev/spec/v1.0/) Build Level 3 provenance
  attestation in [in-toto](https://in-toto.io/) JSON-Lines format,
  emitted by
  [`slsa-framework/slsa-github-generator`](https://github.com/slsa-framework/slsa-github-generator)'s
  `generator_generic_slsa3.yml` reusable workflow. One attestation
  covers both the sdist and wheel, binding each artefact's sha256
  digest to the exact `release-publish.yml` workflow run, commit SHA,
  and ref that produced it. The generator runs on GitHub's isolated
  SLSA generator runner (not the `publish` runner that produced the
  artefacts), so a compromised step inside `publish` cannot forge the
  provenance.

### SLSA target level

The release pipeline claims **SLSA v1.0 Build Level 3**. Provenance
is produced by a hosted builder (GitHub's SLSA generator), is
tamper-resistant against the workflow that produced the artefacts,
and is transparency-log published via Sigstore. Level 3 is both the
current state on `main` and the target for the 1.0 release.

### Verification recipe

```bash
# Download the artefact, its SBOM, both signature bundles, and the
# `multiple.intoto.jsonl` provenance from the release.
# Filenames use PEP 625 normalisation (underscore, not hyphen) — that is the
# form `uv build` emits. Each SBOM lives next to its artefact as
# `<artefact>.spdx.json`.
: "${TAG:?set TAG=vX.Y.Z to the release tag you downloaded}"

VERSION="${TAG#v}"
SDIST="agent_auth-${VERSION}.tar.gz"
WHEEL="agent_auth-${VERSION}-py3-none-any.whl"
IDENTITY="https://github.com/aidanns/agent-auth/.github/workflows/release-publish.yml@refs/tags/${TAG}"

# 1. Cosign verifies the raw artefacts + their SBOMs against the
#    runner's keyless signature.
for f in "${SDIST}" "${WHEEL}" "${SDIST}.spdx.json" "${WHEEL}.spdx.json"; do
  cosign verify-blob \
    --bundle "${f}.sig.bundle" \
    --certificate-identity "${IDENTITY}" \
    --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
    "${f}"
done

# 2. slsa-verifier verifies the SLSA Build L3 provenance for each
#    artefact against the source repository and tag. Install with
#    `go install github.com/slsa-framework/slsa-verifier/v2/cli/slsa-verifier@latest`
#    or download a binary from
#    https://github.com/slsa-framework/slsa-verifier/releases.
for f in "${SDIST}" "${WHEEL}"; do
  slsa-verifier verify-artifact \
    --provenance-path multiple.intoto.jsonl \
    --source-uri github.com/aidanns/agent-auth \
    --source-tag "${TAG}" \
    "${f}"
done
```

The `--certificate-identity` pins the signature to the
`release-publish.yml` workflow running on the `v*` tag that cut the
release; a signature produced by any other workflow or branch fails
verification. Exact-match is used instead of `--certificate-identity-regexp`
so that unescaped `.` characters in the tag cannot widen the accepted
identity set. `slsa-verifier`'s `--source-uri` + `--source-tag` flags
enforce the same property for the SLSA provenance: an attestation
produced by a different repo, or for a different tag, will not verify
against the expected source.

### Trust boundary and residual risks

The supply-chain trust boundary ends at the GitHub-hosted runner:

- **Compromised GitHub-hosted runner.** Artefacts, SBOM, and
  signatures are produced in the same ephemeral job; a compromised
  runner could produce a consistently signed malicious bundle.
  Residual risk accepted; Rekor transparency-log inclusion is the
  detection signal.
- **Rekor availability.** `cosign verify-blob --bundle` requires
  the transparency-log entry embedded in the bundle to be
  verifiable against Rekor's current state. If Rekor is
  unreachable at verification time, or if an entry has been
  withheld, verification fails closed — the verifier cannot
  distinguish a censored entry from a forged one without an
  alternate log mirror.
- **Fulcio CA compromise.** The keyless signing model trusts the
  Sigstore PKI (Fulcio root). A compromised Fulcio could mint a
  certificate against any OIDC identity, including the runner's.
  Rekor transparency bounds the detection window but does not
  prevent a successful forgery within it.
- **No long-lived signing keys.** Cosign consumes the runner's
  OIDC token per-release, so there is no key to steal or revoke
  out-of-band. The trade-off is accepting the three risks above.
- **SLSA generator vs. publish runner.** SLSA build provenance is
  emitted by a reusable workflow that GitHub schedules on a separate,
  isolated runner, so a compromised step inside the `publish` job
  cannot forge the attestation. The residual trust root for
  provenance is GitHub's SLSA-generator repo
  (`slsa-framework/slsa-github-generator`) and the OIDC identity of
  that generator runner — the same Fulcio/Rekor trust surface as the
  cosign signatures, plus the tag-pinned workflow ref.

<!-- REUSE-IgnoreEnd -->

## Vulnerability reporting

This is a personal project. If you find a security issue, **do not open a
public GitHub issue.** Use
[GitHub private vulnerability reporting](https://github.com/aidanns/agent-auth/security/advisories/new)
to disclose the issue confidentially.

### Post-incident review

Every confirmed vulnerability that reaches committed state earns a
structured post-incident review (PIR) in
[`design/vulnerability-reviews/`](design/vulnerability-reviews/). The
review is part of the remediation PR, captures root cause, similar-
vulnerability search, remediation, and preventive follow-ups, and maps
onto NIST SSDF RV.2 / RV.3 practices. See
[`design/vulnerability-reviews/README.md`](design/vulnerability-reviews/README.md)
for the when-to-write and how-to-write guidance, and
[`design/vulnerability-reviews/TEMPLATE.md`](design/vulnerability-reviews/TEMPLATE.md)
for the template.
