"""Dashboard operator accounts: sign up / log in for humans using the UI.

Separate from ``auth.py`` (machine service-token auth): those tokens let the
Next.js server call the backend; these are the people who log into the dashboard.
Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib — no bcrypt/argon2 dep) into
a self-describing ``pbkdf2_sha256$iterations$salt$hash`` string so the parameters
travel with the hash and can be raised later without breaking existing rows.

The signup/login endpoints that call these sit behind ``require_firm`` (only the
Next server, holding the firm token, can reach them), and the Next server manages
the browser session cookie — so raw passwords only ever transit server→backend.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re

from api.platform.db import Database

_PBKDF2_ITERATIONS = 200_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserExistsError(Exception):
    """Signup attempted with an email that already has an account."""


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)  # constant-time
    except (ValueError, AttributeError):
        return False


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def create_user(db: Database, email: str, password: str) -> str:
    """Create a dashboard account. Raises ``ValueError`` on invalid input and
    ``UserExistsError`` if the email is taken. Returns the normalized email."""
    email = _normalize_email(email)
    if not _EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    with db.admin() as conn:
        if conn.execute("SELECT 1 FROM dashboard_users WHERE email = %s", (email,)).fetchone():
            raise UserExistsError()
        conn.execute(
            "INSERT INTO dashboard_users (email, password_hash) VALUES (%s, %s)",
            (email, _hash_password(password)),
        )
    return email


def verify_user(db: Database, email: str, password: str) -> bool:
    """True iff the email exists and the password matches its stored hash."""
    email = _normalize_email(email)
    with db.admin() as conn:
        row = conn.execute(
            "SELECT password_hash FROM dashboard_users WHERE email = %s", (email,)
        ).fetchone()
    return bool(row) and _verify_password(password, row["password_hash"])
