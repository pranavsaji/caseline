"""Mock CMS provider: local dev + tests + firms not yet wired to a real CMS.

Records land in an in-memory store on the instance (inspectable by tests)
and in the worker log. Also supports fault injection so the worker's
retry/idempotency behavior can be proven (Phase 1 exit criterion:
"idempotent under forced retry").
"""

from __future__ import annotations

import itertools
import logging

from integrations.base import CaseManagementProvider, ProviderError
from integrations.models import Contact, Matter, Note, Task

logger = logging.getLogger("caseline.integrations.mock")


class MockProvider(CaseManagementProvider):
    name = "mock"

    def __init__(self, **_credentials: object):
        self.contacts: dict[str, dict] = {}
        self.matters: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}
        self.notes: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self.fail_next: int = 0  # fault injection: raise on the next N writes

    def _maybe_fail(self) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ProviderError("injected mock-CMS failure")

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids)}"

    def upsert_contact(self, contact: Contact, idempotency_key: str) -> str:
        self._maybe_fail()
        for ext_id, existing in self.contacts.items():
            if contact.phone and existing["phone"] == contact.phone:
                return ext_id
        ext_id = self._next_id("contact")
        self.contacts[ext_id] = contact.model_dump()
        logger.info("mock CMS contact %s: %s", ext_id, contact.name)
        return ext_id

    def create_matter(self, matter: Matter, contact_external_id: str, idempotency_key: str) -> str:
        self._maybe_fail()
        ext_id = self._next_id("matter")
        self.matters[ext_id] = {**matter.model_dump(), "contact": contact_external_id}
        logger.info("mock CMS matter %s: %s", ext_id, matter.description)
        return ext_id

    def create_task(self, task: Task, matter_external_id: str | None, idempotency_key: str) -> str:
        self._maybe_fail()
        ext_id = self._next_id("task")
        self.tasks[ext_id] = {**task.model_dump(), "matter": matter_external_id}
        logger.info("mock CMS task %s: %s", ext_id, task.name)
        return ext_id

    def add_note(self, note: Note, matter_external_id: str, idempotency_key: str) -> str:
        self._maybe_fail()
        ext_id = self._next_id("note")
        self.notes[ext_id] = {**note.model_dump(), "matter": matter_external_id}
        logger.info("mock CMS note %s: %s", ext_id, note.subject)
        return ext_id
