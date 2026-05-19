<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# macOS-Tart-VM CI lane: operator's guide

Companion to ADR 0049 and
`.github/workflows/test-system-macos-tart.yml`. This guide is for
the operator triaging a failure of the macOS-Tart-VM smoke lane, or
bumping the digest-pinned base image / Tart CLI version.

## Reading the failure-artefact bundle

Every run uploads a bundle named
`macos-tart-smoke-<run_id>-<run_attempt>` (`if: always()`, so it
ships even when the smoke test or boot-prep fails). Open the
artefacts panel on the GitHub Actions run and download the bundle.

Bundle layout:

```
macos-tart-artefacts/
  bootstrap.log              <- step-by-step trace of boot-prep, with
                                `set -x` around the osascript seed call.
                                First place to look.
  pytest.log                 <- smoke test stdout/stderr (`-v
                                --tb=long --color=no`).
  tart-run.log               <- Tart's own stdout from the headless
                                boot. Useful when SSH never came up.
  artefact-rsync.log         <- rsync output from the in-VM artefact
                                pull. If empty / missing, the VM
                                died before the rsync step.
  in-vm/
    bootstrap.log            <- duplicate of the above for runs where
                                the in-VM rsync succeeded; identical
                                content. Keep both for the case where
                                the SSH-side `tee` died early.
    sw_vers.txt              <- runner's actual macOS version.
                                Catches Sequoia minor bumps that
                                broke the TCC schema.
    system_profiler.txt      <- `system_profiler SPSoftwareDataType`
                                output. Same purpose as sw_vers.txt
                                with more detail.
    tcc-grant-row.txt        <- the row(s) currently in `access`
                                with `service = kTCCServiceAppleEvents`.
                                Empty -> seed didn't take.
    tcc-access-schema.txt    <- `.schema access` from TCC.db. Diff
                                against the bootstrap.sh's INSERT
                                column list to catch schema drift.
    tcc-probe.stderr         <- stderr from the `osascript -e 'tell
                                application "Things3" to count to
                                dos'` probe. macOS prompt text here
                                is the canonical TCC failure
                                signature.
    *.crash                  <- any `~/Library/Logs/DiagnosticReports/
                                *.crash` files. Usually empty; when
                                present, an osascript or Things 3
                                crash is the failure mode.
```

Explicitly NOT in the bundle: screenshots (low signal headless),
full `/var/log/system.log` (huge, mostly noise). Add later if a
real incident motivates the noise budget.

## Common failure modes

### TCC schema mismatch on Sequoia minor bump

**Signature**: `bootstrap.log` shows step 3 fail with
`Error: table access has no column named ...` from `sqlite3`. Or
the probe in step 4 fails with the macOS Automation prompt error
("Things3 wants permission to ...") even after the seed completed.

**Root cause**: Apple bumped the `access` table's column set in a
Sequoia minor version. The `INSERT` in
`scripts/ci/macos-tart/bootstrap.sh` uses an explicit column list,
so a column rename / drop / reorder breaks it.

**Fix**: pull `tcc-access-schema.txt` from the artefact bundle, diff
against the column list in the bootstrap script's `INSERT`, update
the script to match. Confirm `sw_vers.txt` records the new minor
version so future regressions tie back to this bump.

### Homebrew install failure

**Signature**: `bootstrap.log` step 1 fails with the Homebrew
install script erroring (commonly: GitHub rate-limit on the install
script's curl, or a Homebrew commit-pin issue).

**Fix**: usually transient — re-run the workflow. If recurrent,
consider pre-installing Homebrew in a custom Tart image (the
Option A path tracked as #568).

### Things 3 cask install regression

**Signature**: `bootstrap.log` step 2 fails with
`Error: Cask 'things' is unavailable` or a download checksum
failure.

**Fix**: Cultured Code occasionally rotates the download URL. The
`homebrew/cask` repo usually catches up within a day; re-run the
workflow once the upstream cask is fixed. Long-term, Option A
(#568) removes the per-PR cask install entirely.

### Things 3 dictionary breakage

**Signature**: `bootstrap.log` step 6 (the `set -x`-traced
`osascript -e 'make new to do ...'` call) reports an AppleScript
syntax error or "can't get to do" from osascript, or the smoke
test's `pytest.log` shows the round-tripped to-do is missing or
named differently than `ci-smoke-todo`.

**Root cause**: a Things 3 update changed the AppleScript
dictionary's `to do` class definition, the `make new to do`
verb signature, or the `name` property semantics.

**Fix**: open Script Editor.app in a developer Mac, drop the
new Things 3.app onto it, inspect the `Things 3` dictionary. Update
either the `osascript -e` seed in `bootstrap.sh` or the assertion
in
`packages/things-client-cli-applescript/tests/system/test_macos_tart_smoke.py`
to match. If the breakage extends to the read side, the
`things-client-cli-applescript`'s `things.py` runner itself will
need updating — that's beyond the smoke lane's scope, file an
issue against the package.

### VM never reaches SSH-ready

**Signature**: workflow step "Boot VM Headless and Wait for SSH"
fails with `VM <name> did not reach SSH-ready within 600s`.
`tart-run.log` may contain Tart's own diagnosis.

**Fix**: usually the base image got rotated upstream and the
DHCP / SSH seed inside the new image differs. Bump the
`TART_BASE_IMAGE` digest pin to the latest verified-good rev (see
"Digest-bump procedure" below).

## Local reproduction recipe

The boot-prep is reproducible on any Apple Silicon Mac with Tart
installed. From a developer machine:

```bash
brew install cirruslabs/cli/tart

