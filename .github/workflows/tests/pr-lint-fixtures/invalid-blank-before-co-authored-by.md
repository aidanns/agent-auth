==COMMIT_MSG==
The body has a blank line between `Closes #N` and the
`Co-Authored-By:` trailer (mixed-case spelling).
`git interpret-trailers --parse` would treat the blank as the
body/trailer boundary and silently drop both `Closes` and the
co-author attribution from the trailer set, so the validator must
reject this shape. The mixed-case `Co-Authored-By:` matches the
canonical `Co-authored-by` token case-insensitively, so this fixture
also pins the case-insensitive token recognition path.

Closes #403

Co-Authored-By: Claude <noreply@anthropic.com>
Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>
==COMMIT_MSG==
