<!--
The canonical issue-close trailer is `Closes: #N` (colon form, since
issue #486 / ADR 0038 amendment 8). The bare `Closes #N` form remains
accepted by the validator's GITHUB_KEYWORD_RE branch so historical
CHANGELOG entries and any in-flight PRs continue to validate; this
fixture pins that contract so a future regression in either parser or
validator that rejects the bare form fails the self-test loop.

Pairs with the colon-form coverage in `valid-minimal.md` and
`valid-template-default.md`.
-->

==COMMIT_MSG==
The thing is small but useful.

Closes #486
Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>
==COMMIT_MSG==

## Review notes

- ran `task check`
