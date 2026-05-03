<!--
The bare `Closes #N` form (no colon) is rejected by the validator
since issue #566 — only the canonical `Closes: #N` (with colon) is
accepted in the trailer block. Two PRs landed in the same week using
the two different forms (#563 used the bare form, #564 used the
canonical), making clear that the historic two-form acceptance was
just an inconsistency tax.

This fixture pins the negative-path contract: a body that would have
passed pre-#566 must now fail. Pairs with the colon-form positive
coverage in `valid-minimal.md` and `valid-template-default.md`.
-->

==COMMIT_MSG==
The thing is small but useful.

Closes #486
Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>
==COMMIT_MSG==

## Review notes

- ran `task check`
