<!--
The block opens with a Conventional-Commit-shaped first line
(`improvement(ci): wire the foo into the bar`). Post-#478 the block is
body + trailers only; the PR title is the source of the squash commit
subject. A leading subject line in the block would render twice on
`main` (once as the rendered subject, once as the first body line).
The validator rejects this shape with a fix-it pointer to the new
convention.
-->

==COMMIT_MSG==
improvement(ci): wire the foo into the bar

The body explaining why the change exists.

Closes #478
Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>
==COMMIT_MSG==
