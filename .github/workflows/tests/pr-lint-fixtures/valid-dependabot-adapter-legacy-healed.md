<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

<!--
The body the dependabot-adaptor-bot workflow produces when healing a
PR that an earlier version of the workflow already adapted (issue
#551 — the workflow used to inject only `==COMMIT_MSG==`, and the
in-place heal prepends just the missing `==NO_CHANGELOG==` marker
without touching the existing block). Keep this fixture in sync with
the legacy-heal `printf` in `.github/workflows/dependabot-adaptor-bot.yml`
so a regression in either side fails the self-test.
-->

==NO_CHANGELOG==

==COMMIT_MSG==
See the PR description for upstream release notes.

Signed-off-by: dependabot[bot] <support@github.com>
==COMMIT_MSG==

Bumps [actions/setup-python](https://github.com/actions/setup-python) from 5.6.0 to 6.2.0.
- Upstream release notes elided in this fixture.
