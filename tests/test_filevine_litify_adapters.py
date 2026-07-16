"""Filevine + Litify adapters against mocked transports: endpoint shapes,
phone dedupe, session/token refresh-and-retry, retryable error mapping.
Phase 2 exit criterion: three CMS adapters live behind one interface."""

import json

import httpx
import pytest

from integrations.base import ProviderError, get_provider_class
from integrations.filevine import FilevineProvider
from integrations.litify import LitifyProvider
from integrations.models import Contact, Matter, Note, Task

# ---------------------------------------------------------------------------
# Filevine
# ---------------------------------------------------------------------------


class FakeFilevine:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.contacts: list[dict] = []
        self.expired_token: str | None = None
        self._ids = iter(range(500, 600))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/session":
            self.expired_token = None
            return httpx.Response(200, json={"accessToken": "fv-fresh"})
        auth = request.headers.get("authorization", "")
        if self.expired_token and auth == f"Bearer {self.expired_token}":
            return httpx.Response(401, json={"error": "expired"})
        if path == "/core/contacts" and request.method == "GET":
            phone = request.url.params.get("phone")
            hits = [c for c in self.contacts if c["phone"] == phone]
            # Filevine wraps ids: {"native": ..., "partner": null}
            return httpx.Response(
                200, json={"items": [{"personId": {"native": c["id"]}} for c in hits]}
            )
        if path == "/core/contacts" and request.method == "POST":
            body = json.loads(request.content)
            new = {"id": next(self._ids), "phone": body.get("primaryPhone")}
            self.contacts.append(new)
            return httpx.Response(200, json={"personId": {"native": new["id"]}})
        if path == "/core/projects":
            return httpx.Response(200, json={"projectId": {"native": next(self._ids)}})
        if path == "/core/tasks":
            return httpx.Response(200, json={"taskId": next(self._ids)})  # flat id shape
        if path == "/core/notes":
            return httpx.Response(200, json={"noteId": {"native": next(self._ids)}})
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def fv_fake():
    return FakeFilevine()


@pytest.fixture
def filevine(fv_fake):
    return FilevineProvider(
        api_key="key", api_secret="secret", access_token="fv-tok",
        project_type_id=18, transport=fv_fake.transport(),
    )


def test_filevine_contact_create_and_wrapped_id(filevine, fv_fake):
    ext = filevine.upsert_contact(
        Contact(name="Dana Torres", phone="+15125550142", email="d@example.com"), "k1"
    )
    assert ext == "500"
    body = json.loads(fv_fake.requests[-1].content)
    assert body["firstName"] == "Dana" and body["lastName"] == "Torres"
    assert body["primaryPhone"] == "+15125550142"
    assert body["personTypes"] == ["Client"]


def test_filevine_contact_deduped_by_phone(filevine, fv_fake):
    first = filevine.upsert_contact(Contact(name="Dana Torres", phone="+15125550142"), "k1")
    second = filevine.upsert_contact(Contact(name="D. Torres", phone="+15125550142"), "k2")
    assert first == second
    posts = [r for r in fv_fake.requests if r.method == "POST" and "contacts" in r.url.path]
    assert len(posts) == 1


def test_filevine_project_task_note_shapes(filevine, fv_fake):
    project = filevine.create_matter(Matter(description="MVA intake"), "500", "k3")
    body = json.loads(fv_fake.requests[-1].content)
    assert body["clientId"] == 500 and body["projectTypeId"] == 18

    filevine.create_task(Task(name="Consult Tuesday"), project, "k4")
    assert json.loads(fv_fake.requests[-1].content)["projectId"] == int(project)

    filevine.add_note(Note(subject="Intake call", detail="summary"), project, "k5")
    body = json.loads(fv_fake.requests[-1].content)
    assert body["subject"] == "Intake call" and body["projectId"] == int(project)


def test_filevine_expired_session_reminted_and_retried(fv_fake):
    rotated: list[dict] = []
    fv = FilevineProvider(
        api_key="key", api_secret="secret", access_token="fv-old",
        transport=fv_fake.transport(), on_token_refresh=rotated.append,
    )
    fv_fake.expired_token = "fv-old"
    assert fv.upsert_contact(Contact(name="Sam Lee", phone="+15125550111"), "k1")
    assert rotated == [{"access_token": "fv-fresh"}]
    assert "/session" in [r.url.path for r in fv_fake.requests]


def test_filevine_server_errors_are_retryable():
    transport = httpx.MockTransport(lambda req: httpx.Response(503, text="brownout"))
    fv = FilevineProvider(access_token="t", transport=transport)
    with pytest.raises(ProviderError, match="retryable"):
        fv.upsert_contact(Contact(name="X", phone="+1"), "k1")


