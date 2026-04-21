<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Verify checksums on tool binary downloads in setup-toolchain

Resolves [#135](https://github.com/aidanns/agent-auth/issues/135).

## Problem

`.github/actions/setup-toolchain/action.yml` downloads seven CLI
binaries directly over HTTPS (`shellcheck`, `shfmt`, `ruff`, `taplo`,
`keep-sorted`, `ripsecrets`, `treefmt`) with no integrity check. TLS
to the GitHub release CDN is the only barrier; a compromised release
artefact or server-side tampering would land attacker-controlled
binaries in CI (which has write access to the repo and read access
to any secrets scoped to the workflow).

## Approach

Pin a sha256 for each tool directly in the composite action, alongside
the version input, and verify with `sha256sum -c` after download and
before `install(1)` / `tar`. This gives the strongest integrity
property — tampering would have to land in the pinned repo, not
merely in transit or on the CDN — and a single uniform verification
mechanism across tools.

Rejected alternatives:

- **Fetch and parse upstream `checksums.txt`** — only some of the
  seven tools publish one (shfmt, treefmt). The rest do not, so we'd
  still need an in-repo pin for them. A mixed scheme is worse than a
  uniform one.
- **Sigstore / cosign verification** — only ruff and shellcheck offer
  it among these seven. Same heterogeneity problem, plus more moving
  parts.
- **Pin the download URL by digest via `gh release download --digest`**
  — GitHub's release API does not expose artefact digests for any of
  the seven releases we use (verified: `digest: null` on shellcheck
  assets).

## Changes

1. Add one input per tool holding the expected sha256 of the Linux
   x86_64 artefact we download, defaulted to the current pinned
   value.
2. Modify each of the seven install steps to:
   - Download to `/tmp/<artefact>`.
   - Verify `echo "<sha256>  /tmp/<artefact>" | sha256sum -c -` before
     extract/install. On mismatch `sha256sum -c` exits non-zero and
     the step fails — the composite action propagates that up.
3. Update `.claude/instructions/tooling-and-ci.md` to require
   checksum pinning for any new binary install added to CI.

## Out of scope

- The `curl -fsSL https://d2lang.com/install.sh | sh` and
  `systems-engineering/install.sh` pipe-to-shell installers have a
  similar but distinct threat surface (arbitrary scripts vs. archived
  binaries). The fix is different (pin the install script's sha256,
  or switch to a packaged release). Tracked as
  [#157](https://github.com/aidanns/agent-auth/issues/157) rather
  than bundled here, per the acceptance criteria that scope this
  change to the seven listed binary downloads.
- `astral-sh/setup-uv`, `arduino/setup-task` — these are third-party
  GitHub Actions, verified by action-pinning / Dependabot for
  actions, not by our download verification.

## Verification

- CI runs the workflow, which exercises the modified composite action
  on every check job. If any sha256 is wrong, the affected install
  step fails and CI fails.
- Manually confirm one failure path by temporarily flipping a byte
  of one pinned sha and observing that `sha256sum -c` aborts the
  step. (Done locally; not committed.)

## Design and verification

- **Design doc** — no behaviour or schema change visible to the
  project; `design/DESIGN.md` does not describe CI toolchain
  provisioning. No update required.
- **Threat model** — `SECURITY.md` is scoped to the running service's
  runtime trust boundaries and the outbound release supply chain
  (signed SBOMs); inbound CI tool integrity sits under build-time
  hygiene, which is owned by `.claude/instructions/tooling-and-ci.md`
  (updated by this PR). No SECURITY.md change.
- **ADR** — single, localised CI-hygiene change; does not meet the
  "significant design decision" bar. Skip.
- **Cybersecurity standard compliance** — this change *advances*
  compliance (supply-chain integrity) rather than risks regressing
  it. No new gap.
- **QM / SIL** — no functional behaviour change. No QM/SIL artefact
  required.

## Post-implementation standards review

- `coding-standards.md` — n/a (YAML + shell).
- `service-design.md` — n/a.
- `release-and-hygiene.md` — n/a (no versioned artefact or release
  changes).
- `testing-standards.md` — n/a (no runtime code changes).
- `tooling-and-ci.md` — *updated by this PR* to require checksum
  pinning for new tool installs.
- `bash.md` — the shell snippets in each install step follow the
  existing one-liner style; no new scripts added.
