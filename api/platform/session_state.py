"""Live call/session state + config cache.

A call in flight never touches Postgres on the hot path: per-call working
state and the per-firm agent-config cache live here. ``RedisSessionStore``
is the deployment target; ``InMemorySessionStore`` keeps local dev and tests
dependency-free. Same interface, config-swapped.
"""

from __future__ import annotations

import json
import os
import time
from typing import Protocol


class SessionStore(Protocol):
    def get(self, key: str) -> dict | None: ...

    def set(self, key: str, value: dict, ttl_seconds: int | None = None) -> None: ...

    def delete(self, key: str) -> None: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float | None, dict]] = {}

    def get(self, key: str) -> dict | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at is not None and time.monotonic() >= expires_at:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: dict, ttl_seconds: int | None = None) -> None:
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds else None
        self._data[key] = (expires_at, value)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


class RedisSessionStore:
    def __init__(self, url: str, prefix: str = "caseline:"):
        import redis

        self._redis = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = prefix

    def get(self, key: str) -> dict | None:
        raw = self._redis.get(self._prefix + key)
        return json.loads(raw) if raw is not None else None

    def set(self, key: str, value: dict, ttl_seconds: int | None = None) -> None:
        self._redis.set(self._prefix + key, json.dumps(value), ex=ttl_seconds)

    def delete(self, key: str) -> None:
        self._redis.delete(self._prefix + key)


def make_session_store(redis_url: str | None = None) -> SessionStore:
    redis_url = redis_url or os.getenv("CASELINE_REDIS_URL")
    return RedisSessionStore(redis_url) if redis_url else InMemorySessionStore()
