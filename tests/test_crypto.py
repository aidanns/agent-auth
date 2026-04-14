"""Tests for AES-256-GCM field encryption."""

import os

import pytest

from agent_auth.crypto import decrypt_field, encrypt_field


@pytest.mark.covers_function("Encrypt Field", "Decrypt Field")
def test_round_trip(encryption_key):
    plaintext = b"sensitive-data-here"
    ciphertext = encrypt_field(plaintext, encryption_key)
    assert ciphertext != plaintext
    assert decrypt_field(ciphertext, encryption_key) == plaintext


@pytest.mark.covers_function("Encrypt Field")
def test_different_nonces_produce_different_ciphertext(encryption_key):
    plaintext = b"same-data"
    ct1 = encrypt_field(plaintext, encryption_key)
    ct2 = encrypt_field(plaintext, encryption_key)
    assert ct1 != ct2
    assert decrypt_field(ct1, encryption_key) == plaintext
    assert decrypt_field(ct2, encryption_key) == plaintext


@pytest.mark.covers_function("Decrypt Field")
def test_wrong_key_fails(encryption_key):
    plaintext = b"test-data"
    ciphertext = encrypt_field(plaintext, encryption_key)
    wrong_key = os.urandom(32)
    try:
        decrypt_field(ciphertext, wrong_key)
        assert False, "Should have raised an exception"
    except Exception:
        pass


@pytest.mark.covers_function("Encrypt Field", "Decrypt Field")
def test_empty_plaintext(encryption_key):
    ciphertext = encrypt_field(b"", encryption_key)
    assert decrypt_field(ciphertext, encryption_key) == b""
