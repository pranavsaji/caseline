"""Typed tool layer over the v1 API: deterministic, firm-scoped, evented."""


def _qualify(v1_client, firm, call_id="call-1", incident="2026-06-01"):
    return v1_client.post(
        "/v1/tools/qualify_lead",
        json={
            "call_id": call_id,
            "incident_date": incident,
            "injury_type": "whiplash",
            "in_treatment": True,
            "has_insurance": True,
        },
        headers=firm["headers"],
    )


def test_lookup_caller_unknown_then_known(v1_client, firm):
    r = v1_client.post(
        "/v1/tools/lookup_caller", json={"phone": "+15125550142"}, headers=firm["headers"]
    )
    assert r.json() == {"known": False}

    # complete a call that captures the contact, then look them up again
    _qualify(v1_client, firm)
    v1_client.post(
        "/v1/calls/complete",
        json={
            "call_id": "call-1",
            "summary": "Qualified whiplash lead.",
            "structured": {"name": "Dana Torres", "phone": "+15125550142", "decision": "qualified"},
        },
        headers=firm["headers"],
    )
    r = v1_client.post(
        "/v1/tools/lookup_caller", json={"phone": "+15125550142"}, headers=firm["headers"]
    )
    body = r.json()
    assert body["known"] is True
    assert body["name"] == "Dana Torres"
    assert body["last_lead_status"] == "qualified"


def test_qualify_uses_per_firm_rules(v1_client, firm):
    # Default SOL (730d): a 400-day-old incident qualifies.
    r = _qualify(v1_client, firm, call_id="c-old", incident="2025-06-01")
    assert r.json()["decision"] == "qualified"

    # Tighten the firm's SOL to 365d: the same incident now declines.
    v1_client.put(
        f"/v1/agents/{firm['agent_id']}/config",
        json={"qualification_rules": {"statute_of_limitations_days": 365}},
        headers=firm["headers"],
    )
    r = _qualify(v1_client, firm, call_id="c-old-2", incident="2025-06-01")
    assert r.json()["decision"] == "decline"


def test_qualify_creates_lead_and_event(v1_client, firm):
    r = _qualify(v1_client, firm)
    body = r.json()
    assert body["decision"] == "qualified"
    leads = v1_client.get("/v1/leads", headers=firm["headers"]).json()
    assert len(leads) == 1
    assert leads[0]["status"] == "qualified"
    events = v1_client.get("/v1/events", headers=firm["headers"]).json()
    assert any(e["type"] == "lead.qualified" for e in events)


def test_schedule_consult_is_idempotent_under_forced_retry(v1_client, firm):
    payload = {
        "call_id": "call-2",
        "name": "Sam Lee",
        "phone": "+15125550111",
        "slot_iso": "2026-07-21T10:00:00",
        "idempotency_key": "call-2:consult",
    }
    first = v1_client.post("/v1/tools/schedule_consult", json=payload, headers=firm["headers"]).json()
    retry = v1_client.post("/v1/tools/schedule_consult", json=payload, headers=firm["headers"]).json()
    assert first["consult_id"] == retry["consult_id"]
    assert retry["duplicate"] is True
    consults = v1_client.get("/v1/consults", headers=firm["headers"]).json()
    assert len(consults) == 1  # retried booking never double-books


def test_schedule_consult_rejects_bad_slot(v1_client, firm):
    r = v1_client.post(
        "/v1/tools/schedule_consult",
        json={"call_id": "c", "name": "X", "phone": "1", "slot_iso": "tomorrow-ish"},
        headers=firm["headers"],
    )
    assert r.status_code == 422


def test_transfer_to_human_returns_target_and_audits(v1_client, firm):
    r = v1_client.post(
        "/v1/tools/transfer_to_human",
        json={"call_id": "call-3", "reason": "caller asked for a person"},
        headers=firm["headers"],
    )
    body = r.json()
    assert body["action"] == "transfer"
    assert body["target"] == "+15125550199"
    events = v1_client.get("/v1/events", headers=firm["headers"]).json()
    assert any(e["type"] == "call.transfer_requested" for e in events)


def test_transfer_without_number_takes_message(v1_client, second_firm):
    r = v1_client.post(
        "/v1/tools/transfer_to_human",
        json={"call_id": "call-4", "reason": "upset caller"},
        headers=second_firm["headers"],
    )
    body = r.json()
    assert body["action"] == "take_message"
    assert body["target"] is None


def test_send_sms_persists_and_uses_provider(v1_client, firm, platform):
    r = v1_client.post(
        "/v1/tools/send_sms",
        json={"call_id": "call-5", "to": "+15125550100", "body": "See you Tuesday at 2."},
        headers=firm["headers"],
    )
    assert r.json()["status"] == "sent"
    assert platform.sms.sent[-1]["to"] == "+15125550100"
    messages = v1_client.get("/v1/messages", headers=firm["headers"]).json()
    assert len(messages) == 1
    assert messages[0]["direction"] == "out"


def test_take_message_persists(v1_client, firm):
    r = v1_client.post(
        "/v1/tools/take_message",
        json={
            "call_id": "call-6",
            "caller_name": "Adjuster Pat",
            "phone": "+15125550188",
            "body": "Calling about claim 4451.",
        },
        headers=firm["headers"],
    )
    assert r.json()["status"] == "taken"
    messages = v1_client.get("/v1/messages", headers=firm["headers"]).json()
    assert "Adjuster Pat" in messages[0]["body"]
