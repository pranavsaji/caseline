"""Secrets cipher + session store implementations."""

import time

import pytest

from api.platform.secrets import FernetCipher, make_cipher
from api.platform.session_state import InMemorySessionStore


def test_fernet_round_trip():
    cipher = FernetCipher(FernetCipher.generate_key())
    secrets = {"access_token": "tok", "refresh_token": "ref", "nested": {"n": 1}}
    ciphertext = cipher.encrypt(secrets)
    assert "tok" not in ciphertext
    assert cipher.decrypt(ciphertext) == secrets


def test_wrong_key_cannot_decrypt():
    from cryptography.fernet import InvalidToken

    ciphertext = FernetCipher(FernetCipher.generate_key()).encrypt({"a": 1})
    other = FernetCipher(FernetCipher.generate_key())
    with pytest.raises(InvalidToken):
        other.decrypt(ciphertext)


def test_make_cipher_requires_a_key(monkeypatch):
    monkeypatch.delenv("CASELINE_SECRETS_KEY", raising=False)
    monkeypatch.delenv("CASELINE_KMS_KEY_NAME", raising=False)
    with pytest.raises(RuntimeError, match="No secrets key"):
        make_cipher()


def test_in_memory_store_ttl():
    store = InMemorySessionStore()
    store.set("k", {"v": 1})
    assert store.get("k") == {"v": 1}
    store.set("short", {"v": 2}, ttl_seconds=1)
    assert store.get("short") == {"v": 2}
    # simulate expiry without sleeping
    expires_at, value = store._data["short"]
    store._data["short"] = (time.monotonic() - 1, value)
    assert store.get("short") is None
    store.delete("k")
    assert store.get("k") is None


def test_redis_store_round_trip_if_available():
    import redis as redis_lib

    from api.platform.session_state import RedisSessionStore

    try:
        store = RedisSessionStore("redis://localhost:6379/15", prefix="caseline-test:")
        store._redis.ping()
    except redis_lib.exceptions.ConnectionError:
        pytest.skip("no local redis")
    try:
        store.set("k", {"firm": "a"}, ttl_seconds=30)
        assert store.get("k") == {"firm": "a"}
        store.delete("k")
        assert store.get("k") is None
    finally:
        store._redis.close()
