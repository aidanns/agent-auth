<!--
Trailer values are exempt from the 72-char body wrap. The release-PR
workflow renders a `Signed-off-by:` trailer attributed to the
`agent-auth-release-bot` GitHub App (#398), and the
numeric-id-prefixed GitHub no-reply email used by `[bot]` accounts is
already 60+ chars before the `Signed-off-by: <slug>[bot] <…>` envelope
adds another ~30. Wrapping a `Signed-off-by:` line would also break
`git interpret-trailers --parse`, so the kernel/git convention treats
trailers as one-line-per-trailer regardless of width.

This fixture pins that contract: a body whose body region wraps at 72
but whose trailer is over 72 chars must validate. Pairs with
`invalid-too-wide.md`, which still rejects a wide *body* line.
-->

==COMMIT_MSG==
The foo previously bypassed the bar because of a typo in
config.py; this fix routes every foo through the bar so the
metrics counter actually increments.

Closes: #1
Signed-off-by: agent-auth-release-bot[bot] <123456+agent-auth-release-bot[bot]@users.noreply.github.com>
==COMMIT_MSG==
