<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

<!--
PR title (what this issue's `pr-title` lint enforces) must use one of:

  feature: | improvement: | fix: | break: | deprecation: | migration: | chore:

Optional `(scope)` is allowed (e.g. `feature(ci): add pr-lint workflow`).
The PR title becomes the squash-merge commit subject.

The `==COMMIT_MSG==` block below becomes the squash-merge commit body.
The `## Review notes` section is for the reviewer only — it does NOT
enter git history. See CONTRIBUTING.md → "Writing PRs" for a worked
example. The split is enforced by .github/workflows/pr-lint.yml.

While the merge bot (#291) is still pending, the maintainer must paste
the contents of the ==COMMIT_MSG== block (everything between the two
markers, exclusive) into the squash-merge dialog at merge time. See
docs/release/rollout-pr-template.md.
-->

<!--
Author the squash-merge commit body inside the ==COMMIT_MSG== block
below. Rules (enforced by .github/workflows/pr-lint.yml):

- Lines wrap at <= 72 chars.
- No markdown headings (#), bullet lists (-, *, +), numbered lists,
  or task checkboxes inside this block.
- If a `BREAKING CHANGE:` footer is present, it must be on the last
  non-`Signed-off-by:` line.
- Trailers (`Closes`, `Co-authored-by`, `Signed-off-by`) follow the
  git-trailer format `Token: value`. `Closes #N` (no colon) is also
  accepted for compatibility with the existing CHANGELOG style.

The block below is intentionally empty — the lint will fail until
you replace this comment with the body.
-->

==COMMIT_MSG==
==COMMIT_MSG==

<!--
==CHANGELOG_MSG==/==NO_CHANGELOG== markers are reserved for #298 and
are inert in this template. Do not add a marker — the lint will
ignore it for now and the merge bot (#291) will reject the PR once
the marker convention is active.
-->

## Review notes

<!--
Anything the reviewer needs that should NOT enter git history:
test plan, screenshots, links to design docs, deploy steps, gotchas.
This section is dropped at merge time.
-->

### Test plan

<!-- Checklist of verification steps the reviewer can re-run. Prefer
concrete task commands (e.g. `task check`, `task test`) over prose. -->
