"""Filevine adapter (Filevine v2 core API).

Second adapter — the first pressure test of the ``CaseManagementProvider``
abstraction against a provider whose object model differs from Clio's:

  Contact -> Person contact (deduped by phone search)
  Matter  -> Project (Filevine's matter unit; requires a project type,
             supplied per-firm via credentials as ``project_type_id``)
  Task    -> Task
  Note    -> Project note

Auth is a bearer session token minted from an API key/secret pair
(POST /session); on a 401 the adapter re-mints once and retries, handing the
rotated token to ``on_token_refresh`` for re-encryption at rest — the same
contract Clio uses. Filevine ids arrive both flat and wrapped
(``{"native": 123, "partner": ...}``); ``_ext_id`` normalizes either shape.
"""

from __future__ import annotations

import logging
from typing import Callable

import httpx

from integrations.base import CaseManagementProvider, ProviderError
from integrations.models import Contact, Matter, Note, Task

logger = logging.getLogger("caseline.integrations.filevine")

DEFAULT_BASE_URL = "https://api.filevine.io"


def _ext_id(value: object) -> str:
    """Normalize Filevine's id shapes (int | str | {'native': ...})."""
    if isinstance(value, dict):
        value = value.get("native")
    if value is None:
        raise ProviderError("Filevine response carried no id")
    return str(value)


class FilevineProvider(CaseManagementProvider):
    name = "filevine"

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        access_token: str | None = None,
        project_type_id: int | None = None,
        base_url: str = DEFAULT_BASE_URL,
        on_token_refresh: Callable[[dict], None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        if not access_token and not (api_key and api_secret):
            raise ValueError("Filevine needs an access_token or an api_key/api_secret pair")
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token
        self._project_type_id = project_type_id
        self._on_token_refresh = on_token_refresh
        self._client = httpx.Client(base_url=base_url, timeout=15.0, transport=transport)

    # --- HTTP plumbing ---

    def _mint_session(self) -> None:
        if not (self._api_key and self._api_secret):
            raise ProviderError("Filevine session expired and no api key/secret configured")
        r = self._client.post(
            "/session", json={"apiKey": self._api_key, "apiSecret": self._api_secret}
        )
        if r.status_code != 200:
            raise ProviderError(f"Filevine session mint failed: {r.status_code} {r.text[:200]}")
        self._access_token = r.json()["accessToken"]
        logger.info("Filevine session token minted")
        if self._on_token_refresh:
            self._on_token_refresh({"access_token": self._access_token})

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            if self._access_token is None:
                self._mint_session()
            r = self._client.request(
                method, path, headers={"Authorization": f"Bearer {self._access_token}"}, **kwargs
            )
            if r.status_code == 401 and self._api_key and self._api_secret:
                self._mint_session()
                r = self._client.request(
                    method,
                    path,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    **kwargs,
                )
            if r.status_code == 429 or r.status_code >= 500:
                raise ProviderError(f"Filevine {method} {path} -> {r.status_code} (retryable)")
            if r.status_code >= 400:
                raise ProviderError(f"Filevine {method} {path} -> {r.status_code}: {r.text[:300]}")
            return r.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Filevine {method} {path} transport failure: {exc}") from exc

    # --- CaseManagementProvider ---

    def upsert_contact(self, contact: Contact, idempotency_key: str) -> str:
        if contact.phone:
            found = self._request("GET", "/core/contacts", params={"phone": contact.phone})
            items = found.get("items", [])
            if items:
                return _ext_id(items[0].get("personId") or items[0].get("id"))
        parts = contact.name.strip().split(" ", 1)
        body = {
            "firstName": parts[0],
            "lastName": parts[1] if len(parts) > 1 else "",
            "fullName": contact.name,
            "personTypes": ["Client"],
        }
        if contact.phone:
            body["primaryPhone"] = contact.phone
        if contact.email:
            body["primaryEmail"] = contact.email
        created = self._request("POST", "/core/contacts", json=body)
        return _ext_id(created.get("personId") or created.get("id"))

    def create_matter(self, matter: Matter, contact_external_id: str, idempotency_key: str) -> str:
        body: dict = {
            "projectName": matter.description[:120],
            "clientId": int(contact_external_id),
        }
        if self._project_type_id is not None:
            body["projectTypeId"] = int(self._project_type_id)
        created = self._request("POST", "/core/projects", json=body)
        return _ext_id(created.get("projectId") or created.get("id"))

    def create_task(self, task: Task, matter_external_id: str | None, idempotency_key: str) -> str:
        body: dict = {"name": task.name}
        if task.due_at is not None:
            body["dueDate"] = task.due_at.isoformat()
        if matter_external_id:
            body["projectId"] = int(matter_external_id)
        created = self._request("POST", "/core/tasks", json=body)
        return _ext_id(created.get("taskId") or created.get("id"))

    def add_note(self, note: Note, matter_external_id: str, idempotency_key: str) -> str:
        body = {
            "projectId": int(matter_external_id),
            "subject": note.subject,
            "body": note.detail,
        }
        created = self._request("POST", "/core/notes", json=body)
        return _ext_id(created.get("noteId") or created.get("id"))

    def close(self) -> None:
        self._client.close()
