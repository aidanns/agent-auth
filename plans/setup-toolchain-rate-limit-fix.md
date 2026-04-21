# Plan: Make systems-engineering install in setup-toolchain survive raw.githubusercontent.com 403s

Resolves [#155](https://github.com/aidanns/agent-auth/issues/155).

## Problem

`.github/actions/setup-toolchain/action.yml` fetches the
systems-engineering installer script via unauthenticated `curl` against
`raw.githubusercontent.com`. The raw CDN enforces a per-IP rate limit.
When the Test workflow's 6 parallel jobs start simultaneously they all
request the same URL from the same runner IP, and occasionally 1–2 jobs
come back with HTTP 403 (`curl: (22)`) and fail before any tests run.

Observed on PR #153's first Test run
([24716620066](https://github.com/aidanns/agent-auth/actions/runs/24716620066)):
2 of 6 jobs failed at this step; a re-run without changes was all green.

## Approach

Two complementary fixes, applied together in the action's "Install
systems-engineering" step. Both apply to the same curl invocation — no
new step, no new input, no extra orchestration.

1. **Authenticate via `GITHUB_TOKEN` and the Contents API.** The action
   already takes `github-token` as an input (every workflow passes
   `${{ secrets.GITHUB_TOKEN }}`). Switch the fetch from the anonymous
   raw-content CDN to `api.github.com/repos/{repo}/contents/{path}?ref=...`
   with `Accept: application/vnd.github.raw` and the bearer token.
   Authenticated requests share the 5,000/hr GITHUB_TOKEN budget rather
   than the low anonymous per-IP limit. The installer itself already
   honours `GITHUB_TOKEN` for its own API calls (see
   `gh_curl`/`gh_download` in `aidanns/systems-engineering/install.sh`),
   so forwarding it via `env` authenticates the release-metadata and
   asset downloads too.
2. **Retry with backoff.** Use curl's built-in
   `--retry 2 --retry-delay 2 --retry-all-errors` (3 attempts total,
   with backoff). `--retry-all-errors` is required because the rate-
   limit response is HTTP 4xx, which plain `--retry` ignores. Absorbs
   transient 403s / network hiccups without failing the job.

The fetch-then-pipe-to-bash pattern loses curl's non-zero exit through
the pipe, so download to a tempfile first, verify curl succeeded, then
`bash <tempfile>`.

If `github-token` is empty (the input is declared optional), fall
through to the anonymous raw URL; the retry loop still helps.

Rejected alternatives:

- **Cache the install** via `actions/cache` keyed on
  `systems-engineering-ref`. Adds a cache step per job and does not
  help the first cold-cache run after a ref bump. The two fixes above
  address the root cause directly.
- **Install only in the aggregator job** and share via
  `actions/upload-artifact`. A larger refactor; not justified for a
  flake that only fires ~1/10 pushes.

## Changes

1. `.github/actions/setup-toolchain/action.yml` — rewrite the "Install
   systems-engineering" step to:
   - Use `GITHUB_TOKEN` (passed via `env` from the `github-token`
     input) to fetch `install.sh` through the Contents API when the
     token is non-empty; otherwise fall back to the raw URL.
   - Use `curl --retry 2 --retry-delay 2 --retry-all-errors` for
     built-in retry with backoff (3 attempts total).
   - Write to a tempfile and execute that, so a failed download does
     not silently execute an empty/partial script.
   - Export `GITHUB_TOKEN` to the installer invocation so its internal
     release-metadata / asset downloads are authenticated too.

No workflow changes are required — every caller already passes
`github-token: ${{ secrets.GITHUB_TOKEN }}` to this action.

## Verification

- Action YAML parses cleanly (`actionlint` runs on pre-commit via
  lefthook; CI will confirm).
- Push the branch and confirm the Test workflow's 6 parallel jobs all
  reach the test-running stage without the raw-content 403.

## Skipped plan-template steps

- No design-doc, threat-model, ADR, cybersecurity, or QM/SIL work is
  needed: this is a CI reliability fix inside a composite action. It
  does not change runtime behaviour, security posture, or any
  externally visible surface.
- Post-implementation standards review items in `plan-template.md`
  (coding / service-design / testing / release-and-hygiene) do not
  apply to an action YAML change. `tooling-and-ci.md` is the only
  relevant standard file; the change keeps the existing single-step
  install pattern intact.
