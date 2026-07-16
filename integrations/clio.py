"""Clio adapter (Clio Manage REST API v4).

First real adapter (best API in the space: OAuth2, webhooks, clean REST).
Mapping from the normalized schema:

  Contact -> Clio Person contact (deduped by phone-number search)
  Lead    -> Contact + pending Matter (Clio Manage has no first-class lead)
  Matter  -> Matter (status Pending) under the contact
  Task    -> Task
  Note    -> Matter note

Auth is OAuth2 with refresh tokens. On a 401 the adapter refreshes once and
retries; rotated tokens are handed to ``on_token_refresh`` so the platform
re-encrypts and persists them (credentials only ever live encrypted at
rest). Retryable failures raise ``ProviderError`` — retry policy belongs to
the event worker.
"""

from __future__ import annotations

import logging
from typing import Callable

import httpx

from integrations.base import CaseManagementProvider, ProviderError
from integrations.models import Contact, Matter, Note, Task

logger = logging.getLogger("caseline.integrations.clio")

DEFAULT_BASE_URL = "https://app.clio.com"
API_PREFIX = "/api/v4"


class ClioProvider(CaseManagementProvider):
    name = "clio"

    def __init__(
        self,
        access_token: str,
        refresh_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        on_token_refresh: Callable[[dict], None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._on_token_refresh = on_token_refresh
        self._client = httpx.Client(base_url=base_url, timeout=15.0, transport=transport)

    # --- HTTP plumbing ---

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _refresh(self) -> None:
        if not (self._refresh_token and self._client_id and self._client_secret):
            raise ProviderError("Clio access token expired and no refresh credentials configured")
        r = self._client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if r.status_code != 200:
            raise ProviderError(f"Clio token refresh failed: {r.status_code} {r.text[:200]}")
        payload = r.json()
        self._access_token = payload["access_token"]
        self._refresh_token = payload.get("refresh_token", self._refresh_token)
        logger.info("Clio access token refreshed")
        if self._on_token_refresh:
            self._on_token_refresh(
                {"access_token": self._access_token, "refresh_token": self._refresh_token}
            )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = API_PREFIX + path
        try:
            r = self._client.request(method, url, headers=self._headers(), **kwargs)
            if r.status_code == 401 and self._refresh_token:
                self._refresh()
                r = self._client.request(method, url, headers=self._headers(), **kwargs)
            if r.status_code == 429 or r.status_code >= 500:
                raise ProviderError(f"Clio {method} {path} -> {r.status_code} (retryable)")
            if r.status_code >= 400:
                # 4xx other than auth/rate-limit is a poison payload: raising
                # ProviderError still lets the worker retry, and after max
                # attempts it dead-letters for human replay.
                raise ProviderError(f"Clio {method} {path} -> {r.status_code}: {r.text[:300]}")
            return r.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Clio {method} {path} transport failure: {exc}") from exc

    # --- CaseManagementProvider ---

    def upsert_contact(self, contact: Contact, idempotency_key: str) -> str:
        if contact.phone:
            found = self._request(
                "GET", "/contacts.json", params={"query": contact.phone, "type": "Person"}
            )
            data = found.get("data", [])
            if data:
                return str(data[0]["id"])
        parts = contact.name.strip().split(" ", 1)
        body = {
            "data": {
                "type": "Person",
                "first_name": parts[0],
                "last_name": parts[1] if len(parts) > 1 else "",
            }
        }
        if contact.phone:
            body["data"]["phone_numbers"] = [
                {"name": "Mobile", "number": contact.phone, "default_number": True}
            ]
        if contact.email:
            body["data"]["email_addresses"] = [
                {"name": "Home", "address": contact.email, "default_email": True}
            ]
        created = self._request("POST", "/contacts.json", json=body)
        return str(created["data"]["id"])

    def create_matter(self, matter: Matter, contact_external_id: str, idempotency_key: str) -> str:
        body = {
            "data": {
                "client": {"id": int(contact_external_id)},
                "description": matter.description,
                "status": "Pending",
            }
        }
        created = self._request("POST", "/matters.json", json=body)
        return str(created["data"]["id"])

    def create_task(self, task: Task, matter_external_id: str | None, idempotency_key: str) -> str:
        body: dict = {"data": {"name": task.name}}
        if task.due_at is not None:
            body["data"]["due_at"] = task.due_at.isoformat()
        if matter_external_id:
            body["data"]["matter"] = {"id": int(matter_external_id)}
        created = self._request("POST", "/tasks.json", json=body)
        return str(created["data"]["id"])

    def add_note(self, note: Note, matter_external_id: str, idempotency_key: str) -> str:
        body = {
            "data": {
                "type": "Matter",
                "matter": {"id": int(matter_external_id)},
                "subject": note.subject,
                "detail": note.detail,
            }
        }
        created = self._request("POST", "/notes.json", json=body)
        return str(created["data"]["id"])

    def close(self) -> None:
        self._client.close()
