"""CMS sync worker: outbox consumption, idempotency under fault injection,
retry with backoff, dead-letter queue. Phase 1 exit criterion: idempotent
under forced retry — zero duplicate CMS writes."""

import pytest

from api.platform import events
from integrations.mock import MockProvider
from integrations.models import Matter
from workers.cms_sync import EventProcessor


@pytest.fixture
def cms(firm, platform):
    return MockProvider()


@pytest.fixture
def processor(db, platform, firm, cms):
    return EventProcessor(db, platform.cipher, provider_overrides={firm["firm_id"]: cms})


def _complete_call(v1_client, firm, call_id="call-w1"):
    r = v1_client.post(
        "/v1/calls/complete",
        json={
            "call_id": call_id,
            "summary": "Qualified whiplash lead, consult booked.",
            "structured": {
                "name": "Dana Torres",
                "phone": "+15125550142",
                "decision": "qualified",
                "practice_area": "personal injury",
            },
        },
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text


def test_call_completed_syncs_contact_matter_note(v1_client, firm, processor, cms):
    _complete_call(v1_client, firm)
    counts = processor.process_once()
    assert counts["processed"] == 1
    assert len(cms.contacts) == 1
    assert len(cms.matters) == 1
    assert len(cms.notes) == 1
    assert list(cms.contacts.values())[0]["name"] == "Dana Torres"
    # event marked processed
    evs = v1_client.get("/v1/events", params={"status": "processed"}, headers=firm["headers"]).json()
    assert any(e["type"] == "call.completed" for e in evs)
    # external id reflected back onto the local lead-by-call linkage
    reprocess = processor.process_once()
    assert reprocess["processed"] == 0  # nothing left to do


def test_consult_booked_creates_cms_task(v1_client, firm, processor, cms):
    v1_client.post(
        "/v1/tools/schedule_consult",
        json={
            "call_id": "call-w2",
            "name": "Sam Lee",
            "phone": "+15125550111",
            "slot_iso": "2026-07-21T10:00:00",
        },
        headers=firm["headers"],
    )
    processor.process_once()
    assert len(cms.tasks) == 1
    assert "Sam Lee" in list(cms.tasks.values())[0]["name"]


def _force_due(db) -> None:
    with db.admin() as conn:
        conn.execute("UPDATE events SET next_attempt_at = now() WHERE status = 'pending'")


def test_forced_retry_never_duplicates_cms_writes(v1_client, firm, db, platform):
    """Provider fails after the contact write; the retry must finish the
    matter + note without re-creating the contact."""

    class FlakyProvider(MockProvider):
        def __init__(self):
            super().__init__()
            self.contact_calls = 0
            self.fail_matter_once = True

        def upsert_contact(self, contact, idempotency_key):
            self.contact_calls += 1
            return super().upsert_contact(contact, idempotency_key)

        def create_matter(self, matter: Matter, contact_external_id, idempotency_key):
            if self.fail_matter_once:
                self.fail_matter_once = False
                raise RuntimeError("CMS blew up mid-sync")
            return super().create_matter(matter, contact_external_id, idempotency_key)

    cms = FlakyProvider()
    processor = EventProcessor(db, platform.cipher, provider_overrides={firm["firm_id"]: cms})
    _complete_call(v1_client, firm)

    first = processor.process_once()
    assert first["retried"] == 1
    assert len(cms.contacts) == 1 and len(cms.matters) == 0

    _force_due(db)  # skip the backoff wait
    second = processor.process_once()
    assert second["processed"] == 1
    assert cms.contact_calls == 1  # idempotency ledger short-circuited the retry
    assert len(cms.contacts) == 1
    assert len(cms.matters) == 1
    assert len(cms.notes) == 1


def test_poison_event_dead_letters_then_replays(v1_client, firm, db, platform, cms):
    cms.fail_next = 999
    processor = EventProcessor(db, platform.cipher, provider_overrides={firm["firm_id"]: cms})
    _complete_call(v1_client, firm)

    outcomes = []
    for _ in range(events.MAX_ATTEMPTS):
        _force_due(db)
        outcomes.append(processor.process_once())
    assert outcomes[-1]["dead"] == 1

    dead = v1_client.get("/v1/events", params={"status": "dead"}, headers=firm["headers"]).json()
    assert len(dead) == 1
    assert "injected mock-CMS failure" in dead[0]["last_error"]

    # human fixes the provider, replays the poison event
    cms.fail_next = 0
    with db.admin() as conn:
        events.replay_dead(conn, dead[0]["id"])
    counts = processor.process_once()
    assert counts["processed"] == 1
    assert len(cms.contacts) == 1


def test_events_without_caller_identity_are_skipped_gracefully(v1_client, firm, processor, cms):
    v1_client.post(
        "/v1/calls/complete",
        json={"call_id": "anon", "summary": "Hang-up.", "structured": {}},
        headers=firm["headers"],
    )
    counts = processor.process_once()
    assert counts["processed"] == 1  # processed as a no-op, not retried forever
    assert len(cms.contacts) == 0
