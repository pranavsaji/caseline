"""Clio adapter against a mocked transport: endpoint shapes, contact dedupe,
OAuth refresh-and-retry, retryable error mapping. No network."""

import json

import httpx
import pytest

from integrations.clio import ClioProvider
from integrations.base import ProviderError
from integrations.models import Contact, Matter, Note, Task


class FakeClio:
    """Minimal Clio v4 stand-in behind httpx.MockTransport."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.contacts: list[dict] = []
        self.expired_token: str | None = None
        self._ids = iter(range(100, 200))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/oauth/token":
            self.expired_token = None
            return httpx.Response(
                200, json={"access_token": "fresh-token", "refresh_token": "fresh-refresh"}
            )
        auth = request.headers.get("authorization", "")
        if self.expired_token and auth == f"Bearer {self.expired_token}":
            return httpx.Response(401, json={"error": "invalid_token"})
        if path == "/api/v4/contacts.json" and request.method == "GET":
            query = request.url.params.get("query")
            hits = [c for c in self.contacts if c.get("phone") == query]
            return httpx.Response(200, json={"data": [{"id": c["id"]} for c in hits]})
        if path == "/api/v4/contacts.json" and request.method == "POST":
            body = json.loads(request.content)["data"]
            new = {"id": next(self._ids), "phone": (body.get("phone_numbers") or [{}])[0].get("number")}
            self.contacts.append(new)
            return httpx.Response(201, json={"data": {"id": new["id"]}})
        if path in ("/api/v4/matters.json", "/api/v4/tasks.json", "/api/v4/notes.json"):
            return httpx.Response(201, json={"data": {"id": next(self._ids)}})
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def fake():
    return FakeClio()


@pytest.fixture
def clio(fake):
    return ClioProvider(
        access_token="tok-1",
        refresh_token="ref-1",
        client_id="cid",
        client_secret="secret",
        transport=fake.transport(),
    )


def test_contact_created_with_normalized_fields(clio, fake):
    ext_id = clio.upsert_contact(
        Contact(name="Dana Torres", phone="+15125550142", email="dana@example.com"), "k1"
    )
    assert ext_id == "100"
    create = json.loads(fake.requests[-1].content)["data"]
    assert create["type"] == "Person"
    assert create["first_name"] == "Dana"
    assert create["last_name"] == "Torres"
    assert create["phone_numbers"][0]["number"] == "+15125550142"


def test_contact_deduped_by_phone_search(clio, fake):
    first = clio.upsert_contact(Contact(name="Dana Torres", phone="+15125550142"), "k1")
    second = clio.upsert_contact(Contact(name="D. Torres", phone="+15125550142"), "k2")
    assert first == second
    posts = [r for r in fake.requests if r.method == "POST" and "contacts" in r.url.path]
    assert len(posts) == 1  # the second upsert found the existing contact


def test_matter_task_note_payload_shapes(clio, fake):
    matter_id = clio.create_matter(Matter(description="MVA intake"), "100", "k3")
    body = json.loads(fake.requests[-1].content)["data"]
    assert body["client"]["id"] == 100
    assert body["status"] == "Pending"

    clio.create_task(Task(name="Consult Tuesday 2pm"), matter_id, "k4")
    body = json.loads(fake.requests[-1].content)["data"]
    assert body["matter"]["id"] == int(matter_id)

    clio.add_note(Note(subject="Intake call", detail="summary..."), matter_id, "k5")
    body = json.loads(fake.requests[-1].content)["data"]
    assert body["type"] == "Matter"
    assert body["subject"] == "Intake call"


def test_expired_token_refreshes_and_retries(fake):
    rotated: list[dict] = []
    clio = ClioProvider(
        access_token="tok-old",
        refresh_token="ref-1",
        client_id="cid",
        client_secret="secret",
        transport=fake.transport(),
        on_token_refresh=rotated.append,
    )
    fake.expired_token = "tok-old"
    ext_id = clio.upsert_contact(Contact(name="Sam Lee", phone="+15125550111"), "k1")
    assert ext_id  # request succeeded after refresh
    assert rotated == [{"access_token": "fresh-token", "refresh_token": "fresh-refresh"}]
    paths = [r.url.path for r in fake.requests]
    assert "/oauth/token" in paths


def test_server_errors_map_to_retryable_provider_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(503, text="brownout"))
    clio = ClioProvider(access_token="t", transport=transport)
    with pytest.raises(ProviderError, match="retryable"):
        clio.upsert_contact(Contact(name="X", phone="+1"), "k1")
