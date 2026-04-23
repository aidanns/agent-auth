# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Declared migrations, in version order.

Every schema change to the token store lands as a new ``Migration``
entry here. Do not modify an applied migration in place — pinning a
prior version is the whole point of the versioned runner.
"""

from agent_auth.migrations.runner import Migration

_INITIAL_UP = """
CREATE TABLE token_families (
    id TEXT PRIMARY KEY,
    scopes BLOB NOT NULL,
    created_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE tokens (
    id TEXT PRIMARY KEY,
    hmac_signature BLOB NOT NULL,
    family_id TEXT NOT NULL REFERENCES token_families(id),
    type TEXT NOT NULL CHECK (type IN ('access', 'refresh')),
    expires_at TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_tokens_family_id ON tokens(family_id);
"""

# Drop in reverse-dependency order: the index and the referencing
# ``tokens`` table before the referenced ``token_families``.
_INITIAL_DOWN = """
DROP INDEX IF EXISTS idx_tokens_family_id;
DROP TABLE IF EXISTS tokens;
DROP TABLE IF EXISTS token_families;
"""

CATALOGUE: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="initial",
        up_sql=_INITIAL_UP,
        down_sql=_INITIAL_DOWN,
    ),
)
