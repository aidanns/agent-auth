==COMMIT_MSG==
Use constant-time HMAC comparison in parse_token.

The previous implementation used `==`, exposing a timing oracle.

Fixes: 9c4f1 (broken comparison)
Closes #2
Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>
==COMMIT_MSG==
