<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Consolidate setup-toolchain release-asset downloads into a shared helper

Resolves parts 1 and 2 of [#165](https://github.com/aidanns/agent-auth/issues/165).
Part 3 (parallelise downloads) is deferred to a follow-up issue because it
is a larger structural change and the issue itself sequences it after
part 1.

## Problem

After `#166` landed, `.github/actions/setup-toolchain/action.yml` has 7
near-identical steps (`shellcheck`, `shfmt`, `ruff`, `taplo`,
`keep-sorted`, `ripsecrets`, `treefmt`) that all run:

```bash
curl -fsSL --retry 2 --retry-delay 2 --retry-all-errors \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -o /tmp/<name>.<ext> \
  "<release-url>"
echo "${<NAME>_SHA256}  /tmp/<name>.<ext>" | sha256sum -c -
```

Two scoped-out opportunities from the simplify review of `#159`'s PR:

1. The 7 blocks are pure duplication — any new hardening (connect
   timeout, mirror fallback, log-suppression tweak) has to be applied
   7 times.
2. `--retry 2 --retry-delay 2` disables curl's built-in exponential
   backoff and caps recovery at ~4s. `--retry 5 --retry-max-time 60`
   with no explicit `--retry-delay` lets curl honour `Retry-After` and
   exponential backoff on 429s/5xx — better recovery on the kind of
   transient failure the retry is there to catch, at zero cost on the
   happy path.

## Approach

1. **Extract `scripts/ci/fetch-release-asset.sh <url> <out-path> <sha256>`.**
   The helper encapsulates the curl+auth+retry+sha256 pattern. Each of
   the 7 action steps calls it once and then handles its own
   extraction/install (which genuinely differs per tool — `.tar.xz`,
   `.tar.gz`, `.gz`, raw binary).
2. **Retune the retry params inside the helper.** One change point
   rather than 7. Use `--retry 5 --retry-max-time 60 --retry-all-errors`
   with no `--retry-delay`.
3. **Also retune `Install systems-engineering`.** That step stays
   inline because it fetches via the Contents API with
   `Accept: application/vnd.github.raw` and has no sha256 to check —
   it does not fit the helper's signature. But it benefits from the
   same retry-param retune, so apply Part 2 to it in-place.

Helper signature (verbatim from the issue):

```
scripts/ci/fetch-release-asset.sh <url> <out-path> <sha256>
```

- Reads `GITHUB_TOKEN` from env. Error out with a clear message if
  unset — authenticated download is now the only path and missing
  auth will just fail opaquely on the curl side otherwise.
- `<out-path>` is where the asset ends up on disk.
- `<sha256>` is the hex digest; verified with `sha256sum -c -` right
  after download. Verification failure aborts the script.

Rejected alternatives:

- **Unify systems-engineering into the same helper** via an optional
  `--accept`/`--no-sha256` flag. The flag surface makes the 7 simple
  calls harder to read and systems-engineering is a one-off — the
  duplication isn't here. Keep it inline.
- **Move extraction (`tar -xJf`, `gunzip`, ...) into the helper.** The
  extraction step is genuinely heterogeneous (4 shapes across 7 tools)
  and the install target differs (path inside extracted dir vs.
  standalone binary). A tar/gunzip dispatcher inside the helper adds
  more complexity than it saves.
- **Mirror fallback / connect-timeout now.** Out of scope for #165 —
  the helper just makes it a one-line change when we want it.

## Changes

1. `scripts/ci/fetch-release-asset.sh` (new) — bash script following
   the project's standard shape (`set -euo pipefail`, description
   comment surrounded by single blank lines, SPDX header). Uses
   `curl -fsSL --retry 5 --retry-max-time 60 --retry-all-errors`
   with `Authorization: Bearer ${GITHUB_TOKEN}`, writes to
   `<out-path>`, then runs `echo "<sha256>  <out-path>" | sha256sum -c -`.
2. `.github/actions/setup-toolchain/action.yml` —
   - Each of the 7 release-binary install steps calls
     `${GITHUB_ACTION_PATH}/../../../scripts/ci/fetch-release-asset.sh`
     instead of open-coding the curl+sha256 block.
   - `GITHUB_TOKEN` is exported via `env:` to make it available to the
     helper (same pattern as the current systems-engineering step).
   - `Install systems-engineering` step retunes its curl flags to
     `--retry 5 --retry-max-time 60 --retry-all-errors` (drops
     `--retry-delay 2`). No other behaviour change.
3. `CHANGELOG.md` — add an Unreleased "Changed" entry referencing #165.

## Verification

- `shellcheck scripts/ci/fetch-release-asset.sh` and `shfmt -d` clean
  (via `treefmt` / `lefthook pre-commit`).
- PR CI run passes: every setup-toolchain step still resolves the
  binary, verifies sha256, and installs the tool. The wall-time is
  unchanged on the happy path; only the retry shape differs on
  failure.
- Spot-check one install step's CI log for the new curl flags
  (`--retry 5 --retry-max-time 60`) and absence of `--retry-delay 2`.
- sha256 verification stays in place — confirm the `install tool`
  step still fails if we deliberately corrupt the pinned digest
  (mental smoke test, not an automated one).

## Skipped plan-template steps

- **Design / threat-model / ADR / cybersecurity / QM-SIL** — this is
  CI-tooling refactor inside a composite action plus one new bash
  helper. No runtime behaviour, no security posture change, no
  external surface.
- **Post-implementation standards review** — only
  `tooling-and-ci.md` and `bash.md` are relevant.
  `tooling-and-ci.md` § CI mandates sha256 pinning for tool binary
  downloads — the helper preserves that contract (verification still
  happens, and an unverified binary aborts the run).
  `bash.md` requires `shellcheck` and `shfmt` clean — enforced by
  `treefmt`/`lefthook` on the new script. `coding-standards.md`,
  `service-design.md`, `testing-standards.md`,
  `release-and-hygiene.md` do not apply.

## Deferred

Part 3 of #165 (parallelise release-binary downloads via
`curl --parallel --parallel-max 7`) is tracked in a follow-up issue
created at PR-open time. It is deferred because it restructures the
composite action (merging 7 sequential steps into one `run:` block
with separate per-tool extract/install steps) and the issue already
calls it out as "a bigger structural change — do after (1)".
