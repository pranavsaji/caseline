"""Litify adapter (Salesforce managed package, REST + SOQL).

Third adapter, and the deliberate stress test of the abstraction: Litify is
not an API of its own but a managed package inside Salesforce, so the
adapter speaks Salesforce — sObject CRUD, SOQL for dedupe, OAuth2 refresh
tokens against the org's instance URL. Mapping:

  Contact -> Account (Litify runs on person accounts)
  Matter  -> litify_pm__Matter__c linked via litify_pm__Client__c
  Task    -> Task (Salesforce activity) linked via WhatId
  Note    -> Note linked via ParentId

The normalized schema survives untouched — provider weirdness stays inside
this file, which is the whole point (plan.md Workstream E: "if the interface
survives Litify's Salesforce-managed-package weirdness, it's real").
"""

from __future__ import annotations

import logging
from typing import Callable

import httpx

from integrations.base import CaseManagementProvider, ProviderError
from integrations.models import Contact, Matter, Note, Task

logger = logging.getLogger("caseline.integrations.litify")

API_VERSION = "v59.0"


def _soql_quote(value: str) -> str:
    """Escape a string literal for SOQL (single quotes and backslashes)."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


class LitifyProvider(CaseManagementProvider):
    name = "litify"

    def __init__(
        self,
        instance_url: str,
        access_token: str,
        refresh_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        on_token_refresh: Callable[[dict], None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._on_token_refresh = on_token_refresh
        self._client = httpx.Client(
            base_url=instance_url.rstrip("/"), timeout=15.0, transport=transport
        )

    # --- HTTP plumbing ---

    def _refresh(self) -> None:
        if not (self._refresh_token and self._client_id and self._client_secret):
            raise ProviderError("Salesforce token expired and no refresh credentials configured")
        r = self._client.post(
            "/services/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if r.status_code != 200:
            raise ProviderError(f"Salesforce token refresh failed: {r.status_code} {r.text[:200]}")
        self._access_token = r.json()["access_token"]
        logger.info("Salesforce access token refreshed")
        if self._on_token_refresh:
            self._on_token_refresh({"access_token": self._access_token})

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"/services/data/{API_VERSION}{path}"
        try:
            r = self._client.request(
                method, url, headers={"Authorization": f"Bearer {self._access_token}"}, **kwargs
            )
            if r.status_code == 401 and self._refresh_token:
                self._refresh()
                r = self._client.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    **kwargs,
                )
            if r.status_code == 429 or r.status_code >= 500:
                raise ProviderError(f"Salesforce {method} {path} -> {r.status_code} (retryable)")
            if r.status_code >= 400:
                raise ProviderError(
                    f"Salesforce {method} {path} -> {r.status_code}: {r.text[:300]}"
                )
            return r.json() if r.content else {}
        except httpx.HTTPError as exc:
            raise ProviderError(f"Salesforce {method} {path} transport failure: {exc}") from exc

    def _query(self, soql: str) -> list[dict]:
        return self._request("GET", "/query", params={"q": soql}).get("records", [])

    def _create(self, sobject: str, body: dict) -> str:
        created = self._request("POST", f"/sobjects/{sobject}", json=body)
        if not created.get("success", True) or not created.get("id"):
            raise ProviderError(f"Salesforce create {sobject} failed: {created}")
        return str(created["id"])

    # --- CaseManagementProvider ---

    def upsert_contact(self, contact: Contact, idempotency_key: str) -> str:
        if contact.phone:
            records = self._query(
                "SELECT Id FROM Account WHERE Phone = "
                f"'{_soql_quote(contact.phone)}' LIMIT 1"
            )
            if records:
                return str(records[0]["Id"])
        body: dict = {"Name": contact.name}
        if contact.phone:
            body["Phone"] = contact.phone
        if contact.email:
            body["litify_pm__Email__c"] = contact.email
        return self._create("Account", body)

    def create_matter(self, matter: Matter, contact_external_id: str, idempotency_key: str) -> str:
        return self._create(
            "litify_pm__Matter__c",
            {
                "litify_pm__Client__c": contact_external_id,
                "litify_pm__Status__c": "Open",
                "litify_pm__Description__c": matter.description,
            },
        )

    def create_task(self, task: Task, matter_external_id: str | None, idempotency_key: str) -> str:
        body: dict = {"Subject": task.name, "Status": "Not Started"}
        if task.due_at is not None:
            body["ActivityDate"] = task.due_at.date().isoformat()
        if matter_external_id:
            body["WhatId"] = matter_external_id
        return self._create("Task", body)

    def add_note(self, note: Note, matter_external_id: str, idempotency_key: str) -> str:
        return self._create(
            "Note",
            {"Title": note.subject, "Body": note.detail, "ParentId": matter_external_id},
        )

    def close(self) -> None:
        self._client.close()
