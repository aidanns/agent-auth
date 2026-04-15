"""AES-256-GCM field-level encryption for sensitive database columns."""

import os
from typing import NewType

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12

# Distinguishes encrypted bytes from arbitrary plaintext bytes at the type
# level. Runtime representation is still ``bytes`` (``nonce || ciphertext ||
# tag``), but callers must go through ``encrypt_field`` / ``decrypt_field`` to
# cross the boundary. This prevents accidentally passing plaintext into a
# store that expects ciphertext, or vice versa.
Ciphertext = NewType("Ciphertext", bytes)


def encrypt_field(plaintext: bytes, key: bytes, aesgcm: AESGCM | None = None) -> Ciphertext:
    """Encrypt plaintext using AES-256-GCM.

    Returns nonce (12 bytes) || ciphertext || tag (16 bytes).
    Pass a pre-constructed AESGCM instance to avoid recreating it per call.
    """
    nonce = os.urandom(NONCE_SIZE)
    if aesgcm is None:
        aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return Ciphertext(nonce + ciphertext)


def decrypt_field(ciphertext: Ciphertext, key: bytes, aesgcm: AESGCM | None = None) -> bytes:
    """Decrypt ciphertext produced by encrypt_field.

    Pass a pre-constructed AESGCM instance to avoid recreating it per call.
    """
    nonce = ciphertext[:NONCE_SIZE]
    data = ciphertext[NONCE_SIZE:]
    if aesgcm is None:
        aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, data, None)
