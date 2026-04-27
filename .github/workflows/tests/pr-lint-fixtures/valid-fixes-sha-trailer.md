==COMMIT_MSG==
Use constant-time HMAC comparison in parse_token.

Switch to `hmac.compare_digest` so the comparison takes the same
number of cycles regardless of which byte differs.

Fixes: 9c4f1a2b3d5e ("improvement(tokens): inline parse_token hot path")
Closes #3
Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>
==COMMIT_MSG==
