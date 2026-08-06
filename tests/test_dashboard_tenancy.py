"""Dashboard accounts are bound to a firm, and that binding is what scopes the
UI's data.

Two things have to hold for a multi-tenant dashboard on one deploy:
  1. login tells the Next server which firm the operator belongs to, and
  2. acting as that firm requires the admin secret — a header alone must never
     be enough, or any caller could read any tenant by guessing a uuid.
"""

import uuid

from api.platform import dashboard_auth
from tests.conftest import ADMIN_TOKEN

PASSWORD = "correct-horse-staple"


def _admin_headers(firm_id: str) -> dict:
    return {"X-Admin-Token": ADMIN_TOKEN, "X-Caseline-Firm-Id": firm_id}


# --- account -> firm binding ---------------------------------------------


def test_login_returns_the_bound_firm(v1_client, platform, firm):
    dashboard_auth.create_user(platform.db, "ops@bluebonnet.example", PASSWORD, firm["firm_id"])
    r = v1_client.post(
        "/v1/dashboard/login",
        json={"email": "ops@bluebonnet.example", "password": PASSWORD},
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["firm_id"] == firm["firm_id"]


def test_unbound_account_logs_in_with_no_firm(v1_client, platform, firm):
    """Accounts predating the binding keep working — they just carry no firm,
    and the Next server falls back to the deploy default for them."""
    dashboard_auth.create_user(platform.db, "legacy@example.com", PASSWORD)
    r = v1_client.post(
        "/v1/dashboard/login",
        json={"email": "legacy@example.com", "password": PASSWORD},
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["firm_id"] is None


def test_wrong_password_still_401(v1_client, platform, firm):
    dashboard_auth.create_user(platform.db, "ops2@bluebonnet.example", PASSWORD, firm["firm_id"])
    r = v1_client.post(
        "/v1/dashboard/login",
        json={"email": "ops2@bluebonnet.example", "password": "wrong"},
        headers=firm["headers"],
    )
    assert r.status_code == 401


def test_two_accounts_resolve_to_their_own_firms(v1_client, platform, firm, second_firm):
    dashboard_auth.create_user(platform.db, "a@example.com", PASSWORD, firm["firm_id"])
    dashboard_auth.create_user(platform.db, "b@example.com", PASSWORD, second_firm["firm_id"])
    resolved = {}
    for email in ("a@example.com", "b@example.com"):
        r = v1_client.post(
            "/v1/dashboard/login",
            json={"email": email, "password": PASSWORD},
            headers=firm["headers"],
        )
        resolved[email] = r.json()["firm_id"]
    assert resolved["a@example.com"] == firm["firm_id"]
    assert resolved["b@example.com"] == second_firm["firm_id"]
    assert resolved["a@example.com"] != resolved["b@example.com"]


# --- acting as a firm is gated by the admin secret -----------------------


def test_admin_token_plus_firm_id_acts_as_that_firm(v1_client, firm):
    r = v1_client.get("/v1/calls", headers=_admin_headers(firm["firm_id"]))
    assert r.status_code == 200
    assert r.json() == []


def test_firm_id_header_without_admin_token_is_rejected(v1_client, firm):
    """The whole isolation guarantee rests on this: naming a firm is not the
    same as being allowed to act as it."""
    r = v1_client.get("/v1/calls", headers={"X-Caseline-Firm-Id": firm["firm_id"]})
    assert r.status_code == 401


def test_firm_id_header_with_wrong_admin_token_is_rejected(v1_client, firm):
    r = v1_client.get(
        "/v1/calls",
        headers={"X-Admin-Token": "not-the-secret", "X-Caseline-Firm-Id": firm["firm_id"]},
    )
    assert r.status_code == 401


def test_firm_bearer_token_cannot_impersonate_another_firm(v1_client, firm, second_firm):
    """A firm's own service token must not become a lever to read a rival's
    data by naming them in the header."""
    r = v1_client.get(
        "/v1/calls",
        headers={**firm["headers"], "X-Caseline-Firm-Id": second_firm["firm_id"]},
    )
    assert r.status_code == 401


def test_unknown_firm_id_is_404(v1_client, firm):
    r = v1_client.get("/v1/calls", headers=_admin_headers(str(uuid.uuid4())))
    assert r.status_code == 404


def test_malformed_firm_id_is_400_not_500(v1_client, firm):
    r = v1_client.get("/v1/calls", headers=_admin_headers("not-a-uuid"))
    assert r.status_code == 400


# --- the payoff: data actually stays separated ---------------------------


def test_dashboard_sessions_see_only_their_own_firms_leads(v1_client, firm, second_firm):
    v1_client.post(
        "/v1/hooks/leads",
        json={"name": "Bluebonnet Caller", "phone": "+15125550111", "source": "web"},
        headers=firm["headers"],
    )
    v1_client.post(
        "/v1/hooks/leads",
        json={"name": "Rival Caller", "phone": "+15125550222", "source": "web"},
        headers=second_firm["headers"],
    )

    mine = v1_client.get("/v1/leads", headers=_admin_headers(firm["firm_id"])).json()
    theirs = v1_client.get("/v1/leads", headers=_admin_headers(second_firm["firm_id"])).json()

    assert [lead["contact_name"] for lead in mine] == ["Bluebonnet Caller"]
    assert [lead["contact_name"] for lead in theirs] == ["Rival Caller"]
