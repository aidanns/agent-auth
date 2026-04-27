==COMMIT_MSG==
Add a thing.

The body has a blank line between `Closes #N` and
`Signed-off-by:`. `git interpret-trailers --parse` would treat the
blank as the body/trailer boundary and silently drop the `Closes`
reference, so the validator must reject this shape.

Closes #400

Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>
==COMMIT_MSG==
