"""Onboard a firm from the command line (design-partner workflow).

Creates the firm, a default intaker agent, and a service token, printing the
token exactly once. Run against the same CASELINE_DATABASE_URL the API uses:

    uv run python scripts/onboard_firm.py --name "Bluebonnet Injury Law" \
        --timezone America/Chicago --cms mock --transfer-number +15125550199

    # Clio credentials from a JSON file (encrypted at rest immediately):
    uv run python scripts/onboard_firm.py --name "..." --cms clio \
        --cms-credentials-file clio_creds.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.platform.auth import issue_token  # noqa: E402
from api.platform.db import Database  # noqa: E402
from api.platform.secrets import make_cipher  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Onboard a firm")
    parser.add_argument("--name", required=True)
    parser.add_argument("--timezone", default="America/Chicago")
    parser.add_argument("--cms", default="mock", choices=["mock", "clio"])
    parser.add_argument("--cms-credentials-file", help="JSON file with provider credentials")
    parser.add_argument("--practice-area", default="personal injury")
    parser.add_argument("--agent-name", default="Caseline")
    parser.add_argument("--transfer-number", default=None)
    args = parser.parse_args()

    load_dotenv()
    dsn = os.getenv("CASELINE_DATABASE_URL")
    if not dsn:
        sys.exit("CASELINE_DATABASE_URL is not set (see .env.example)")

    credentials_enc = None
    if args.cms_credentials_file:
        with open(args.cms_credentials_file) as f:
            credentials_enc = make_cipher().encrypt(json.load(f))

    db = Database(dsn)
    try:
        db.migrate()
        with db.admin() as conn:
            firm = conn.execute(
                "INSERT INTO firms (name, timezone, cms_provider, cms_credentials_enc)"
                " VALUES (%s, %s, %s, %s) RETURNING id",
                (args.name, args.timezone, args.cms, credentials_enc),
            ).fetchone()
            agent = conn.execute(
                "INSERT INTO agents (firm_id, name, role, script_config, routing_rules)"
                " VALUES (%s, %s, 'intaker', %s, %s) RETURNING id",
                (
                    firm["id"],
                    args.agent_name,
                    json.dumps({"practice_area": args.practice_area}),
                    json.dumps({"transfer_number": args.transfer_number}),
                ),
            ).fetchone()
        token = issue_token(db, str(firm["id"]))
    finally:
        db.close()

    print(f"firm_id:  {firm['id']}")
    print(f"agent_id: {agent['id']}")
    print(f"token:    {token}")
    print()
    print("Store the token now — it is not retrievable later.")
    print("Voice worker: set CASELINE_FIRM_TOKEN in the worker's environment.")
    print("Dashboard:    set CASELINE_FIRM_TOKEN in frontend/.env.local.")


if __name__ == "__main__":
    main()
