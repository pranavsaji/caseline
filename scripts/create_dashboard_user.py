#!/usr/bin/env python3
"""Provision a dashboard operator account (sign-in only; there is no self-serve
signup). Creates a row in dashboard_users with a PBKDF2-hashed password.

Usage:
  python scripts/create_dashboard_user.py <email> [password] [--firm <name-or-id>]

If the password is omitted you'll be prompted for it (not echoed). Reads
CASELINE_DATABASE_URL from .env.

--firm binds the account to one tenant, so signing in with it shows that firm's
data and only that firm's. Without it the account lands on the deploy's default
firm (whatever CASELINE_FIRM_TOKEN points at) — the pre-multi-tenant behaviour.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.platform.db import Database  # noqa: E402
from api.platform import dashboard_auth  # noqa: E402


def _resolve_firm(db: Database, ref: str) -> str:
    """Accept either a firm uuid or an exact firm name, so the caller doesn't
    have to go look up an id to provision an account."""
    with db.admin() as conn:
        row = conn.execute(
            "SELECT id, name FROM firms WHERE id::text = %s OR name = %s", (ref, ref)
        ).fetchone()
    if row is None:
        raise ValueError(f"no firm matching {ref!r}")
    print(f"Binding to firm: {row['name']} ({row['id']})")
    return str(row["id"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a dashboard operator account")
    parser.add_argument("email")
    parser.add_argument("password", nargs="?", help="omit to be prompted (not echoed)")
    parser.add_argument("--firm", help="firm name or uuid to bind this account to")
    args = parser.parse_args()

    email = args.email
    password = args.password or getpass.getpass("Password: ")

    # Prefer an injected env var (e.g. under `railway run` / inside the deploy,
    # which targets the PROD database); fall back to local .env for dev.
    db_url = os.environ.get("CASELINE_DATABASE_URL") or dotenv_values(".env").get(
        "CASELINE_DATABASE_URL"
    )
    if not db_url:
        print("CASELINE_DATABASE_URL not set (env or .env)", file=sys.stderr)
        return 1

    db = Database(db_url)
    try:
        firm_id = _resolve_firm(db, args.firm) if args.firm else None
        created = dashboard_auth.create_user(db, email, password, firm_id=firm_id)
    except dashboard_auth.UserExistsError:
        print(f"An account already exists for {email}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"Created dashboard account: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
