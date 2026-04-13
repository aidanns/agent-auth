"""AES-256-GCM field-level encryption for sensitive database columns."""

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12


def encrypt_field(plaintext: bytes, key: bytes, aesgcm: AESGCM | None = None) -> bytes:
    """Encrypt plaintext using AES-256-GCM.

    Returns nonce (12 bytes) || ciphertext || tag (16 bytes).
    Pass a pre-constructed AESGCM instance to avoid recreating it per call.
    """
    nonce = os.urandom(NONCE_SIZE)
    if aesgcm is None:
        aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt_field(ciphertext: bytes, key: bytes, aesgcm: AESGCM | None = None) -> bytes:
    """Decrypt ciphertext produced by encrypt_field.

    Pass a pre-constructed AESGCM instance to avoid recreating it per call.
    """
    nonce = ciphertext[:NONCE_SIZE]
    data = ciphertext[NONCE_SIZE:]
    if aesgcm is None:
        aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, data, None)
