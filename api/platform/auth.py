"""API gateway concerns: firm service-token auth + per-token rate limiting.

Tokens are opaque (``cl_`` + 32 random url-safe bytes) and stored only as
sha256 hashes. A request's bearer token resolves to a firm_id, which becomes
the RLS context for every query that request makes — auth and tenancy are
the same decision made once.

The in-process rate limiter is a request-path backstop; production fronting
(Cloud Armor / API gateway) does the heavy lifting.
"""

from __future__ import annotations

import hashlib
import secrets as pysecrets
import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import HTTPException, Request

from api.platform.db import Database

TOKEN_PREFIX = "cl_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(
    db: Database, firm_id: str, name: str = "default", scopes: list[str] | None = None
) -> str:
    """Create a service token for a firm. The raw token is returned exactly
    once and never stored. ``scopes`` grants beyond the default surface —
    e.g. ``transcripts:raw`` for unredacted transcript access."""
    token = TOKEN_PREFIX + pysecrets.token_urlsafe(32)
    with db.admin() as conn:
        conn.execute(
            "INSERT INTO firm_tokens (firm_id, name, token_hash, scopes) VALUES (%s, %s, %s, %s)",
            (firm_id, name, _hash(token), scopes or []),
        )
    return token


def resolve_token(db: Database, token: str) -> tuple[str, list[str]] | None:
    """Return (firm_id, scopes) for a live token, or None."""
    if not token.startswith(TOKEN_PREFIX):
        return None
    with db.admin() as conn:
        row = conn.execute(
            "SELECT firm_id, scopes FROM firm_tokens WHERE token_hash = %s AND revoked_at IS NULL",
            (_hash(token),),
        ).fetchone()
    return (str(row["firm_id"]), list(row["scopes"] or [])) if row else None


def revoke_token(db: Database, firm_id: str, name: str) -> int:
    with db.admin() as conn:
        cur = conn.execute(
            "UPDATE firm_tokens SET revoked_at = now()"
            " WHERE firm_id = %s AND name = %s AND revoked_at IS NULL",
            (firm_id, name),
        )
        return cur.rowcount


class RateLimiter:
    """Sliding-window limiter keyed by token hash."""

    def __init__(self, limit: int = 300, window_seconds: float = 60.0):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


@dataclass
class AuthedFirm:
    firm_id: str
    scopes: tuple[str, ...] = ()

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return header[7:].strip()


def require_firm(request: Request) -> AuthedFirm:
    """FastAPI dependency: bearer token -> firm identity (the RLS context)."""
    token = bearer_token(request)
    platform = request.app.state.platform
    if not platform.rate_limiter.allow(_hash(token)):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    cached = platform.session_store.get(f"token:{_hash(token)}")
    if cached:
        return AuthedFirm(firm_id=cached["firm_id"], scopes=tuple(cached.get("scopes", ())))
    resolved = resolve_token(platform.db, token)
    if resolved is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked token")
    firm_id, scopes = resolved
    platform.session_store.set(
        f"token:{_hash(token)}", {"firm_id": firm_id, "scopes": scopes}, ttl_seconds=60
    )
    return AuthedFirm(firm_id=firm_id, scopes=tuple(scopes))


def require_admin(request: Request) -> None:
    """Platform-admin endpoints (onboarding) are gated by a deploy-level
    shared secret, not firm tokens."""
    expected = request.app.state.platform.admin_token
    provided = request.headers.get("x-admin-token", "")
    if not expected or not pysecrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Admin token required")
