"""CaseManagementProvider: the one interface every CMS adapter implements.

Contract rules (cross-phase, non-negotiable):
  * Every write takes an ``idempotency_key``. The platform's idempotency
    ledger is the primary duplicate defense; adapters additionally dedupe
    natively where the provider allows (e.g. Clio contact search by phone).
  * Adapters raise ``ProviderError`` for anything retryable; the event
    worker owns retry/backoff/dead-letter policy, not the adapter.
  * Provider names appear only in adapter code and firm config.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from integrations.models import Contact, Matter, Note, Task


class ProviderError(Exception):
    """A provider-side failure the worker may retry."""


class CaseManagementProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def upsert_contact(self, contact: Contact, idempotency_key: str) -> str:
        """Create or find the contact; returns the provider's contact id."""

    @abstractmethod
    def create_matter(self, matter: Matter, contact_external_id: str, idempotency_key: str) -> str:
        """Create a matter/case for a contact; returns the provider's id."""

    @abstractmethod
    def create_task(self, task: Task, matter_external_id: str | None, idempotency_key: str) -> str:
        """Create a task; returns the provider's id."""

    @abstractmethod
    def add_note(self, note: Note, matter_external_id: str, idempotency_key: str) -> str:
        """Attach a note to a matter; returns the provider's id."""

    def close(self) -> None:  # adapters holding connections override
        return None


def get_provider_class(name: str) -> type[CaseManagementProvider]:
    """Config-string -> adapter class. Import-lazy so an unused adapter's
    dependencies are never required."""
    if name == "clio":
        from integrations.clio import ClioProvider

        return ClioProvider
    if name == "mock":
        from integrations.mock import MockProvider

        return MockProvider
    raise ValueError(f"Unknown CMS provider {name!r}")
