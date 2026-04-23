<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# SSDF Conformance

agent-auth adopts [NIST SP 800-218 v1.1 — Secure Software Development
Framework](https://csrc.nist.gov/publications/detail/sp/800-218/final)
as its reference standard for SDLC-side practices. SSDF sits
alongside two companion standards:

- [NIST SP 800-53 Rev 5](../SECURITY.md#cybersecurity-standard) —
  system-level cybersecurity controls (access control, audit,
  authentication, communications protection, system integrity).
- [OWASP ASVS v5](ASVS.md) — application-layer verification (17
  chapters at target Level 2; see
  [ADR 0019](decisions/0019-owasp-asvs-application-security-standard.md)).

SSDF specifies **what practices** the project follows to produce
software; the companions specify **what the running system does**
and **what the application exposes**. Build-provenance mechanisms
(SLSA [#109](https://github.com/aidanns/agent-auth/issues/109),
Sigstore / cosign signing
[#110](https://github.com/aidanns/agent-auth/issues/110), SPDX
SBOM [#111](https://github.com/aidanns/agent-auth/issues/111),
and OpenSSF Scorecard
[#108](https://github.com/aidanns/agent-auth/issues/108)) are the
supply-chain controls that SSDF's PS and PW groups reference.

The rest of this document records current conformance per practice.
Rationale and pointers to the evidence for each row let future
implementation plans walk the SDLC standard as required by
`.claude/instructions/plan-template.md`.

## Rationale for selecting SSDF

- **Federal reference standard.** SSDF is the SDLC framework cited
  by EO 14028 and the OMB M-22-18 attestation form. Choosing it
  aligns this personal project with the same vocabulary a larger
  downstream consumer would expect.
- **Practice-focused, not prescriptive.** SSDF groups outcomes
  (PO / PS / PW / RV) and leaves the implementation up to the
  project. That fits a solo-maintained project where adopting,
  e.g., BSIMM or SAMM would pull in roles and governance that
  don't exist at this scale.
- **Maps cleanly onto existing artefacts.** Every practice has a
  candidate artefact already in the repo
  (`design/ASSURANCE.md`, `SECURITY.md`, `CONTRIBUTING.md`,
  ADRs, CI workflows). SSDF provides the taxonomy; the artefacts
  provide the evidence.

## Conformance status legend

- **Implemented** — a committed artefact satisfies the practice
  task today.
- **Partial** — practice is partially satisfied with a known gap;
  the linked issue tracks the remainder.
- **Planned** — practice is selected but not yet started; the
  linked issue tracks the work.
- **Not applicable** — practice is scoped out because it does
  not fit a solo, local-only, single-user project. The rationale
  is given in-line.

## Prepare the Organization (PO)

| Task   | Summary                                                           | Status         | Evidence / gap                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ------ | ----------------------------------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PO.1.1 | Identify and document security requirements for software          | Implemented    | [`SECURITY.md`](../SECURITY.md), [`design/ASSURANCE.md`](ASSURANCE.md), ADRs under [`design/decisions/`](decisions/).                                                                                                                                                                                                                                                                                                                     |
| PO.1.2 | Identify and document requirements for software development infra | Implemented    | [`.claude/instructions/service-design.md`](../.claude/instructions/service-design.md), [`.claude/instructions/tooling-and-ci.md`](../.claude/instructions/tooling-and-ci.md), and `scripts/verify-dependencies.sh` / `scripts/verify-standards.sh` gates.                                                                                                                                                                                 |
| PO.1.3 | Communicate requirements to stakeholders and third parties        | Implemented    | [`CONTRIBUTING.md`](../CONTRIBUTING.md) documents the expectations contributors inherit; `.claude/instructions/` files are committed so AI collaborators see the same standards.                                                                                                                                                                                                                                                          |
| PO.2.1 | Create roles and responsibilities                                 | Not applicable | Solo-maintainer project; there is one role (maintainer) and it is the repository owner. Record maintained in `CONTRIBUTING.md` ("Author" section of `README.md`).                                                                                                                                                                                                                                                                         |
| PO.2.2 | Provide role-based training                                       | Not applicable | No multi-person team to train.                                                                                                                                                                                                                                                                                                                                                                                                            |
| PO.2.3 | Obtain upper-management commitment                                | Not applicable | Project is not organisationally governed.                                                                                                                                                                                                                                                                                                                                                                                                 |
| PO.3.1 | Specify which tools are mandatory in the toolchain                | Implemented    | [`.claude/instructions/tooling-and-ci.md`](../.claude/instructions/tooling-and-ci.md), [`.claude/instructions/python.md`](../.claude/instructions/python.md), [`.claude/instructions/bash.md`](../.claude/instructions/bash.md) name the required tools; `scripts/verify-dependencies.sh` enforces their presence on contributor hosts.                                                                                                   |
| PO.3.2 | Follow recommended security practices when deploying tools        | Implemented    | Tools pinned via `uv.lock`, `lefthook.yml` (pre-commit), and [`.github/actions/setup-toolchain/`](../.github/actions/setup-toolchain) composite action. Upstream versions tracked by Dependabot.                                                                                                                                                                                                                                          |
| PO.3.3 | Configure tools to generate artifacts that support audit trails   | Partial        | CI jobs publish logs on every PR. Structured-log retention and schema pinning is tracked in [#20](https://github.com/aidanns/agent-auth/issues/20); toolchain version alignment in [#87](https://github.com/aidanns/agent-auth/issues/87).                                                                                                                                                                                                |
| PO.4.1 | Define criteria for software security checks                      | Implemented    | `scripts/verify-standards.sh`, `scripts/verify-dependencies.sh`, `scripts/verify-function-tests.sh`, `scripts/verify-design.sh` codify the per-PR checks. CI runs them non-advisorily — a red check blocks merge.                                                                                                                                                                                                                         |
| PO.4.2 | Implement processes, mechanisms, etc. to gather and analyze info  | Implemented    | CI surfaces failures on PRs and via the daily `pip-audit` schedule. `pip-audit` emits SARIF on every run and `.github/workflows/security.yml` uploads it to the GitHub Security tab (Code scanning alerts). Scheduled-run failures auto-open (or comment on) a dedupe issue carrying the `pip-audit-failure` label via `scripts/ci/report-scan-failure.sh`; a subsequent green scheduled run auto-closes it so the signal tracks reality. |
| PO.5.1 | Separate and protect each development environment                 | Partial        | Tokens and keys are scoped per-OS via `.venv-$(uname -s)-$(uname -m)` and per-user keyring entries. Devcontainer isolates the dev environment from the host. TLS between devcontainer and host is missing — tracked in [#101](https://github.com/aidanns/agent-auth/issues/101).                                                                                                                                                          |
| PO.5.2 | Secure and harden development endpoints                           | Partial        | Developer machine hardening is out of scope for a personal project. Devcontainer base image is pinned; commit signing on `main` is enforced by a GitHub repository ruleset (`required_signatures`).                                                                                                                                                                                                                                       |

## Protect the Software (PS)

| Task   | Summary                                                          | Status      | Evidence / gap                                                                                                                                                                                                                                                                                                                                                                                                                |
| ------ | ---------------------------------------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PS.1.1 | Store all forms of code securely                                 | Implemented | Source lives in a private-visibility-capable GitHub repo under the maintainer's account. Commit signing is documented in `CONTRIBUTING.md` and enforced on `main` by a GitHub repository ruleset (`required_signatures`). DCO sign-off is enforced on every PR by `.github/workflows/dco.yml`; bot-authored commits are exempt.                                                                                               |
| PS.2.1 | Make software integrity verification information available       | Implemented | Every release carries keyless Sigstore / cosign signatures ([#110](https://github.com/aidanns/agent-auth/issues/110)) and SLSA v1.0 Build Level 3 provenance ([#109](https://github.com/aidanns/agent-auth/issues/109)) — see [ADR 0020](decisions/0020-slsa-build-provenance.md). `cosign verify-blob` and `slsa-verifier verify-artifact` recipes are documented in [`SECURITY.md`](../SECURITY.md#supply-chain-artifacts). |
| PS.3.1 | Archive the necessary files and supporting data for each release | Implemented | GitHub retains tags, release assets, and the `CHANGELOG.md` entry per release; every release additionally bundles per-artefact SPDX 2.3 SBOMs ([#111](https://github.com/aidanns/agent-auth/issues/111)).                                                                                                                                                                                                                     |
| PS.3.2 | Collect, safeguard, maintain, and share provenance data          | Implemented | Tag-triggered autorelease ([#106](https://github.com/aidanns/agent-auth/issues/106)) + SLSA Build L3 in-toto attestation ([#109](https://github.com/aidanns/agent-auth/issues/109), [ADR 0020](decisions/0020-slsa-build-provenance.md)) binds each artefact's sha256 digest to the workflow run, commit SHA, and ref. Attestations ship as `multiple.intoto.jsonl` on every GitHub release.                                  |

## Produce Well-Secured Software (PW)

| Task   | Summary                                                           | Status      | Evidence / gap                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ------ | ----------------------------------------------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PW.1.1 | Use forms of risk modeling to identify threats                    | Implemented | STRIDE table in [`SECURITY.md`](../SECURITY.md#threat-model) covers spoofing / tampering / repudiation / information disclosure / DoS / elevation of privilege per component. Risk rated per NIST SP 800-30 Rev 1.                                                                                                                                                                                                                                                                                                                                                                                  |
| PW.1.2 | Track and maintain the software's security requirements           | Implemented | [`SECURITY.md`](../SECURITY.md) and [`design/ASSURANCE.md`](ASSURANCE.md) are refreshed before any security-relevant change lands; the `plan-template.md` *Threat model* step enforces this.                                                                                                                                                                                                                                                                                                                                                                                                        |
| PW.1.3 | Communicate requirements to those responsible for implementation  | Implemented | `.claude/instructions/` files are the communication channel to the sole human contributor and every AI collaborator.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| PW.2.1 | Review the software design for compliance with security reqs      | Implemented | `plan-template.md` *Design and verification* step. The `verify-design.sh` gate cross-checks `design/functional_decomposition.yaml` against implemented functions.                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| PW.4.1 | Acquire and maintain well-secured software components             | Implemented | Dependencies tracked in `pyproject.toml` / `uv.lock`. Dependabot opens grouped minor/patch PRs; `pip-audit` runs on every PR and daily for the full dependency closure (including dev deps). Reusable in-tree libraries (e.g. `things_client_common`) are split out as explicit sibling packages so their trust boundary is reviewable.                                                                                                                                                                                                                                                             |
| PW.4.4 | Verify that acquired components comply with requirements          | Implemented | `pip-audit` (`task pip-audit`), `uv.lock` pinning, and the `verify-dependencies.sh` gate that asserts required tooling is present on contributor hosts.                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| PW.5.1 | Follow all secure coding practices that are appropriate           | Implemented | [`.claude/instructions/coding-standards.md`](../.claude/instructions/coding-standards.md), `.claude/instructions/python.md`, and `.claude/instructions/bash.md`. Enforced via `ruff`, `mypy` (tracked in [#48](https://github.com/aidanns/agent-auth/issues/48)), `shellcheck`, `shfmt`, and `treefmt`.                                                                                                                                                                                                                                                                                             |
| PW.6.1 | Use compiler, interpreter, and build tools that offer features... | Implemented | Python 3.11+ with `ruff` enforcing modern syntax; `mypy` strict for type checks ([#48](https://github.com/aidanns/agent-auth/issues/48)).                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| PW.6.2 | Determine which compiler, interpreter, and build tool features... | Partial     | `uv` produces deterministic builds from `uv.lock`. Release-time hardening (reproducible builds, SBOM) is tracked under [#106](https://github.com/aidanns/agent-auth/issues/106) / [#111](https://github.com/aidanns/agent-auth/issues/111).                                                                                                                                                                                                                                                                                                                                                         |
| PW.7.1 | Determine whether code review and/or analysis should be performed | Implemented | ASSURANCE.md *Required activities* mandates code review on every PR; the Claude reviewer subagent + self-review pattern is the solo-developer equivalent.                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| PW.7.2 | Perform the code review and/or analysis                           | Implemented | `ruff`, `shellcheck`, and the code-review subagent run on every PR. CodeQL (`.github/workflows/codeql.yml`) runs the `security-extended` query suite against `python` and `actions` on every PR and daily at 07:00 UTC; findings are published to the GitHub Security tab via SARIF upload.                                                                                                                                                                                                                                                                                                         |
| PW.8.1 | Determine whether executable code testing should be performed     | Implemented | ASSURANCE.md mandates tests for every behaviour; `verify-function-tests.sh` enforces function-to-test coverage.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| PW.8.2 | Design and perform the executable code testing                    | Implemented | `pytest` unit suite + Docker-harnessed integration tests (ADR 0004 / 0005). Coverage threshold enforced via `--cov-fail-under` ([#37](https://github.com/aidanns/agent-auth/issues/37)). Mutation testing via mutmut on security-critical modules ([ADR 0021](decisions/0021-mutation-testing-security-critical.md), `.github/workflows/mutation.yml`). Fault-injection layer under `tests/fault/` covers SQLite errors, audit disk-full, keyring unavailability, plugin timeout, agent-auth unreachable, and Things AppleScript failures ([#39](https://github.com/aidanns/agent-auth/issues/39)). |
| PW.9.1 | Define a secure baseline configuration                            | Implemented | All services bind to `127.0.0.1` by default; request body capped at 1 MiB; scope tiers default to `deny`; keyring-backed key material never touches disk. Documented in [`SECURITY.md`](../SECURITY.md).                                                                                                                                                                                                                                                                                                                                                                                            |
| PW.9.2 | Implement the secure baseline by default                          | Implemented | `Config` defaults in `src/agent_auth/config.py` and `src/things_bridge/config.py` match the secure baseline; overrides are opt-in via YAML (migration from JSON tracked in [#24](https://github.com/aidanns/agent-auth/issues/24)).                                                                                                                                                                                                                                                                                                                                                                 |

## Respond to Vulnerabilities (RV)

| Task   | Summary                                                          | Status      | Evidence / gap                                                                                                                                                                                                                                                            |
| ------ | ---------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RV.1.1 | Gather information from purchasers / users / public sources      | Implemented | [`SECURITY.md`](../SECURITY.md#vulnerability-reporting) names GitHub private vulnerability reporting as the intake channel; Dependabot + `pip-audit` surface advisories for direct and transitive deps.                                                                   |
| RV.1.2 | Review, analyze, and/or test to identify vulnerabilities         | Implemented | `pip-audit` (on every PR + daily schedule), `ruff` / `shellcheck` static checks, integration tests. Per-tool scan coverage expansion in [#88](https://github.com/aidanns/agent-auth/issues/88).                                                                           |
| RV.1.3 | Have a policy that addresses vulnerability disclosure            | Implemented | [`SECURITY.md`](../SECURITY.md#vulnerability-reporting) documents the private-reporting channel.                                                                                                                                                                          |
| RV.2.1 | Analyze vulnerabilities to determine root cause                  | Implemented | Every confirmed vulnerability earns a post-incident review (PIR) under [`design/vulnerability-reviews/`](vulnerability-reviews/) using [`TEMPLATE.md`](vulnerability-reviews/TEMPLATE.md). The *Root cause* section forces an intent-level analysis alongside the fix PR. |
| RV.2.2 | Develop, test, and release remediations                          | Implemented | Standard PR workflow applies to security fixes; `CHANGELOG.md` records the fix per release; release tags are GPG/SSH signed. PIR *Remediation* section cross-references the fix PR and regression test.                                                                   |
| RV.3.1 | Analyze to identify underlying cause                             | Implemented | Covered by the PIR *Root cause* section — same template as RV.2.1 — which demands an intent-level explanation rather than a symptom write-up.                                                                                                                             |
| RV.3.2 | Analyze to identify similar vulnerabilities in other software    | Implemented | PIR *Similar-vulnerability search* section records the query / tool used, the paths searched, and any sibling fixes landed. Missing the section is a template-checklist gap, not an ad-hoc oversight.                                                                     |
| RV.3.3 | Analyze root causes over time to identify patterns               | Implemented | PIR *Patterns over time* section cross-references prior PIRs in the same directory; the directory itself accumulates the longitudinal record. Structural fixes (lint rules, types, wrappers) are preferred over point fixes once a pattern repeats.                       |
| RV.3.4 | Review information needed to plan and implement fixes to prevent | Implemented | PIR *Preventive follow-ups* section requires concrete tracked actions — issue / PR links for lint rules, threat-model refreshes, and contributor-instruction updates. Aspirational hardening without a tracked follow-up is not accepted.                                 |

## Per-plan checklist

`.claude/instructions/plan-template.md` *Cybersecurity standard
compliance* step is amended implicitly by this document: plans
should walk the relevant SSDF practice tasks alongside the
NIST SP 800-53 controls already required. When a plan introduces a
new category of work (e.g. a new subprocess boundary, a new
release artefact), update this document in the same PR rather
than deferring it.

## Consistency with NIST SP 800-53

The NIST SP 800-53 Rev 5 SA family (System and Services
Acquisition) is the cybersecurity-standard counterpart most
adjacent to SSDF. Per [`SECURITY.md`](../SECURITY.md#cybersecurity-standard),
SA is out of scope for this project — the five in-scope 800-53
families (AC / AU / IA / SC / SI) cover the running system;
SDLC-side practices that SA would otherwise cover are instead
recorded here under SSDF. No conflicts exist between the SSDF
rows above and the 800-53 controls recorded in `SECURITY.md`.

## Follow-up issues

Gaps identified by this audit are tracked via GitHub issues
linked in the tables above. Issues filed as part of
[#113](https://github.com/aidanns/agent-auth/issues/113):

- [#131](https://github.com/aidanns/agent-auth/issues/131) —
  Adopt a structured vulnerability post-incident review template
  (RV.2.1, RV.3.1, RV.3.2, RV.3.3, RV.3.4).
