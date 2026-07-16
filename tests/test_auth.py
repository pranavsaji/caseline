"""Token auth, admin gating, and rate limiting on the v1 API."""

from fastapi.testclient import TestClient

from api.main import PlatformContext, create_app
from api.platform.auth import RateLimiter
from tests.conftest import ADMIN_TOKEN


def test_missing_token_is_401(v1_client, firm):
    assert v1_client.get("/v1/calls").status_code == 401


def test_garbage_token_is_401(v1_client, firm):
    r = v1_client.get("/v1/calls", headers={"Authorization": "Bearer cl_not_a_real_token"})
    assert r.status_code == 401


def test_valid_token_resolves_firm(v1_client, firm):
    r = v1_client.get("/v1/calls", headers=firm["headers"])
    assert r.status_code == 200
    assert r.json() == []


def test_admin_endpoints_require_admin_token(v1_client, firm):
    r = v1_client.post("/v1/admin/firms", json={"name": "X"})
    assert r.status_code == 401
    r = v1_client.post(
        "/v1/admin/firms", json={"name": "X"}, headers={"X-Admin-Token": "wrong"}
    )
    assert r.status_code == 401
    # firm bearer tokens do not grant admin access either
    r = v1_client.post("/v1/admin/firms", json={"name": "X"}, headers=firm["headers"])
    assert r.status_code == 401


def test_second_token_can_be_issued_and_used(v1_client, firm):
    r = v1_client.post(
        f"/v1/admin/firms/{firm['firm_id']}/tokens",
        json={"name": "dashboard"},
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert r.status_code == 200
    token = r.json()["token"]
    assert token != firm["token"]
    r = v1_client.get("/v1/leads", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_rate_limit_returns_429(tmp_path, platform, firm):
    tight = PlatformContext(
        db=platform.db,
        session_store=platform.session_store,
        sms=platform.sms,
        cipher=platform.cipher,
        rate_limiter=RateLimiter(limit=3),
        admin_token=platform.admin_token,
    )
    app = create_app(db_path=str(tmp_path / "rl.db"), platform=tight)
    with TestClient(app) as client:
        statuses = [
            client.get("/v1/calls", headers=firm["headers"]).status_code for _ in range(5)
        ]
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]
