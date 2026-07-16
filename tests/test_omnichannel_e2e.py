"""Phase 3 end-to-end: webform -> chaser -> SMS thread -> booking -> CMS,
plus consent enforcement, opt-out, nudges, tracker, preview, and tenancy.

Exit criteria exercised here:
  * lead-to-first-contact under 60 s from webform submit (measured, not assumed)
  * one firm running voice + SMS + chaser + tracker on the same brain
"""

from datetime import datetime, timedelta, timezone

import pytest

from api.compliance.outbound import OutboundPolicy
from integrations.mock import MockProvider
from workers.cms_sync import EventProcessor
from workers.omnichannel import OmniProcessor

LEAD_PHONE = "+15125550111"
ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token"}


@pytest.fixture
def cms(firm, platform):
    return MockProvider()


@pytest.fixture
def omni(platform):
    return OmniProcessor(
        platform.db, platform.session_store, platform.sms, platform.email, platform.dialer
    )


@pytest.fixture
def processor(db, platform, firm, cms, omni):
    return EventProcessor(
        db, platform.cipher, provider_overrides={firm["firm_id"]: cms}, extra_handlers=omni.handlers()
    )


def drain(processor):
    while processor.process_once()["processed"]:
        pass


def submit_lead(v1_client, firm, **overrides):
    body = {
        "name": "Dana Torres",
        "phone": LEAD_PHONE,
        "source": "web",
        "sms_consent": True,
        "consent_source": "landing-page checkbox",
        "details": {"campaign": "brand-search"},
    } | overrides
    r = v1_client.post("/v1/hooks/leads", json=body, headers=firm["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def inbound_sms(v1_client, firm, body, from_number=LEAD_PHONE):
    r = v1_client.post(
        "/v1/hooks/sms",
        json={"from_number": from_number, "body": body},
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def force_due_followups(db):
    with db.admin() as conn:
        conn.execute(
            "UPDATE followups SET due_at = now() - interval '1 minute' WHERE status = 'pending'"
        )


# ---------------------------------------------------------------------------
# Digital Lead Chaser
# ---------------------------------------------------------------------------


def test_webform_lead_gets_first_contact_within_seconds(v1_client, firm, platform, processor):
    submitted_at = datetime.now(timezone.utc)
    submit_lead(v1_client, firm)
    processor.process_once()

    sent = platform.sms.sent
    assert len(sent) == 1 and sent[0]["to"] == LEAD_PHONE
    assert "Dana" in sent[0]["body"] and "STOP" in sent[0]["body"]

    threads = v1_client.get("/v1/threads", headers=firm["headers"]).json()
    assert len(threads) == 1 and threads[0]["status"] == "open" and threads[0]["goal"] == "intake"

    leads = v1_client.get("/v1/leads", headers=firm["headers"]).json()
    assert leads[0]["status"] == "contacted"

    chaser = v1_client.get("/v1/analytics/chaser", headers=firm["headers"]).json()
    assert chaser["web_ad_leads"] == 1 and chaser["contacted"] == 1
    assert chaser["under_60s_rate"] == 1.0  # the Phase 3 exit criterion, measured
    assert chaser["first_contact_p95_seconds"] < 60
    assert datetime.now(timezone.utc) - submitted_at < timedelta(seconds=60)


def test_full_sms_conversation_to_booking_and_cms(v1_client, firm, platform, processor, cms, db):
    submit_lead(v1_client, firm)
    processor.process_once()
    for reply in ["It was on June 1", "back injury from a car accident", "yes", "yes", "1"]:
        inbound_sms(v1_client, firm, reply)
        processor.process_once()
    drain(processor)

    consults = v1_client.get("/v1/consults", headers=firm["headers"]).json()
    assert len(consults) == 1  # exactly one booking, no duplicates
    leads = v1_client.get("/v1/leads", headers=firm["headers"]).json()
    assert leads[0]["status"] == "qualified"
    threads = v1_client.get("/v1/threads", headers=firm["headers"]).json()
    assert threads[0]["status"] == "closed" and threads[0]["closed_reason"] == "booked"
    # consult.booked flowed through the same CMS pipeline as voice calls
    assert len(cms.tasks) == 1
    # the reply disarmed pending nudges; booking canceled the rest
    with db.admin() as conn:
        pending = conn.execute(
            "SELECT count(*) AS n FROM followups WHERE status = 'pending'"
        ).fetchone()["n"]
    assert pending == 0
    # transcript of the whole exchange is visible per thread
    detail = v1_client.get(
        f"/v1/threads/{threads[0]['id']}", headers=firm["headers"]
    ).json()
    assert len(detail["messages"]) >= 10  # 5 caller + 6 agent turns


def test_no_consent_blocks_the_chase(v1_client, firm, platform, processor):
    submit_lead(v1_client, firm, sms_consent=False)
    processor.process_once()
    assert platform.sms.sent == []
    assert v1_client.get("/v1/threads", headers=firm["headers"]).json() == []
    events = v1_client.get("/v1/events", headers=firm["headers"]).json()
    assert any(e["type"] == "lead.chase_blocked" for e in events)


def test_quiet_hours_defer_the_chase_not_drop_it(
    v1_client, firm, platform, processor, omni, db, monkeypatch
):
    deferred = OutboundPolicy(
        allowed=False,
        reason="quiet hours",
        defer_until=datetime.now(timezone.utc) + timedelta(hours=8),
    )
    monkeypatch.setattr("workers.omnichannel.outbound_policy", lambda *a, **k: deferred)
    submit_lead(v1_client, firm)
    processor.process_once()
    assert platform.sms.sent == []  # nothing sent inside quiet hours

    force_due_followups(db)  # the deferred start comes due
    counts = omni.process_due_followups()
    assert counts["executed"] == 1
    assert len(platform.sms.sent) == 1
    assert v1_client.get("/v1/threads", headers=firm["headers"]).json()[0]["status"] == "open"


def test_voice_preferred_lead_dials_out(v1_client, firm, platform, processor):
    submit_lead(v1_client, firm, preferred_channel="voice")
    processor.process_once()
    assert len(platform.dialer.dialed) == 1
    assert platform.dialer.dialed[0]["to"] == LEAD_PHONE
    calls = v1_client.get("/v1/calls", headers=firm["headers"]).json()
    assert calls[0]["direction"] == "out"
    events = v1_client.get("/v1/events", headers=firm["headers"]).json()
    assert any(e["type"] == "call.outbound_requested" for e in events)


def test_lead_webhook_validation(v1_client, firm):
    r = v1_client.post(
        "/v1/hooks/leads", json={"name": "Nobody Reachable"}, headers=firm["headers"]
    )
    assert r.status_code == 422
    r = v1_client.post(
        "/v1/hooks/leads",
        json={"name": "X", "phone": LEAD_PHONE, "source": "spam"},
        headers=firm["headers"],
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Opt-out (STOP) — immediate, unconditional, permanent
# ---------------------------------------------------------------------------


def test_stop_revokes_consent_closes_threads_and_sticks(
    v1_client, firm, platform, processor, db
):
    submit_lead(v1_client, firm)
    processor.process_once()
    assert len(platform.sms.sent) == 1

    out = inbound_sms(v1_client, firm, "STOP")
    assert out["status"] == "opted_out"
    assert "unsubscribed" in platform.sms.sent[-1]["body"]  # CTIA confirmation

    threads = v1_client.get("/v1/threads", headers=firm["headers"]).json()
    assert threads[0]["status"] == "closed" and threads[0]["closed_reason"] == "opted_out"
    with db.admin() as conn:
        pending = conn.execute(
            "SELECT count(*) AS n FROM followups WHERE status = 'pending'"
        ).fetchone()["n"]
    assert pending == 0

    # A fresh form submit does NOT resurrect consent — only the person can.
    sent_before = len(platform.sms.sent)
    submit_lead(v1_client, firm, sms_consent=True)
    drain(processor)
    assert len(platform.sms.sent) == sent_before
    events = v1_client.get("/v1/events", headers=firm["headers"]).json()
    assert any(e["type"] == "lead.chase_blocked" for e in events)


def test_help_keyword_gets_informational_reply(v1_client, firm, platform):
    out = inbound_sms(v1_client, firm, "HELP")
    assert out["status"] == "help_sent"
    assert "STOP" in platform.sms.sent[-1]["body"]


# ---------------------------------------------------------------------------
# Nudges and cold inbound
# ---------------------------------------------------------------------------


def test_unresponsive_lead_is_nudged_then_closed(v1_client, firm, platform, processor, omni, db):
    submit_lead(v1_client, firm)
    processor.process_once()
    for _ in range(2):  # two nudges...
        force_due_followups(db)
        omni.process_due_followups()
    assert len(platform.sms.sent) == 3  # opening + 2 nudges
    force_due_followups(db)  # ...then give up politely
    omni.process_due_followups()
    threads = v1_client.get("/v1/threads", headers=firm["headers"]).json()
    assert threads[0]["status"] == "closed" and threads[0]["closed_reason"] == "unresponsive"


def test_cold_inbound_sms_starts_intake(v1_client, firm, platform, processor):
    inbound_sms(v1_client, firm, "I got rear-ended yesterday", from_number="+15125550999")
    processor.process_once()
    threads = v1_client.get("/v1/threads", headers=firm["headers"]).json()
    assert len(threads) == 1 and threads[0]["goal"] == "intake"
    assert platform.sms.sent[-1]["to"] == "+15125550999"
    assert "what date" in platform.sms.sent[-1]["body"].lower()


# ---------------------------------------------------------------------------
# Treatment tracker
# ---------------------------------------------------------------------------


def test_tracker_checkins_updates_and_completion(v1_client, firm, platform, processor, omni, cms, db):
    r = v1_client.post(
        "/v1/tracker/enroll",
        json={
            "name": "Sam Client",
            "phone": "+15125550777",
            "matter_description": "MVA 2026-05-02",
            "cadence_days": 7,
        },
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    assert "check in every 7 days" in platform.sms.sent[-1]["body"]

    force_due_followups(db)  # first scheduled check-in comes due
    omni.process_due_followups()
    assert "how is your treatment going" in platform.sms.sent[-1]["body"].lower()

    inbound_sms(v1_client, firm, "Still doing physical therapy weekly", from_number="+15125550777")
    drain(processor)
    assert any("progress" in t["name"] for t in cms.tasks.values())  # CMS task created
    with db.admin() as conn:  # and the next check-in is armed
        n = conn.execute(
            "SELECT count(*) AS n FROM followups WHERE status = 'pending' AND type = 'tracker.checkin'"
        ).fetchone()["n"]
    assert n == 1

    inbound_sms(v1_client, firm, "Doctor says I'm all done, discharged", from_number="+15125550777")
    drain(processor)
    threads = v1_client.get("/v1/threads", headers=firm["headers"]).json()
    tracker = [t for t in threads if t["goal"] == "treatment_tracker"][0]
    assert tracker["status"] == "closed" and tracker["closed_reason"] == "treatment_complete"
    assert any("treatment_complete" in t["name"] for t in cms.tasks.values())


# ---------------------------------------------------------------------------
# Config studio: preview endpoint + onboarding metric
# ---------------------------------------------------------------------------


def test_preview_endpoint_runs_same_brain_with_no_side_effects(v1_client, firm):
    agents = v1_client.get("/v1/agents", headers=firm["headers"]).json()
    assert len(agents) == 1
    r = v1_client.post(
        f"/v1/agents/{agents[0]['id']}/preview",
        json={"messages": ["two weeks ago", "broken arm", "yes", "yes", "1"]},
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["closed_reason"] == "booked"
    assert [a["kind"] for a in out["actions"]] == ["qualify", "book"]
    # zero side effects: nothing persisted anywhere
    assert v1_client.get("/v1/threads", headers=firm["headers"]).json() == []
    assert v1_client.get("/v1/consults", headers=firm["headers"]).json() == []
    assert v1_client.get("/v1/leads", headers=firm["headers"]).json() == []


def test_preview_honors_unsaved_config_overrides(v1_client, firm):
    agents = v1_client.get("/v1/agents", headers=firm["headers"]).json()
    r = v1_client.post(
        f"/v1/agents/{agents[0]['id']}/preview",
        json={
            "messages": ["two months ago", "broken arm", "yes", "yes"],
            "qualification_rules": {"statute_of_limitations_days": 10},
        },
        headers=firm["headers"],
    )
    assert r.status_code == 200
    assert r.json()["closed_reason"] == "decline"
    # invalid override is rejected, not silently ignored
    r = v1_client.post(
        f"/v1/agents/{agents[0]['id']}/preview",
        json={"messages": ["hi"], "qualification_rules": {"statute_of_limitations_days": "soon"}},
        headers=firm["headers"],
    )
    assert r.status_code == 422


def test_onboarding_metric_tracks_time_to_first_call(v1_client, firm):
    r = v1_client.get("/v1/admin/ops/onboarding", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    row = [f for f in r.json()["firms"] if f["id"] == firm["firm_id"]][0]
    assert row["first_call_at"] is None
    v1_client.post(
        "/v1/calls/complete",
        json={"call_id": "call-onb-1", "summary": "s", "structured": {}},
        headers=firm["headers"],
    )
    row = [
        f
        for f in v1_client.get("/v1/admin/ops/onboarding", headers=ADMIN_HEADERS).json()["firms"]
        if f["id"] == firm["firm_id"]
    ][0]
    assert row["first_call_at"] is not None
    assert row["time_to_first_call_seconds"] >= 0


# ---------------------------------------------------------------------------
# Tenancy: threads are as isolated as everything else
# ---------------------------------------------------------------------------


def test_threads_are_tenant_isolated(v1_client, firm, second_firm, processor):
    submit_lead(v1_client, firm)
    processor.process_once()
    mine = v1_client.get("/v1/threads", headers=firm["headers"]).json()
    assert len(mine) == 1
    assert v1_client.get("/v1/threads", headers=second_firm["headers"]).json() == []
    r = v1_client.get(f"/v1/threads/{mine[0]['id']}", headers=second_firm["headers"])
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# The Phase 3 exit picture: voice + SMS chaser + tracker on one brain
# ---------------------------------------------------------------------------


def test_one_firm_runs_voice_sms_chaser_and_tracker_together(
    v1_client, firm, platform, processor, omni, cms, db
):
    # Voice path (Phase 1 tools) — unchanged
    v1_client.post(
        "/v1/tools/qualify_lead",
        json={
            "call_id": "call-mix-1",
            "incident_date": "2026-06-01",
            "injury_type": "whiplash",
            "in_treatment": True,
            "has_insurance": True,
        },
        headers=firm["headers"],
    )
    v1_client.post(
        "/v1/calls/complete",
        json={
            "call_id": "call-mix-1",
            "summary": "Voice intake",
            "structured": {"name": "Voice Caller", "phone": "+15125550301", "decision": "qualified"},
        },
        headers=firm["headers"],
    )
    # Chaser + SMS thread
    submit_lead(v1_client, firm)
    processor.process_once()
    inbound_sms(v1_client, firm, "It was on June 1")
    # Tracker
    v1_client.post(
        "/v1/tracker/enroll",
        json={"name": "Sam Client", "phone": "+15125550777", "cadence_days": 14},
        headers=firm["headers"],
    )
    drain(processor)

    threads = v1_client.get("/v1/threads", headers=firm["headers"]).json()
    goals = sorted(t["goal"] for t in threads)
    assert goals == ["intake", "treatment_tracker"]
    calls = v1_client.get("/v1/calls", headers=firm["headers"]).json()
    assert any(c["id"] == "call-mix-1" for c in calls)
    assert len(cms.contacts) >= 1  # the voice call synced through the same pipeline
    leads = v1_client.get("/v1/leads", headers=firm["headers"]).json()
    assert {l["source"] for l in leads} == {"phone", "web"}
