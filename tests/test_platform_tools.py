"""Typed tool layer over the v1 API: deterministic, firm-scoped, evented."""

from api.messaging import normalize_phone


def test_normalize_phone():
    assert normalize_phone("124830370") is None  # STT-dropped digit -> refused
    assert normalize_phone("3125551212") == "+13125551212"  # bare US 10-digit
    assert normalize_phone("1 312 555 1212") == "+13125551212"
    assert normalize_phone("+1 (312) 555-1212") == "+13125551212"
    assert normalize_phone("") is None
    assert normalize_phone("12") is None


def test_available_slots_returns_open_business_hours(v1_client, firm):
    r = v1_client.get("/v1/tools/available_slots", headers=firm["headers"])
    assert r.status_code == 200
    slots = r.json()["slots"]
    assert slots, "expected at least one open slot"
    assert all("slot_iso" in s and "label" in s for s in slots)


def test_available_slots_spread_across_multiple_days(v1_client, firm):
    # Availability should span the coming weeks (a tester any day this month
    # sees open times), not pile onto the first day. With the default window and
    # a couple of slots per day, several distinct calendar days must appear.
    slots = v1_client.get("/v1/tools/available_slots", headers=firm["headers"]).json()["slots"]
    days = {s["slot_iso"][:10] for s in slots}
    assert len(days) >= 3, f"slots clustered on too few days: {sorted(days)}"
    # And no single day hogs the list (max_per_day guard).
    from collections import Counter
    per_day = Counter(s["slot_iso"][:10] for s in slots)
    assert max(per_day.values()) <= 3


def test_schedule_consult_rejects_taken_slot_with_alternatives(v1_client, firm):
    slot = v1_client.get("/v1/tools/available_slots", headers=firm["headers"]).json()["slots"][0]
    ok = v1_client.post(
        "/v1/tools/schedule_consult",
        json={"call_id": "c1", "name": "A", "phone": "+13125551212", "slot_iso": slot["slot_iso"]},
        headers=firm["headers"],
    )
    assert ok.json()["status"] == "booked"
    # Someone else asks for the same time -> unavailable, with real alternatives.
    clash = v1_client.post(
        "/v1/tools/schedule_consult",
        json={"call_id": "c2", "name": "B", "phone": "+13125551213", "slot_iso": slot["slot_iso"]},
        headers=firm["headers"],
    )
    body = clash.json()
    assert body["status"] == "unavailable" and body["alternatives"]


def test_send_sms_invalid_number_is_graceful(v1_client, firm):
    r = v1_client.post(
        "/v1/tools/send_sms",
        json={"call_id": "c", "to": "124830370", "body": "hi"},
        headers=firm["headers"],
    )
    assert r.status_code == 200
    assert r.json()["status"] == "failed" and r.json()["reason"] == "invalid_number"


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
    # An unparseable slot is a graceful "unavailable" (with alternatives to
    # offer), not an HTTP error that would crash the agent's tool call.
    r = v1_client.post(
        "/v1/tools/schedule_consult",
        json={"call_id": "c", "name": "X", "phone": "1", "slot_iso": "tomorrow-ish"},
        headers=firm["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "bad_slot"


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


def test_send_sms_disabled_does_not_reach_provider(v1_client, firm, platform, monkeypatch):
    # With outbound SMS switched off (e.g. pending A2P 10DLC approval) the tool
    # reports a normal failure and never hands the message to the transport, so
    # the agent can steer around it instead of promising a text that bounces.
    monkeypatch.setenv("CASELINE_SMS_ENABLED", "false")
    before = len(platform.sms.sent)
    r = v1_client.post(
        "/v1/tools/send_sms",
        json={"call_id": "call-7", "to": "+15125550100", "body": "See you Tuesday."},
        headers=firm["headers"],
    )
    assert r.status_code == 200
    assert r.json() == {"status": "failed", "reason": "disabled", "to": "+15125550100"}
    assert len(platform.sms.sent) == before


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
