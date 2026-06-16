"""Tests for password hashing and JWT token utilities."""
import time

import pytest
import jwt as pyjwt

from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.core.config import settings


def test_hash_and_verify_correct_password():
    hashed = hash_password("s3cret!")
    assert verify_password("s3cret!", hashed)


def test_verify_wrong_password_returns_false():
    hashed = hash_password("correct")
    assert not verify_password("wrong", hashed)


def test_hash_is_not_plaintext():
    plain = "mypassword"
    assert hash_password(plain) != plain


def test_two_hashes_of_same_password_differ():
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2  # bcrypt uses random salt


def test_create_and_decode_token_roundtrip():
    token = create_access_token("user-123")
    subject = decode_token(token)
    assert subject == "user-123"


def test_decode_token_with_invalid_signature_raises():
    token = create_access_token("user-abc")
    tampered = token[:-4] + "xxxx"
    with pytest.raises(pyjwt.PyJWTError):
        decode_token(tampered)


def test_decode_expired_token_raises():
    from datetime import timedelta
    token = create_access_token("user-xyz", expires_delta=timedelta(seconds=-1))
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(token)


def test_token_contains_correct_subject():
    token = create_access_token("uuid-999")
    payload = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["sub"] == "uuid-999"
