<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Release-automation bots — overview and bring-up checklist

Three GitHub Apps back the release-automation workflows on this
repo. Each App has its own setup doc covering permissions, secret
rotation, and decommissioning. This doc is the cross-cutting
checklist: what the three Apps are at a glance, the order in which a
maintainer brings them online from a clean state, and the
bypass-actor policy that applies to all three together. Per-App
docs remain authoritative for App-specific detail; this doc links
out rather than duplicating.

## The three Apps at a glance

| App slug / actor login          | Workflow file(s)                                                                                                                                                                               | Permissions                                                                                       | Required secrets                                                           | Main-ruleset bypass? |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | -------------------- |
| `agent-auth-changelog-bot[bot]` | [`changelog-bot.yml`](../../.github/workflows/changelog-bot.yml)                                                                                                                               | See [changelog-bot-setup.md](changelog-bot-setup.md#one-time-registration)                        | `CHANGELOG_BOT_APP_ID`, `CHANGELOG_BOT_PRIVATE_KEY`, `CHANGELOG_BOT_EMAIL` | No                   |
| `agent-auth-merge-bot[bot]`     | [`merge-bot.yml`](../../.github/workflows/merge-bot.yml)                                                                                                                                       | See [merge-bot-setup.md](merge-bot-setup.md#step-1--register-the-agent-auth-merge-bot-github-app) | `MERGE_BOT_APP_ID`, `MERGE_BOT_PRIVATE_KEY`                                | **Yes**              |
| `agent-auth-release-bot[bot]`   | [`release-pr.yml`](../../.github/workflows/release-pr.yml), [`release-tag.yml`](../../.github/workflows/release-tag.yml), [`release-publish.yml`](../../.github/workflows/release-publish.yml) | See [release-bot-setup.md](release-bot-setup.md#one-time-registration)                            | `RELEASE_BOT_APP_ID`, `RELEASE_BOT_PRIVATE_KEY`                            | No                   |

The canonical secret-name shape is `<BOT>_BOT_APP_ID` /
`<BOT>_BOT_PRIVATE_KEY` where `<BOT>` is the short bot name
(`CHANGELOG`, `MERGE`, or `RELEASE`). The changelog-bot also needs
`CHANGELOG_BOT_EMAIL` because its workflow commits to PR branches
and needs a deterministic `git author.email`. Seven secrets total.

## Bring-up checklist

Order matters: install before secrets so the App's installation ID
is resolvable when the bypass-actor step looks it up.

1. **Register all three GitHub Apps.** Follow the per-App setup
   doc for permissions and webhook settings:
   - `agent-auth-changelog-bot` — see
     [changelog-bot-setup.md](changelog-bot-setup.md).
   - `agent-auth-merge-bot` — see
     [merge-bot-setup.md](merge-bot-setup.md).
   - `agent-auth-release-bot` — see
     [release-bot-setup.md](release-bot-setup.md).
2. **Install all three Apps on `aidanns/agent-auth` only.** Not
   *All repositories*. Each App's installation token is scoped to
   the repo it is installed on; widening the install scope would
   broaden the blast radius of a compromised key with no upside.
3. **Add the seven secrets to the repo's Actions secrets**, using
   the canonical names from the table above. Set them in
   [Settings → Secrets and variables → Actions](https://github.com/aidanns/agent-auth/settings/secrets/actions).
   The workflows consume the names verbatim — a typo
   (`MERGE_APP_ID` instead of `MERGE_BOT_APP_ID`, say) silently
   breaks the affected bot at the first run.
4. **Add `agent-auth-merge-bot` — and only `agent-auth-merge-bot` —
   as a bypass actor on the `main` ruleset.** Use *Always*
   bypass-mode. Do **not** add `agent-auth-changelog-bot` or
   `agent-auth-release-bot`: changelog-bot pushes to PR feature
   branches (governed by PR-branch rules, not the `main` ruleset),
   and release-bot pushes to `release/*` branches and tags (also
   not governed by the `main` ruleset). Adding either to the
   bypass list would widen the trust boundary without need. See
   the [bypass-actor policy](#bypass-actor-policy) section below
   for the full reasoning.
5. **Verify each bot end-to-end** using the per-App acceptance
   test:
   - Changelog-bot:
     [Verifying the install](changelog-bot-setup.md#verifying-the-install).
   - Merge-bot:
     [Verifying the bot end-to-end](merge-bot-setup.md#verifying-the-bot-end-to-end).
   - Release-bot: open and merge a PR with a release-bumping
     prefix (`feature:` / `improvement:` / `fix:` / etc.) and
     confirm `release-pr.yml` opens the `release/X.Y.Z` PR and
     `release-tag.yml` pushes the tag on its merge.

## Bypass-actor policy

Why merge-bot needs main-ruleset bypass and the other two do not.
This is the cross-cutting rationale — `merge-bot-setup.md` covers
the merge-bot-specific UI / API mechanics for adding the bypass
entry.

- The `main` ruleset enforces `required_status_checks` with
  `strict_required_status_checks_policy: true` ("Require branches
  to be up to date before merging"). The default `GITHUB_TOKEN`
  cannot bypass `required_status_checks` administration; a GitHub
  App installation can.
- **Bots wait for checks; they do not bypass the checks
  themselves.** Merge-bot only fires once every required check on
  the PR's head SHA is green — see
  [`merge-bot.yml`](../../.github/workflows/merge-bot.yml) and the
  `Verifies every required check is green` step in
  [merge-bot-setup.md](merge-bot-setup.md#what-the-bot-does).
- The bypass exists so the bot's own gating
  (checks-green-on-head-SHA) replaces the ruleset's stricter
  gating (checks-green **and** branch-up-to-date). The bot inspects
  `statusCheckRollup` for the actual head SHA; the ruleset's
  strict-policy check additionally requires a fresh rebase against
  `main`, which would force every bot-merge to be preceded by a
  human rebase round-trip.
- **Tradeoff.** With bypass, the bot can squash-merge a
  slightly-stale-but-green PR (head SHA is green, but a newer
  commit has landed on `main` since the PR last rebased). Without
  bypass, every PR needs rebasing right before bot-merge — that
  re-runs CI on the rebased head, which often takes longer than
  the staleness-induced semantic risk warrants. The
  semantic-risk bound is "what changed on `main` between the PR's
  base and the current `main`"; review at PR time covers it for
  the kinds of changes this repo lands.

The other two Apps push to branches the `main` ruleset does not
govern, so their pushes are subject only to PR-branch / release-
branch rules (signed-commits, status checks at PR merge time)
and bypass-actor configuration is unnecessary.

## Decommissioning the old `bypass_actors` entry

The `main` ruleset's current `bypass_actors` list still carries an
entry from PR #321:

```
actor_id: 3465211
actor_type: Integration
```

This is the now-decommissioned `semantic-release-agent-auth` App
(the previous release-automation App, superseded by
`agent-auth-release-bot` per
[ADR 0026](../../design/decisions/0026-semantic-release-autorelease.md)
and the workspace-release model in
[ADR 0035](../../design/decisions/0035-workspace-release-model.md)).
The semantic-release App was removed when the workspace release
model landed; the `bypass_actors` entry was not cleaned up at the
time.

Remove the stale entry once `agent-auth-merge-bot` has been added
as a bypass actor (step 4 above). Either via the UI
(*Settings → Rules → Rulesets → `main` → Bypass list*) or via the
API:

```bash
# Read the current ruleset, drop the stale Integration entry,
# write the trimmed list back. Keep agent-auth-merge-bot's
# Integration entry intact.
gh api 'repos/aidanns/agent-auth/rulesets/<RULESET_ID>' \
  --jq '.bypass_actors | map(select(.actor_id != 3465211))'
# … then PATCH the ruleset with the trimmed list (see
# merge-bot-setup.md for the PATCH payload shape).
```

Confirm the entry is gone:

```bash
gh api 'repos/aidanns/agent-auth/rulesets/<RULESET_ID>' \
  --jq '.bypass_actors[] | select(.actor_id == 3465211)'
# (no output expected)
```

## Per-App docs are authoritative

This doc is the deployment checklist + cross-cutting policy
explainer. For anything App-specific — App permissions, key
rotation, decommissioning, the operational mechanics of adding the
merge-bot bypass-actor entry — the per-App docs are the source of
truth:

- [changelog-bot-setup.md](changelog-bot-setup.md)
- [merge-bot-setup.md](merge-bot-setup.md)
- [release-bot-setup.md](release-bot-setup.md)

If a per-App detail conflicts with this doc, the per-App doc
wins; please open an issue so this overview can be brought back
into agreement.
