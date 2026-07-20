"""Phase 2 observability: per-firm latency and outcome analytics endpoints.
Aggregates only — no PII in any response."""

import json


def _seed_funnel(v1_client, firm):
    """3 calls: qualified+booked, declined, qualified+transfer."""
    h = firm["headers"]
    # call 1: qualified -> booked
    v1_client.post(
        "/v1/tools/qualify_lead",
        json={
            "call_id": "an-1",
            "incident_date": "2026-06-01",
            "injury_type": "whiplash",
            "in_treatment": True,
            "has_insurance": True,
        },
        headers=h,
    )
    # Book a real open slot from the calendar rather than a hardcoded date —
    # a fixed timestamp silently falls into the past and schedule_consult
    # rejects it, so the funnel would show 0 consults booked.
    slot = v1_client.get("/v1/tools/available_slots", headers=h).json()["slots"][0]
    v1_client.post(
        "/v1/tools/schedule_consult",
        json={"call_id": "an-1", "name": "A One", "phone": "+15125550201",
              "slot_iso": slot["slot_iso"]},
        headers=h,
    )
    v1_client.post(
        "/v1/calls/complete",
        json={"call_id": "an-1", "summary": "Booked.",
              "structured": {"name": "A One", "phone": "+15125550201", "decision": "qualified"}},
        headers=h,
    )
    # call 2: declined (injury on the refer-out list -> refer_out decision)
    v1_client.post(
        "/v1/tools/qualify_lead",
        json={
            "call_id": "an-2",
            "incident_date": "2020-01-01",  # outside statute of limitations
            "injury_type": "whiplash",
            "in_treatment": False,
            "has_insurance": False,
        },
        headers=h,
    )
    v1_client.post(
        "/v1/calls/complete",
        json={"call_id": "an-2", "summary": "Declined.", "structured": {"decision": "decline"}},
        headers=h,
    )
    # call 3: qualified, asked for a human
    v1_client.post(
        "/v1/tools/qualify_lead",
        json={
            "call_id": "an-3",
            "incident_date": "2026-07-01",
            "injury_type": "broken arm",
            "in_treatment": True,
            "has_insurance": True,
        },
        headers=h,
    )
    v1_client.post(
        "/v1/tools/transfer_to_human",
        json={"call_id": "an-3", "reason": "caller asked for attorney"},
        headers=h,
    )
    v1_client.post(
        "/v1/calls/complete",
        json={"call_id": "an-3", "summary": "Transferred.",
              "structured": {"decision": "qualified"}},
        headers=h,
    )


def test_outcome_funnel_rates(v1_client, firm):
    _seed_funnel(v1_client, firm)
    r = v1_client.get("/v1/analytics/outcomes", headers=firm["headers"])
    assert r.status_code == 200
    data = r.json()
    assert data["calls"] == 3
    assert data["leads"] == 3
    assert data["qualified_leads"] == 2
    assert data["consults_booked"] == 1
    assert data["transfers"] == 1
    assert data["qualification_rate"] == round(2 / 3, 3)
    assert data["booking_rate"] == 0.5  # 1 consult / 2 qualified
    assert data["transfer_rate"] == round(1 / 3, 3)
    # no PII anywhere in the response
    assert "+1512555" not in json.dumps(data) and "A One" not in json.dumps(data)


def test_latency_analytics_by_day_and_provider(v1_client, firm):
    for i, (llm, ms) in enumerate([("anthropic:claude-haiku-4-5", 520),
                                   ("anthropic:claude-haiku-4-5", 610),
                                   ("openai:gpt-4.1-mini", 780)]):
        v1_client.post(
            "/v1/metrics/turn",
            json={
                "call_id": "an-lat", "speech_id": f"s{i}", "eou_delay_ms": 120,
                "llm_ttft_ms": 250, "tts_ttfb_ms": 150, "total_ms": ms,
                "stt_provider": "deepgram:nova-3", "llm_provider": llm,
                "tts_provider": "cartesia:sonic-3",
            },
            headers=firm["headers"],
        )
    r = v1_client.get("/v1/analytics/latency", headers=firm["headers"])
    assert r.status_code == 200
    data = r.json()
    assert data["slo_ms"] == 800.0
    assert len(data["by_day"]) == 1 and data["by_day"][0]["turns"] == 3
    providers = {row["llm_provider"]: row for row in data["by_provider"]}
    assert providers["anthropic:claude-haiku-4-5"]["turns"] == 2
    assert providers["openai:gpt-4.1-mini"]["turns"] == 1


def test_analytics_are_tenant_scoped(v1_client, firm, second_firm):
    _seed_funnel(v1_client, firm)
    other = v1_client.get("/v1/analytics/outcomes", headers=second_firm["headers"]).json()
    assert other["calls"] == 0 and other["leads"] == 0