def test_filevine_requires_some_credentials():
    with pytest.raises(ValueError):
        FilevineProvider()


# ---------------------------------------------------------------------------
# Litify (Salesforce)
# ---------------------------------------------------------------------------


class FakeSalesforce:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.accounts: list[dict] = []
        self.expired_token: str | None = None
        self._ids = iter(f"001xx{n:012d}" for n in range(1, 100))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/services/oauth2/token":
            self.expired_token = None
            return httpx.Response(200, json={"access_token": "sf-fresh"})
        auth = request.headers.get("authorization", "")
        if self.expired_token and auth == f"Bearer {self.expired_token}":
            return httpx.Response(401, json=[{"errorCode": "INVALID_SESSION_ID"}])
        if path.endswith("/query"):
            soql = request.url.params.get("q", "")
            hits = [a for a in self.accounts if a["phone"] in soql]
            return httpx.Response(
                200, json={"records": [{"Id": a["id"]} for a in hits], "done": True}
            )
        if "/sobjects/" in path and request.method == "POST":
            new_id = next(self._ids)
            if path.endswith("/sobjects/Account"):
                body = json.loads(request.content)
                self.accounts.append({"id": new_id, "phone": body.get("Phone")})
            return httpx.Response(201, json={"id": new_id, "success": True, "errors": []})
        return httpx.Response(404, json=[{"errorCode": "NOT_FOUND"}])


@pytest.fixture
def sf_fake():
    return FakeSalesforce()


@pytest.fixture
def litify(sf_fake):
    return LitifyProvider(
        instance_url="https://acme.my.salesforce.com",
        access_token="sf-tok",
        refresh_token="sf-ref",
        client_id="cid",
        client_secret="secret",
        transport=sf_fake.transport(),
    )


def test_litify_contact_dedupe_via_soql(litify, sf_fake):
    first = litify.upsert_contact(Contact(name="Dana Torres", phone="+15125550142"), "k1")
    second = litify.upsert_contact(Contact(name="D. Torres", phone="+15125550142"), "k2")
    assert first == second
    creates = [r for r in sf_fake.requests if r.method == "POST" and "Account" in r.url.path]
    assert len(creates) == 1


def test_litify_soql_injection_is_escaped(litify, sf_fake):
    litify.upsert_contact(Contact(name="Evil", phone="' OR Name != '"), "k1")
    query_req = next(r for r in sf_fake.requests if r.url.path.endswith("/query"))
    assert "\\'" in query_req.url.params["q"]  # quotes escaped, not interpolated


def test_litify_matter_task_note_shapes(litify, sf_fake):
    matter = litify.create_matter(Matter(description="MVA intake"), "001xx000000000001", "k3")
    body = json.loads(sf_fake.requests[-1].content)
    assert body["litify_pm__Client__c"] == "001xx000000000001"
    assert body["litify_pm__Status__c"] == "Open"

    from datetime import datetime

    litify.create_task(Task(name="Consult", due_at=datetime(2026, 7, 21, 10)), matter, "k4")
    body = json.loads(sf_fake.requests[-1].content)
    assert body["WhatId"] == matter and body["ActivityDate"] == "2026-07-21"

    litify.add_note(Note(subject="Intake call", detail="summary"), matter, "k5")
    body = json.loads(sf_fake.requests[-1].content)
    assert body["ParentId"] == matter and body["Title"] == "Intake call"


def test_litify_expired_token_refreshes_and_retries(sf_fake):
    rotated: list[dict] = []
    litify = LitifyProvider(
        instance_url="https://acme.my.salesforce.com",
        access_token="sf-old",
        refresh_token="sf-ref",
        client_id="cid",
        client_secret="secret",
        transport=sf_fake.transport(),
        on_token_refresh=rotated.append,
    )
    sf_fake.expired_token = "sf-old"
    assert litify.upsert_contact(Contact(name="Sam Lee", phone="+15125550111"), "k1")
    assert rotated == [{"access_token": "sf-fresh"}]


def test_litify_server_errors_are_retryable():
    transport = httpx.MockTransport(lambda req: httpx.Response(500, text="whoops"))
    litify = LitifyProvider(instance_url="https://x.salesforce.com", access_token="t",
                            transport=transport)
    with pytest.raises(ProviderError, match="retryable"):
        litify.upsert_contact(Contact(name="X", phone="+1"), "k1")


# ---------------------------------------------------------------------------
# One interface, three providers
# ---------------------------------------------------------------------------


def test_all_three_adapters_resolve_behind_one_interface():
    from integrations.base import CaseManagementProvider

    for name in ("clio", "filevine", "litify", "mock"):
        cls = get_provider_class(name)
        assert issubclass(cls, CaseManagementProvider)
        assert cls.name == name