# Pull the same digest the workflow uses (read from
# .github/workflows/test-system-macos-tart.yml's TART_BASE_IMAGE).
tart pull ghcr.io/cirruslabs/macos-sequoia-base:latest
tart clone ghcr.io/cirruslabs/macos-sequoia-base:latest agent-auth-smoke-local

# Boot headless. Wait for SSH; tart ip prints the guest IP once
# DHCP comes up.
tart run --no-graphics agent-auth-smoke-local &
ip=$(tart ip agent-auth-smoke-local)

# Default cirruslabs base image creds: admin / admin.
sshpass -p admin rsync -a -e "ssh -o StrictHostKeyChecking=no" \
  ./ admin@"${ip}":agent-auth/

sshpass -p admin ssh -o StrictHostKeyChecking=no admin@"${ip}" \
  'cd ~/agent-auth && bash scripts/ci/macos-tart/bootstrap.sh'

# Smoke test:
sshpass -p admin ssh -o StrictHostKeyChecking=no admin@"${ip}" \
  'cd ~/agent-auth \
    && AGENT_AUTH_REAL_THINGS3=1 \
       UV_PROJECT_ENVIRONMENT=.venv-Darwin-arm64 \
       ~/.local/bin/uv run --no-sync pytest \
         packages/things-client-cli-applescript/tests/system/test_macos_tart_smoke.py \
         --no-cov -v'

# Tear down:
tart stop agent-auth-smoke-local
tart delete agent-auth-smoke-local
```

Iterate on `bootstrap.sh` between `tart clone` and `tart delete` —
each `tart clone` from the cached pull is fast (~5s).

## Digest-bump procedure

The `TART_BASE_IMAGE` env var in the workflow file pins the
`cirruslabs/macos-sequoia-base` image by digest so a new upstream
rev cannot silently change the runner OS. To bump:

1. Look up the current `latest` digest:

   ```bash
   docker manifest inspect ghcr.io/cirruslabs/macos-sequoia-base:latest \
     --verbose | jq -r '.Descriptor.digest'
   ```

   (Tart's images are stored as OCI manifests on GHCR, so
   `docker manifest inspect` works even though Tart doesn't itself
   run under Docker.)

2. Confirm the new digest's `sw_vers` matches what
   `scripts/ci/macos-tart/bootstrap.sh`'s `INSERT` was last
   verified against. If the OS minor version bumped, run the
   local-reproduction recipe above and inspect
   `tcc-access-schema.txt` to catch any TCC schema drift before
   landing the bump.

3. Update `TART_BASE_IMAGE` in
   `.github/workflows/test-system-macos-tart.yml` to
   `ghcr.io/cirruslabs/macos-sequoia-base@sha256:<new-digest>`,
   commit, push.

4. The PR carrying the bump touches
   `.github/workflows/test-system-macos-tart.yml`, so the
   `macos_tart_plumbing_updated` filter trips and the workflow
   exercises the new base image on the bump PR itself. Don't
   `automerge` until that smoke run is green.

## Tart CLI version bump

`TART_VERSION` and `TART_TARBALL_SHA256` in the workflow file are
bumped together. To bump:

1. Look up the latest stable Tart release at
   https://github.com/cirruslabs/tart/releases.

2. Compute the sha256 of the matching darwin-arm64 release tarball:

   ```bash
   curl -sL \
     https://github.com/cirruslabs/tart/releases/download/${VERSION}/tart-${VERSION}-arm64.tar.gz \
     | shasum -a 256
   ```

3. Update both `TART_VERSION` and `TART_TARBALL_SHA256` in the same
   commit. As with the digest bump, the touch trips
   `macos_tart_plumbing_updated` so the workflow self-tests the
   bump on the same PR.

## Deliberately failing the workflow (artefact-bundle verification)

Whenever the failure-artefact bundle's contents change (e.g. a new
diagnostic file is added to the boot-prep), verify the upload by
deliberately failing the smoke test once. The accepted ritual:

1. Land a one-line patch on the smoke test that breaks the
   assertion deterministically:
   `assert names == ["never-going-to-match"]`.
2. Push, wait for the run to fail, download the artefact bundle,
   confirm every expected file is present.
3. Revert the deliberate-fail commit before requesting review /
   merge.

Capturing this as a ritual rather than an automated test because
the artefact bundle's value is human inspection — automating
"did the file appear" doesn't catch "does the file's content tell
me what I need to know".
