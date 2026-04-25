<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Changelog bot setup

One-time maintainer instructions for the GitHub App that backs
[`changelog-bot.yml`](../../.github/workflows/changelog-bot.yml). The
bot reads the `==CHANGELOG_MSG==` and `==NO_CHANGELOG==` markers from
PR descriptions and either commits a `changelog/@unreleased/*.yml`
file to the PR branch or applies / removes the `no changelog` label.

This App is **separate** from
[`semantic-release-agent-auth`](../../CONTRIBUTING.md#one-time-register-the-semantic-release-agent-auth-github-app)
(release path) and from #291's merge bot App. Each App is scoped to
the narrowest set of permissions it needs so revoking one does not
disrupt the other.

## Why a dedicated GitHub App?

- **Least privilege.** This App only needs `contents: write` on PR
  branches (to commit the YAML) and `pull_requests: write` (to manage
  labels and comments). The merge bot needs `pull_requests: write`
  for the merge API; the release bot needs `contents: write` on `main`
  for the release commit. Each App's installation token is bounded by
  its own permission set.
- **Independent rotation.** Compromise of any one App's private key
  rotates without taking the others offline.
- **Audit clarity.** PR-history events (`actor.login`) name the
  responsible bot directly. The bot's lockout-detection logic relies
  on this — see [ADR 0039](../../design/decisions/0039-bot-mediated-changelog-authoring.md).

## One-time registration

1. Go to
   [github.com/settings/apps/new](https://github.com/settings/apps/new)
   and create a new App with:

   - **App name**: `agent-auth-changelog-bot`. The actor login GitHub
     assigns is the slug suffixed with `[bot]`
     (`agent-auth-changelog-bot[bot]`); the bot's lockout detection
     and label-event filter both key off this exact string. Renaming
     the App requires updating
     [`scripts/changelog/bot.py`](../../scripts/changelog/bot.py)'s
     `DEFAULT_BOT_LOGIN` constant **and** the
     `CHANGELOG_BOT_LOGIN` env override in
     [`.github/workflows/changelog-bot.yml`](../../.github/workflows/changelog-bot.yml).
   - **Homepage URL**: `https://github.com/aidanns/agent-auth`.
   - **Webhook**: uncheck *Active* — this App does not handle events;
     it is invoked from the workflow.
   - **Repository permissions**:
     - *Contents*: **Read & write** (commit the YAML to PR branches).
     - *Pull requests*: **Read & write** (add / remove the
       `no changelog` label, post the `chore:` reminder comment).
     - *Metadata*: **Read-only** (mandatory for any App).
     - All other permissions: **No access**.
   - **Where can this GitHub App be installed?**: *Only on this
     account*.

2. Click **Create GitHub App**. On the App's settings page:

   - Copy the **App ID** (numeric, top of the page) for step 4.
   - Note the **App's bot user ID** (numeric, shown under the App
     name on the App's public profile, or via
     `gh api users/agent-auth-changelog-bot[bot] --jq .id` after
     step 3 below). The bot's git author email is
     `<bot-user-id>+agent-auth-changelog-bot[bot]@users.noreply.github.com`
     per
     [GitHub's bot identity convention](https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-email-preferences/setting-your-commit-email-address);
     we store this email in a separate secret so the workflow doesn't
     have to compute it at runtime.
   - Under **Private keys -> Generate a private key**, download the
     `.pem` file. GitHub shows it once.

3. Still on the App's settings page, open **Install App** and install
   it against `aidanns/agent-auth` only — not *All repositories*.

4. In the repo's
   [Settings -> Secrets and variables -> Actions](https://github.com/aidanns/agent-auth/settings/secrets/actions),
   add three secrets:

   - `CHANGELOG_BOT_APP_ID` — the numeric App ID from step 2.
   - `CHANGELOG_BOT_PRIVATE_KEY` — the **full contents** of the
     `.pem` file from step 2, including the `-----BEGIN/END` markers
     and the trailing newline.
   - `CHANGELOG_BOT_EMAIL` — the GitHub-Apps email
     `<bot-user-id>+agent-auth-changelog-bot[bot]@users.noreply.github.com`,
     with the bot user ID from step 2 substituted in.

## Verifying the install

After the secrets are set, push any branch to the repo and open a PR.
The `Changelog Bot` workflow appears in the PR's check list. The
expected outcomes:

- PR body contains `==NO_CHANGELOG==` (uncommented from the template):
  the `no changelog` label is added.
- PR body contains `==CHANGELOG_MSG==` ... `==CHANGELOG_MSG==`: a new
  commit appears on the PR branch authored by
  `agent-auth-changelog-bot[bot]` adding
  `changelog/@unreleased/pr-<N>-bot-<hash>.yml`.
- PR body contains neither marker and the contributor has not
  hand-authored a YAML: the workflow exits 0 silently;
  `Changelog Lint` will then fail the PR (this is the intentional
  fall-through).

## Branch protection interaction

The bot pushes commits directly to PR branches (not to `main`). If the
`main` ruleset requires signed commits or required-status checks,
those rules apply at merge time, not when the bot's commit lands on
the PR branch — no bypass actor configuration is required for typical
PR-branch ruleset configurations. If the project later adds a
"signed commits required on PR branches" rule, add the
`agent-auth-changelog-bot` App as a bypass actor on that ruleset; the
App's commits to PR branches are not GPG-signed (GitHub's verified
checkmark on App-authored commits is provided by the API, not GPG).

## Rotating the private key

1. On the App's settings page, **Generate a private key** again.
2. Update `CHANGELOG_BOT_PRIVATE_KEY` in repo Actions secrets with
   the new key.
3. Revoke the old key from the App settings page. No workflow change
   is required.

## Decommissioning

1. Uninstall the App from `aidanns/agent-auth` (App settings ->
   *Install App* -> *Uninstall*).
2. Delete the `CHANGELOG_BOT_APP_ID`, `CHANGELOG_BOT_PRIVATE_KEY`,
   and `CHANGELOG_BOT_EMAIL` secrets.
3. Delete `.github/workflows/changelog-bot.yml`. Contributors fall
   back to hand-authoring YAML entries (the schema and PR-time lint
   are not affected).
