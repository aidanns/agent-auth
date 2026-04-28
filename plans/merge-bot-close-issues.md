<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# merge-bot — close linked issues after squash-merge

Closes #429. Adds an issue-closing step to
`.github/workflows/merge-bot.yml` that runs after the existing
`PUT /pulls/{n}/merge` call so a `Closes #N` (or `Fixes`/`Resolves`)
trailer in the squash commit body actually closes its linked issue
on merge — instead of staying open until an orchestrator-side
`gh issue close` runs.

## Context

GitHub's auto-close-on-`Closes #N` does not fire for App-token-
mediated `PUT /pulls/{n}/merge` calls, even when the squash commit
body carries the trailer correctly. Confirmed deterministically on
PRs #350 / #354 / #423 across two days. The current workaround is a
manual `gh issue close` step in every PR-shepherding workflow
(`/workflow:implement` Phase 6 step 2 and the equivalent in
`/work-issues`); when the orchestrator skips that step the linked
issue silently stays OPEN and there is no observable signal that
the tracker has drifted from reality.

The fix moves the closure into the merge-bot itself: after the
merge API returns 200 the bot parses the squash commit body for
auto-close keyword references, then calls
`PATCH /repos/{owner}/{repo}/issues/{N}` with `state: closed` and
posts a closing comment. The orchestrator-side workaround can then
be downgraded to a defensive sanity-check (or removed; that's a
separate concern outside this PR — issue body's "Once this issue
ships..." note).

## Proposal

Three workflow-side changes plus a docs/ADR refresh:

### Parse the squash commit body for auto-close references

A new step after `Call PUT /pulls/{n}/merge` reads the body that the
bot just pasted (the file at `${{ steps.extract.outputs.commit_message_path }}`
already lives on disk, so we don't need to re-derive it from the
merge response).

The keyword set matches what GitHub's UI auto-closer recognises —
`closes/closed/closing/fix/fixed/fixes/fixing/resolve/resolved/resolves/resolving`,
case-insensitive. References take two shapes:

- Same-repo: `Closes #N` — closeable.
- Cross-repo: `Closes other-org/other-repo#N` — App installation
  token is not scoped to other repos; log the skip via
  `::notice::` and move on.

A trailing colon (`Closes:` — git-trailer form) is accepted in
addition to the bare keyword. Punctuation after the issue number
(`Closes #N.`) is tolerated.

Implementation: a small Python helper
(`scripts/parse-close-keywords.py`) reads a body file from a
positional path argument and writes one issue number per line to
stdout for same-repo references; cross-repo references go to
stderr as `::notice::` lines (so they surface in the workflow
output but don't pollute stdout, which the workflow loops over).
Python rather than inline awk/grep because:

- The keyword set has 11 entries with case-insensitive matching;
  a Python `re.IGNORECASE` regex is one line, an awk equivalent
  is fragile.
- Body content can include backticks / `$(...)` / shell
  metacharacters — running it through an inline shell pipeline
  invites injection. Reading the body via `Path.read_text` with
  the path passed as an argv keeps the shell out of the loop.
- A standalone script is unit-testable from `tests/` without
  spawning a runner — same pattern the existing
  `extract-commit-msg-block.py` already uses.

### Call `PATCH /repos/.../issues/{N}` per same-repo reference

For each issue number returned by the helper:

1. `gh api` is used to call
   `PATCH /repos/${GITHUB_REPOSITORY}/issues/${N}` with `state: closed`.
   The merge-bot App's installation token is the auth credential
   (the same token already used for the merge call).
2. A closing comment of the form
   `Closed by merge of PR #<P> (squash commit <sha>).` is posted
   via `gh api POST /repos/.../issues/{N}/comments`. The squash
   commit SHA is read from the merge API response.

Idempotency: an already-closed issue should not get a duplicate
comment. Before posting, the step queries `gh api repos/.../issues/{N} --jq .state`;
if `closed` already, the step skips both the PATCH and the comment
with a `::notice::` line. (The PATCH itself is harmless when the
state is already `closed`, but skipping the comment matters — a
duplicate comment on an already-closed issue is observable noise.)

Failure handling: a 404 (issue not found, e.g. typo in `Closes #99999`)
is logged via `::warning::` and the step continues to the next
reference; it does not fail the merge job. The merge has already
landed; failing the workflow at this point would not roll it back
and would only generate noise. A 5xx or other unexpected error is
likewise warning-logged; the bot's job is best-effort issue
closure, not a gate.

### Cross-repo references — log and skip

The bot's installation token is scoped to `aidanns/agent-auth`
only, so any `Closes other-org/other-repo#N` reference is
unactionable. The helper emits these as `::notice::` lines so they
appear in the workflow run output and a maintainer can close them
by hand if appropriate. No retry, no failure.

### Permissions impact — `issues: write` on the App installation

The merge-bot App currently has:

- `pull-requests: write` (for `PUT /pulls/{n}/merge` + comments)
- `contents: write` (for `PUT /pulls/{n}/update-branch`)
- `metadata: read`
- `checks: read`
- `workflows: write` (for PRs touching `.github/workflows/`)

`PATCH /repos/.../issues/{N}` requires `issues: write` on the App
installation. This is a deliberate, narrowly-scoped widening:

- The App can transition issue state and post issue comments.
- It still cannot delete issues or modify other issue fields beyond
  what the API endpoint exposes.
- The App is installed only on `aidanns/agent-auth`, so the grant
  is scoped to this repo.

`docs/release/merge-bot-setup.md` Step 1 lists the App
permissions; this PR updates that list. The actual permissions
update on the live App is an operational step the maintainer
performs (GitHub will prompt the App's installer to accept the
expanded scope on next install / the next time the App settings
are saved).

## Design decisions

### Why parse the squash commit body, not the merge response?

The `PUT /pulls/{n}/merge` response contains a `message` field with
the squash commit body, but the bot already has the same content
on disk via the existing `extract` step (the same file it pasted
into the merge call). Reading from disk:

- Keeps the body source single — same file the merge call used,
  so a divergence between "what the bot merged" and "what the bot
  parsed for issue refs" is structurally impossible.
- Avoids a second `gh api` round-trip to fetch the merge response
  body.
- Sidesteps the question of how the merge endpoint normalizes
  the body (CRLF vs LF, trailing newline trimming) — what we
  parsed and what we pasted are the same bytes.

### Why a separate script, not inline jq?

Inline shell/jq parsing on a body that may contain backticks /
`$(...)` / shell metacharacters is a CodeQL
`js/actions/command-injection` red flag — even with `env:` binding,
piping into `jq` over stdin is fine but writing the body content
*into* a jq filter argument or a shell pipeline that uses
`echo "${BODY}"` is not. A standalone `python3` script reading the
body file via `Path.read_text` keeps the shell out of the loop.

The existing `extract-commit-msg-block.py` script follows the same
pattern; the new `parse-close-keywords.py` script slots into the
same `scripts/` directory and is invoked with the same shape:

```bash
python3 scripts/parse-close-keywords.py "${COMMIT_MESSAGE_PATH}"
```

### Why `::notice::` for cross-repo, `::warning::` for 404?

GitHub Actions surface levels:

- `::notice::` — informational, appears in the workflow run log
  but doesn't fail anything. Right level for "we saw this and
  intentionally skipped it".
- `::warning::` — appears in the run summary as a warning marker
  and shows up in the PR's checks UI. Right level for "this
  *should* have worked but didn't".

A cross-repo reference is a deliberate skip and should be a notice.
A 404 on a same-repo reference indicates the contributor likely
typo'd the issue number; surfacing it as a warning makes it
discoverable without failing the merge.

### Why best-effort, not gate the merge step?

The merge has already landed by the time the issue-closing step
runs — failing the workflow would not roll back the merge, and the
issue closure is downstream cleanup, not a release-path gate. A
hard fail at this point would surface as a red merge-bot run on a
PR that already merged successfully, which is a worse signal than a
warning-only log line on the same run.

The merge call itself remains the gating step. Issue closure is a
post-condition, not a precondition.

### Closing-comment shape

`Closed by merge of PR #<P> (squash commit <sha>).` — chosen because:

- The PR number is the most-discoverable reverse-link from the
  issue back to the work that closed it.
- The squash commit SHA pins the closure to a specific commit on
  `main`; the PR number alone wouldn't tell a reader which commit
  on `main` carries the change (squash-merges produce a single
  commit, so the SHA is unambiguous).
- The trailing period matches the punctuation style of the other
  bot comments (`Claude: Merged via bot.`).

The comment is plain text; no `Claude: ` prefix because this is a
machine-generated audit trail line on the issue, not an
agent-author message on the PR. (The `Claude: ` prefix convention
applies to PR comments authored by Claude-driven workflows; the
merge-bot's own machine messages on issues are a different
register.)

### Keyword set lives in the helper script, not the workflow

Hard-coding the 11 keywords in inline workflow YAML would make
test coverage hard. Locating them in `parse-close-keywords.py` as
a module-level constant lets the test suite exercise every keyword
plus edge cases (case sensitivity, trailing punctuation, embedded
references in body prose vs trailer position).

### Position-independence: trailer-only or body-anywhere?

GitHub's UI auto-closer matches anywhere in the PR description /
commit body, not only in the trailer block. To match that
behaviour the helper scans the entire commit body, not only the
trailer block. This means a `Closes #N` reference inside body
prose (e.g. "this builds on the work in #350 — closes the gap
left by that PR — closes #429") would be matched. Acceptable: the
keyword set is conservative enough that incidental prose hits are
rare, and this matches users' expectations from the GitHub UI.

(The validator's `GITHUB_KEYWORD_RE` is anchored at line start —
that's a *validation* concern, not the auto-close-matching
concern. Don't share the regex.)

### Why bash loop over Python invocations?

The helper writes one issue number per line to stdout; the
workflow loops over those lines via `mapfile -t issues < <(python3 ...)`
and runs the `gh api` close calls in bash. Doing the gh-api calls
inside Python would mean reimplementing token plumbing (the App
token is in `${GH_TOKEN}` env, which `gh` consumes natively). Bash
loop + `gh api` is the simpler boundary.

### Where the new step lives in the workflow

Immediately after `Post success comment` (the existing terminal
step on the success path). Putting it after the success comment
means a failure in the issue-closing step doesn't cancel the
"merged" comment. The new step is also gated on
`steps.merge_call.outputs.merged == 'true'` so it doesn't run on
the `already` path (the issue should have been closed by the
prior trigger that did the actual merge).

## Test plan

Static checks:

- [ ] `yq .github/workflows/merge-bot.yml > /dev/null` parses
  cleanly.
- [ ] `python3 scripts/parse-close-keywords.py --help` prints
  usage.
- [ ] `pytest tests/test_parse_close_keywords.py` passes.
- [ ] Unit tests cover:
  - same-repo `Closes #N` (capitalised).
  - same-repo `closes #N`, `CLOSES #N`, `Closes: #N` (case +
    colon variants).
  - all 11 keywords (`closes`, `closed`, `closing`, `fix`,
    `fixed`, `fixes`, `fixing`, `resolve`, `resolved`,
    `resolves`, `resolving`).
  - multiple references in one body (`Closes #1\nCloses #2`).
  - cross-repo `Closes other-org/other-repo#N` — emitted to
    stderr as `::notice::`, NOT to stdout.
  - trailing punctuation tolerance (`Closes #N.`).
  - body prose containing the keyword as a non-keyword word
    (e.g. "fixes a bug in the X module" — must NOT match
    without a `#N` reference).
  - empty body — exits 0 with empty stdout.
  - body with no auto-close references — exits 0 with empty
    stdout.
- [ ] The merge-bot workflow's new `Close linked issues` step:
  - Runs after `Post success comment`.
  - Is gated on `steps.merge_call.outputs.merged == 'true'`
    (NOT `'true' || 'already'`).
  - Loops over the helper's stdout via `mapfile -t`.
  - Skips already-closed issues (one fewer comment).
  - Falls back to `::warning::` on 404.
- [ ] `docs/release/merge-bot-setup.md` Step 1 lists `Issues: Read & write` in the App permissions table.
- [ ] `docs/release/bots-overview.md`'s App permissions row /
  link still points to the merge-bot setup doc (no
  copy-paste of permissions in the overview, so nothing to
  drift).
- [ ] ADR 0038 has a one-paragraph amendment under "Decision"
  or "Consequences" describing the issue-closing
  responsibility.
- [ ] `changelog/@unreleased/pr-<N>-merge-bot-close-issues.yml`
  exists with `type: improvement` and links to issue #429
  and this PR.

Live smoke (only verifiable post-merge):

- [ ] After this PR merges, issue #429 transitions to CLOSED
  with a `Closed by merge of PR #<P> (squash commit <sha>).`
  comment, *without* an orchestrator-side `gh issue close`
  step. (The orchestrator running this issue still calls
  `gh issue close` defensively per the existing workflow;
  the assertion is that the bot's closure happens *first*
  and the orchestrator's defensive call is a no-op.)

## Design and verification

- **Verify implementation against design doc** — ADR 0038
  describes the merge mechanism but pre-dates the issue-closing
  responsibility. This PR amends 0038 with a single-paragraph
  note under "Decision" referencing the auto-close-on-App-token
  failure and the bot's new responsibility.
- **Threat model** — small, deliberate widening of the App's
  installation permissions: `issues: write` on the
  `aidanns/agent-auth` repo only. The trust boundary is
  unchanged (same App, same repo, same short-lived token); the
  *capability* expands to closing issues and posting issue
  comments. Documented in the setup doc's permissions list and
  in the ADR amendment.
- **PIR** — N/A (not remediating a confirmed vulnerability).
- **ADR** — amend 0038 with the issue-closing responsibility;
  no new ADR (the capability is incremental on an existing
  decision).
- **Cybersecurity standard compliance** — N/A
  (workflow change; no application-layer auth surface).
- **QM / SIL compliance** — N/A.

## Post-implementation standards review

- **`coding-standards.md`** — applied to `parse-close-keywords.py`
  (verb name on the script function, NewType for IssueNumber if
  it sharpens types, dataclass for the parsed reference shape if
  the surface warrants it).
- **`service-design.md`** — N/A (not a service).
- **`release-and-hygiene.md`** — hand-authored changelog YAML
  required (improvement-tier); apply the `automerge` label after
  CI green; DCO sign-off on every commit.
- **`testing-standards.md`** — unit tests cover the parser's
  public surface (the CLI's stdout/stderr contract). No internal
  state to test.
- **`tooling-and-ci.md`** — no new `uses:` references in the
  workflow change; existing SHA pins unchanged.
