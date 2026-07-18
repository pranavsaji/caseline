#!/usr/bin/env python3
"""Provision a dashboard operator account (sign-in only; there is no self-serve
signup). Creates a row in dashboard_users with a PBKDF2-hashed password.

Usage:
  python scripts/create_dashboard_user.py <email> [password]

If the password is omitted you'll be prompted for it (not echoed). Reads
CASELINE_DATABASE_URL from .env.
"""

from __future__ import annotations

import getpass
import os
import sys

from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.platform.db import Database  # noqa: E402
from api.platform import dashboard_auth  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    email = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) > 2 else getpass.getpass("Password: ")

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
        created = dashboard_auth.create_user(db, email, password)
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
