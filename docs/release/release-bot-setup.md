<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Release bot setup

One-time maintainer instructions for the GitHub App that backs the
release pipeline. The bot is the App referenced by
[`release-pr.yml`](../../.github/workflows/release-pr.yml),
[`release-tag.yml`](../../.github/workflows/release-tag.yml), and
[`release-publish.yml`](../../.github/workflows/release-publish.yml).
Identity rationale (why these workflows mint installation tokens
instead of using the default `GITHUB_TOKEN`) is in
[ADR 0026](../../design/decisions/0026-semantic-release-autorelease.md).

This App is **separate** from the
[changelog bot](changelog-bot-setup.md) (PR-branch changelog
authoring) and the [merge bot](merge-bot-setup.md) (squash-merge on
`automerge` label). Each App is scoped to the narrowest set of
permissions it needs so revoking one does not disrupt the others.
For the cross-cutting bring-up checklist that covers all three
release-automation Apps together (and the bypass-actor policy that
distinguishes them), see [`bots-overview.md`](bots-overview.md).

## What the bot does

Each of the three release workflows mints a short-lived
installation token via
[`actions/create-github-app-token`](https://github.com/actions/create-github-app-token)
on the `agent-auth-release-bot` App at the start of the run, then
uses that token for every API and git call below. The actor login
on the resulting events is `agent-auth-release-bot[bot]` instead of
the default `github-actions[bot]`, per
[ADR 0026](../../design/decisions/0026-semantic-release-autorelease.md)'s
release-App identity rationale.

- [`release-pr.yml`](../../.github/workflows/release-pr.yml) — opens
  / refreshes the `release/X.Y.Z` PR on every push to `main` and
  pushes the release branch under the App identity. The default
  `GITHUB_TOKEN` cannot create PRs unless the org/repo setting
  *Allow GitHub Actions to create and approve pull requests* is
  on, and enabling that flag would also let every workflow
  auto-approve PRs — too broad for a repo with DCO and signing
  enforcement.
- [`release-tag.yml`](../../.github/workflows/release-tag.yml) —
  pushes the `vX.Y.Z` tag when a release PR merges. An App token
  is required because tag pushes from the default `GITHUB_TOKEN`
  do **not** fire downstream `on: push: tags:` workflows — the
  SLSA / SBOM / cosign chain in `release-publish.yml` would
  silently break.
- [`release-publish.yml`](../../.github/workflows/release-publish.yml)
  — uploads release assets via `gh release upload` so the
  asset-upload events show `agent-auth-release-bot[bot]` as the
  actor in the audit trail and release timeline, matching the
  other two workflows.

The App authors no commits on `main`. `release-pr.yml`'s release
commit on the `release/X.Y.Z` branch is also attributed to
`agent-auth-release-bot[bot]` as author/committer (the workflow's
`Configure git identity` step looks up the App's bot user ID at
runtime); DCO auto-bypasses the bot identity's
`[bot]@users.noreply.github.com` email per
[`dco.yml`](../../.github/workflows/dco.yml).

## One-time registration

1. Go to [github.com/settings/apps/new](https://github.com/settings/apps/new)
   (user-owned App) and create an App with:

   - **App name**: `agent-auth-release-bot`. The actor login GitHub
     assigns is the slug suffixed with `[bot]`
     (`agent-auth-release-bot[bot]`); the verifying-the-install
     check below keys off this exact string.
   - **Homepage URL**: `https://github.com/aidanns/agent-auth`.
   - **Webhook**: uncheck *Active* — this App does not handle
     events; it is invoked from the release workflows.
   - **Repository permissions**:
     - *Contents*: **Read & write** (push the `release/X.Y.Z`
       branch, push the `vX.Y.Z` tag, upload release assets).
     - *Pull requests*: **Read & write** (open, edit, and close
       the release PR from `release-pr.yml`).
     - *Metadata*: **Read-only** (mandatory when any other repo
       permission is granted).
     - All other permissions: **No access**.
   - **Where can this GitHub App be installed?**: *Only on this
     account*.

2. Click **Create GitHub App**. On the App's settings page:

   - Copy the **App ID** (numeric, top of the page) for step 4.
   - Under **Private keys → Generate a private key**, download the
     `.pem` file. GitHub shows it once.

3. Still on the App's settings page, open **Install App** and
   install it against `aidanns/agent-auth` only — not *All
   repositories*.

4. In the repo's
   [Settings → Secrets and variables → Actions](https://github.com/aidanns/agent-auth/settings/secrets/actions),
   add the two secrets covered in the next section.

## Required secrets

In the repo's
[Settings → Secrets and variables → Actions](https://github.com/aidanns/agent-auth/settings/secrets/actions),
add:

- `RELEASE_BOT_APP_ID` — the numeric App ID from
  [One-time registration](#one-time-registration) step 2.
- `RELEASE_BOT_PRIVATE_KEY` — the **full contents** of the `.pem`
  file from step 2, including the `-----BEGIN/END` markers and the
  trailing newline.

These names match the `<BOT>_BOT_APP_ID` /
`<BOT>_BOT_PRIVATE_KEY` shape used by the merge-bot and
changelog-bot Apps. They are referenced by all three workflows
([`release-pr.yml`](../../.github/workflows/release-pr.yml),
[`release-tag.yml`](../../.github/workflows/release-tag.yml),
[`release-publish.yml`](../../.github/workflows/release-publish.yml));
do not rename them without updating each workflow.

Each workflow's `Check secrets are configured` guard handles three
states:

- Both secrets unset — emits a `::notice::` and skips the run
  (e.g. fork or first-time setup).
- Both set — proceeds.
- Exactly one set — emits a `::error::` (partial / broken
  configuration) and fails the job loudly.

## Bypass-actor policy

The release-bot pushes only to `release/*` branches and tags; it
does **not** need `main`-ruleset bypass. Branch protection on
`release/*` (signed-commits, status checks at PR merge time)
applies at PR merge time, not when the bot's commits land on the
release branch.

The cross-cutting rationale — why merge-bot specifically needs
`main`-ruleset bypass and the other two release-automation Apps do
not — lives in
[`bots-overview.md` § "Bypass-actor policy"](bots-overview.md#bypass-actor-policy).
That section also covers the fresh-rebase-vs-stale-but-green
tradeoff the bypass implies.

## Verifying the install

After the secrets are set, open and merge a PR with a
release-bumping prefix (`feature:`, `improvement:`, `fix:`,
`deprecation:`, `migration:`, or `break:`). The expected
end-to-end signal is one full release cycle attributed to
`agent-auth-release-bot[bot]`:

- `release-pr.yml` opens (or refreshes) the `release/X.Y.Z` PR
  with `agent-auth-release-bot[bot]` as the PR author and as the
  pusher of the release branch. The release commit on the branch
  is also attributed to `agent-auth-release-bot[bot]` as
  author/committer (DCO auto-bypasses the bot's
  `[bot]@users.noreply.github.com` email — see
  [What the bot does](#what-the-bot-does)).
- `release-tag.yml` pushes the `vX.Y.Z` tag on the release-PR
  merge under `agent-auth-release-bot[bot]`. The tag push fires
  `release-publish.yml` because the App-minted token (unlike the
  default `GITHUB_TOKEN`) triggers downstream
  `on: push: tags:` workflows.
- `release-publish.yml`'s `Upload artefacts to GitHub release`
  step records `agent-auth-release-bot[bot]` as the asset-upload
  actor on the GitHub Release timeline.

If any of those signals shows `github-actions[bot]` instead, the
most likely cause is a setup gap: missing secret, App not
installed on the repo, or the workflow's `Check secrets are configured` guard taking the unset path. Each workflow's run log
includes the guard's `::notice::` or `::error::` if the secrets
state is anything other than "both set".

## Rotating the private key

1. On the App's settings page, **Generate a private key** again.
2. Update `RELEASE_BOT_PRIVATE_KEY` in repo Actions secrets with
   the new key.
3. Revoke the old key from the App settings page. No workflow
   change is required. The App's tokens are short-lived (≤ 1
   hour) so the old key stops being useful as soon as the next
   workflow run mints a fresh token.

## Decommissioning

1. Uninstall the App from `aidanns/agent-auth` (App settings →
   *Install App* → *Uninstall*).
2. Delete the `RELEASE_BOT_APP_ID` and `RELEASE_BOT_PRIVATE_KEY`
   secrets.
3. Each release workflow's `Check secrets are configured` guard
   will now take the both-unset path on its next run, emit a
   `::notice::` pointing here, and skip the rest of the job. No
   workflow change is required to disable the release path.
4. To restore release automation, register a fresh App following
   [One-time registration](#one-time-registration) above and add
   the two secrets back.
