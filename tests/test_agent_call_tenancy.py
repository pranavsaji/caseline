"""A voice call must be recorded against the firm that owns the room.

One agent worker process answers calls for every tenant. Before this, it
authenticated with a single CASELINE_FIRM_TOKEN from its environment, so a call
started from firm B's dashboard had its qualification, consult, and CMS write
filed under firm A — the caller's matter landing in a stranger's system, with
nothing in the UI to reveal it.
"""

import httpx
import pytest

from agent.backend_client import BackendClient
from tests.conftest import ADMIN_TOKEN


@pytest.fixture
def asgi(v1_app):
    return httpx.ASGITransport(app=v1_app)


def _http(asgi):
    return httpx.AsyncClient(transport=asgi, base_url="http://testserver")


# --- the resolver endpoint -----------------------------------------------


def test_resolve_call_firm_returns_owning_firm(v1_client, firm):
    started = v1_client.post("/v1/calls/web-session", headers=firm["headers"])
    if started.status_code == 503:
        pytest.skip("LiveKit not configured in this environment")
    room = started.json()["room"]
    r = v1_client.get(f"/v1/calls/{room}/firm", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert r.status_code == 200, r.text
    assert r.json()["firm_id"] == firm["firm_id"]


def test_resolve_call_firm_requires_admin(v1_client, firm):
    r = v1_client.get("/v1/calls/whatever/firm", headers=firm["headers"])
    assert r.status_code == 401


def test_resolve_call_firm_unknown_room_is_404(v1_client, firm):
    r = v1_client.get("/v1/calls/no-such-room/firm", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert r.status_code == 404


# --- the client that consumes it -----------------------------------------


async def test_for_call_scopes_to_the_owning_firm(asgi, v1_client, firm, second_firm, monkeypatch):
    """The regression this exists to prevent: the worker's env token names one
    firm, the call belongs to another, and the call must follow the room."""
    started = v1_client.post("/v1/calls/web-session", headers=second_firm["headers"])
    if started.status_code == 503:
        pytest.skip("LiveKit not configured in this environment")
    room = started.json()["room"]

    # Worker env is pinned to the *other* firm, as in production.
    monkeypatch.setenv("CASELINE_FIRM_TOKEN", firm["token"])
    monkeypatch.setenv("CASELINE_ADMIN_TOKEN", ADMIN_TOKEN)

    async with _http(asgi) as http:
        client = await BackendClient.for_call(room, client=http)
        assert client.v1
        # Writes made through this client must land in second_firm.
        await client.qualify_lead("2026-06-01", "whiplash", True, True)

    mine = v1_client.get("/v1/leads", headers=firm["headers"]).json()
    theirs = v1_client.get("/v1/leads", headers=second_firm["headers"]).json()
    assert len(theirs) == 1, "call did not land in the firm that owns the room"
    assert mine == [], "call leaked into the worker's env-token firm"


async def test_for_call_falls_back_when_no_admin_token(asgi, firm, monkeypatch):
    """Single-tenant deploys never set an admin token — they must keep working
    exactly as before rather than losing their auth entirely."""
    monkeypatch.setenv("CASELINE_FIRM_TOKEN", firm["token"])
    monkeypatch.delenv("CASELINE_ADMIN_TOKEN", raising=False)
    async with _http(asgi) as http:
        client = await BackendClient.for_call("web-manual-unknown", client=http)
        assert client.v1  # still authenticated, via the env firm token


async def test_for_call_falls_back_when_room_is_unknown(asgi, firm, monkeypatch):
    """An unresolvable room must degrade to the env token, never to no auth —
    a caller hearing dead air is worse than a call filed under the default."""
    monkeypatch.setenv("CASELINE_FIRM_TOKEN", firm["token"])
    monkeypatch.setenv("CASELINE_ADMIN_TOKEN", ADMIN_TOKEN)
    async with _http(asgi) as http:
        client = await BackendClient.for_call("room-that-does-not-exist", client=http)
        assert client.v1
