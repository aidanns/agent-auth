"""SQLite token store with field-level encryption for sensitive columns."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agent_auth.crypto import Ciphertext, decrypt_field, encrypt_field
from agent_auth.keys import EncryptionKey


class TokenStore:
    """Persistent storage for token families, tokens, and approval grants."""

    def __init__(self, db_path: str, encryption_key: EncryptionKey):
        self._db_path = db_path
        self._encryption_key = encryption_key
        self._aesgcm = AESGCM(encryption_key)
        self._local = threading.local()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS token_families (
                id TEXT PRIMARY KEY,
                scopes BLOB NOT NULL,
                created_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tokens (
                id TEXT PRIMARY KEY,
                hmac_signature BLOB NOT NULL,
                family_id TEXT NOT NULL REFERENCES token_families(id),
                type TEXT NOT NULL CHECK (type IN ('access', 'refresh')),
                expires_at TEXT NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_tokens_family_id ON tokens(family_id);
        """)

    def _encrypt(self, plaintext: str) -> Ciphertext:
        return encrypt_field(plaintext.encode("utf-8"), self._encryption_key, self._aesgcm)

    def _decrypt(self, ciphertext: Ciphertext) -> str:
        return decrypt_field(ciphertext, self._encryption_key, self._aesgcm).decode("utf-8")

    # -- Token families --

    def create_family(self, family_id: str, scopes: dict[str, str]) -> dict:
        """Create a new token family with the given scopes."""
        now = datetime.now(timezone.utc).isoformat()
        encrypted_scopes = self._encrypt(json.dumps(scopes))
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO token_families (id, scopes, created_at, revoked) VALUES (?, ?, ?, 0)",
            (family_id, encrypted_scopes, now),
        )
        conn.commit()
        return {"id": family_id, "scopes": scopes, "created_at": now, "revoked": False}

    def get_family(self, family_id: str) -> dict | None:
        """Retrieve a token family by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM token_families WHERE id = ?", (family_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "scopes": json.loads(self._decrypt(row["scopes"])),
            "created_at": row["created_at"],
            "revoked": bool(row["revoked"]),
        }

    def list_families(self) -> list[dict]:
        """List all token families."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM token_families ORDER BY created_at DESC").fetchall()
        return [
            {
                "id": row["id"],
                "scopes": json.loads(self._decrypt(row["scopes"])),
                "created_at": row["created_at"],
                "revoked": bool(row["revoked"]),
            }
            for row in rows
        ]

    def mark_family_revoked(self, family_id: str):
        """Mark a token family and all its tokens as revoked."""
        conn = self._get_conn()
        conn.execute("UPDATE token_families SET revoked = 1 WHERE id = ?", (family_id,))
        conn.commit()

    def update_family_scopes(self, family_id: str, scopes: dict[str, str]):
        """Update the scopes on a token family."""
        encrypted_scopes = self._encrypt(json.dumps(scopes))
        conn = self._get_conn()
        conn.execute(
            "UPDATE token_families SET scopes = ? WHERE id = ?",
            (encrypted_scopes, family_id),
        )
        conn.commit()

    # -- Tokens --

    def create_token(
        self,
        token_id: str,
        hmac_signature: str,
        family_id: str,
        token_type: str,
        expires_at: str,
    ) -> dict:
        """Store a new access or refresh token."""
        encrypted_sig = self._encrypt(hmac_signature)
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO tokens (id, hmac_signature, family_id, type, expires_at, consumed) VALUES (?, ?, ?, ?, ?, 0)",
            (token_id, encrypted_sig, family_id, token_type, expires_at),
        )
        conn.commit()
        return {
            "id": token_id,
            "family_id": family_id,
            "type": token_type,
            "expires_at": expires_at,
            "consumed": False,
        }

    def get_token(self, token_id: str) -> dict | None:
        """Retrieve a token by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM tokens WHERE id = ?", (token_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "hmac_signature": self._decrypt(row["hmac_signature"]),
            "family_id": row["family_id"],
            "type": row["type"],
            "expires_at": row["expires_at"],
            "consumed": bool(row["consumed"]),
        }

    def get_tokens_by_family(self, family_id: str) -> list[dict]:
        """Retrieve all tokens for a family."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM tokens WHERE family_id = ?", (family_id,)).fetchall()
        return [
            {
                "id": row["id"],
                "hmac_signature": self._decrypt(row["hmac_signature"]),
                "family_id": row["family_id"],
                "type": row["type"],
                "expires_at": row["expires_at"],
                "consumed": bool(row["consumed"]),
            }
            for row in rows
        ]

    def mark_consumed(self, token_id: str) -> bool:
        """Atomically mark a refresh token as consumed. Returns True if successful (was not already consumed)."""
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE tokens SET consumed = 1 WHERE id = ? AND consumed = 0",
            (token_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
