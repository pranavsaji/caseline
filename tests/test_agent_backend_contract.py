"""Agent<->backend contract tests.

Drives the real BackendClient against the real FastAPI app in-process
(httpx.ASGITransport) — no network, no LiveKit. This is exactly the HTTP
surface the voice worker's tools use, so a pass here means the agent's tool
calls will work against a running backend.
"""

import httpx
import pytest

from agent.backend_client import BackendClient


@pytest.fixture
async def backend(app):
    transport = httpx.ASGITransport(app=app)
    client = BackendClient(
        client=httpx.AsyncClient(transport=transport, base_url="http://testserver")
    )
    yield client
    await client.aclose()


async def test_qualify_lead_contract(backend):
    result = await backend.qualify_lead("2026-06-01", "whiplash", True, True)
    assert result["decision"] == "qualified"
    assert isinstance(result["reasons"], list)


async def test_schedule_consult_contract(backend):
    result = await backend.schedule_consult("Jamie Doe", "+15125550100", "2026-07-20T15:00:00")
    assert result["status"] == "booked"
    assert result["consult_id"] == 1


async def test_write_to_cms_contract(backend):
    result = await backend.write_to_cms(
        "room-1", "Qualified PI lead, booked consult.", {"decision": "qualified"}
    )
    assert result["status"] == "saved"


async def test_full_intake_round_trip(backend):
    """The Phase 0 marquee path: qualify -> schedule -> CMS write -> metrics."""
    decision = await backend.qualify_lead("2026-05-10", "broken arm", True, True)
    assert decision["decision"] == "qualified"

    booked = await backend.schedule_consult("Sam Lee", "+15125550111", "2026-07-21T10:00:00")
    assert booked["status"] == "booked"

    saved = await backend.write_to_cms(
        "room-e2e",
        "Sam Lee, broken arm on 2026-05-10, in treatment, insured. Consult booked.",
        {
            "incident_date": "2026-05-10",
            "injury_type": "broken arm",
            "in_treatment": True,
            "has_insurance": True,
            "decision": "qualified",
            "consult_slot": "2026-07-21T10:00:00",
        },
    )
    assert saved["status"] == "saved"

    await backend.post_turn_metrics(
        {
            "call_id": "room-e2e",
            "speech_id": "turn-1",
            "eou_delay_ms": 180.0,
            "llm_ttft_ms": 210.0,
            "tts_ttfb_ms": 90.0,
            "total_ms": 480.0,
        }
    )
    summary = await backend.call_latency_summary("room-e2e")
    assert summary["turns"] == 1
    assert summary["within_budget"] is True


async def test_post_turn_metrics_never_raises(backend):
    # Metrics posting must never break a live call, even on a bad payload.
    await backend.post_turn_metrics({"garbage": True})  # 422 swallowed + logged
