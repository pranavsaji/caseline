"""Phase 1 exit-criteria walk: a simulated design-partner firm, onboarded,
running the full intake path through the real agent BackendClient against
the real v1 app, with the async worker syncing to the CMS and cross-tenant
isolation verified through the API."""

import httpx
import pytest

from agent.backend_client import BackendClient
from integrations.mock import MockProvider
from workers.cms_sync import EventProcessor


@pytest.fixture
async def agent_backend(v1_app, firm):
    """The exact client the voice worker uses, in v1 mode."""
    transport = httpx.ASGITransport(app=v1_app)
    client = BackendClient(
        client=httpx.AsyncClient(transport=transport, base_url="http://testserver"),
        firm_token=firm["token"],
    )
    yield client
    await client.aclose()


async def test_full_intake_call_to_cms_round_trip(v1_client, v1_app, firm, db, platform, agent_backend):
    call_id = "room-e2e-1"
    backend = agent_backend
    assert backend.v1

    # 1. Call start: worker loads the firm's config, not a hardcoded prompt.
    config = await backend.get_agent_config()
    assert "Bluebonnet Injury Law" in config["instructions"]

    # 2. The conversation drives the typed tools.
    lookup = await backend.lookup_caller("+15125550142")
    assert lookup == {"known": False}

    decision = await backend.qualify_lead(
        "2026-06-01", "whiplash", True, True, call_id=call_id
    )
    assert decision["decision"] == "qualified"

    booked = await backend.schedule_consult(
        "Dana Torres", "+15125550142", "2026-07-21T10:00:00", call_id=call_id
    )
    assert booked["status"] == "booked"

    sms = await backend.send_sms(call_id, "+15125550142", "Confirmed for Tuesday 10am.")
    assert sms["status"] == "sent"

    saved = await backend.write_to_cms(
        call_id,
        "Dana Torres, whiplash on 2026-06-01, in treatment, insured. Consult booked.",
        {
            "name": "Dana Torres",
            "phone": "+15125550142",
            "incident_date": "2026-06-01",
            "injury_type": "whiplash",
            "in_treatment": True,
            "has_insurance": True,
            "decision": "qualified",
            "consult_slot": "2026-07-21T10:00:00",
        },
    )
    assert saved["status"] == "saved"

    # 3. Per-turn latency lands in the platform store (SLO instrumentation
    #    carried forward from Phase 0).
    for i, total in enumerate([480.0, 610.0, 550.0], start=1):
        await backend.post_turn_metrics(
            {
                "call_id": call_id,
                "speech_id": f"turn-{i}",
                "eou_delay_ms": 180.0,
                "llm_ttft_ms": total - 270.0,
                "tts_ttfb_ms": 90.0,
                "total_ms": total,
            }
        )
    summary = await backend.call_latency_summary(call_id)
    assert summary["turns"] == 3
    assert summary["within_budget"] is True

    # 4. Transcript persists at hangup; latency rolls up onto the call row.
    await backend.post_transcript(
        call_id,
        [
            {"role": "assistant", "text": "Thanks for calling Bluebonnet Injury Law."},
            {"role": "user", "text": "I was rear-ended on June first."},
        ],
        summary="Qualified whiplash lead.",
    )

    # 5. The async worker performs the CMS writes — never the voice path.
    cms = MockProvider()
    processor = EventProcessor(db, platform.cipher, provider_overrides={firm["firm_id"]: cms})
    counts = processor.process_once()
    assert counts["dead"] == 0
    assert len(cms.contacts) == 1
    assert len(cms.matters) == 1
    assert len(cms.notes) == 1
    assert len(cms.tasks) == 1  # consult.booked -> CMS task

    # Forced retry of the whole batch: nothing duplicates.
    processor.process_once()
    assert len(cms.contacts) == 1 and len(cms.matters) == 1 and len(cms.tasks) == 1

    # 6. Dashboard reads see the call with transcript + latency.
    calls = v1_client.get("/v1/calls", headers=firm["headers"]).json()
    assert len(calls) == 1
    assert calls[0]["latency_p95_ms"] is not None

    detail = v1_client.get(f"/v1/calls/{call_id}", headers=firm["headers"]).json()
    assert len(detail["transcript"]) == 2
    assert len(detail["turn_metrics"]) == 3
    assert detail["outcome"] == "qualified"

    # 7. Cross-tenant isolation through the API (RLS verified end to end).


async def test_cross_tenant_isolation_through_api(v1_client, firm, second_firm, agent_backend):
    await agent_backend.qualify_lead("2026-06-01", "whiplash", True, True, call_id="c1")
    mine = v1_client.get("/v1/leads", headers=firm["headers"]).json()
    theirs = v1_client.get("/v1/leads", headers=second_firm["headers"]).json()
    assert len(mine) == 1
    assert theirs == []
    r = v1_client.get("/v1/calls/c1", headers=second_firm["headers"])
    assert r.status_code == 404


def test_worker_builds_provider_from_encrypted_credentials(v1_client, db, platform):
    """Credentials round-trip: encrypted at onboarding, decrypted only inside
    the worker, provider constructed from them."""
    r = v1_client.post(
        "/v1/admin/firms",
        json={
            "name": "Cipher Firm",
            "cms_provider": "mock",
            "cms_credentials": {"api_key": "sekrit"},
        },
        headers={"X-Admin-Token": "test-admin-token"},
    )
    firm_id = r.json()["firm_id"]
    with db.admin() as conn:
        stored = conn.execute(
            "SELECT cms_credentials_enc FROM firms WHERE id = %s", (firm_id,)
        ).fetchone()["cms_credentials_enc"]
    assert "sekrit" not in (stored or "")  # never plaintext at rest
    processor = EventProcessor(db, platform.cipher)
    provider = processor._provider_for(firm_id)
    assert isinstance(provider, MockProvider)
