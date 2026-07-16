"""Phase 4 — smart referrals: declined-but-viable (refer_out) leads routed
to partner firms. Matching is deterministic, proposals are event-driven and
idempotent, and client case facts leave the system only on a human send with
client consent recorded."""

from datetime import date, timedelta

from api.referrals import match_partners, propose_for_lead
from integrations.mock import MockProvider
from workers.cms_sync import EventProcessor
from workers.referrals import ReferralProcessor


# ---------------------------------------------------------------------------
# matching (pure)
# ---------------------------------------------------------------------------


def partner(name, areas=(), states=(), id="p1"):
    return {"id": id, "name": name, "practice_areas": list(areas), "states": list(states)}


def test_explicit_practice_area_match_beats_wildcard():
    partners = [
        partner("Take Anything LLP", id="p1"),
        partner("PI Specialists", areas=["personal injury"], id="p2"),
    ]
    matches = match_partners(partners, "personal injury", None)
    assert [m.partner_name for m in matches] == ["PI Specialists", "Take Anything LLP"]


def test_state_match_breaks_ties():
    partners = [
        partner("Out of State", areas=["personal injury"], states=["NY"], id="p1"),
        partner("Local Firm", areas=["personal injury"], states=["TX"], id="p2"),
    ]
    matches = match_partners(partners, "personal injury", "TX")
    assert matches[0].partner_name == "Local Firm"
    assert "licensed in TX" in matches[0].reasons


def test_wrong_practice_area_is_no_match():
    partners = [partner("Divorce Only", areas=["family law"], id="p1")]
    assert match_partners(partners, "personal injury", "TX") == []


# ---------------------------------------------------------------------------
# event-driven proposals
# ---------------------------------------------------------------------------


def add_partner(v1_client, firm, **overrides):
    body = {
        "name": "Neighboring PI Firm",
        "practice_areas": ["personal injury"],
        "states": ["TX"],
        "contact_email": "intake@neighborfirm.example.com",
    } | overrides
    r = v1_client.post("/v1/referral-partners", json=body, headers=firm["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def qualify(v1_client, firm, call_id, injury="minor"):
    r = v1_client.post(
        "/v1/tools/qualify_lead",
        json={
            "call_id": call_id,
            "incident_date": (date.today() - timedelta(days=30)).isoformat(),
            "injury_type": injury,
            "in_treatment": False,
            "has_insurance": True,
        },
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def make_processor(db, platform, firm):
    return EventProcessor(
        db,
        platform.cipher,
        provider_overrides={firm["firm_id"]: MockProvider()},
        extra_handlers=ReferralProcessor(db).handlers(),
    )


def test_refer_out_lead_gets_exactly_one_proposal(v1_client, firm, db, platform):
    add_partner(v1_client, firm)
    lead = qualify(v1_client, firm, "call-ref-1", injury="minor")
    assert lead["decision"] == "refer_out"
    processor = make_processor(db, platform, firm)
    processor.process_once()

    referrals = v1_client.get("/v1/referrals", headers=firm["headers"]).json()
    assert len(referrals) == 1
    assert referrals[0]["status"] == "proposed"
    assert referrals[0]["partner_name"] == "Neighboring PI Firm"
    assert "handles personal injury" in referrals[0]["match_reasons"]

    # Retry of the same event payload must not propose twice (idempotency).
    assert propose_for_lead(db, firm["firm_id"], {"lead_id": lead["lead_id"]}) is None
    assert len(v1_client.get("/v1/referrals", headers=firm["headers"]).json()) == 1


def test_qualified_leads_are_never_referred(v1_client, firm, db, platform):
    add_partner(v1_client, firm)
    lead = qualify(v1_client, firm, "call-ref-2", injury="whiplash")
    assert lead["decision"] == "qualified"
    make_processor(db, platform, firm).process_once()
    assert v1_client.get("/v1/referrals", headers=firm["headers"]).json() == []


def test_no_partners_means_feature_is_off(v1_client, firm, db, platform):
    qualify(v1_client, firm, "call-ref-3", injury="minor")
    make_processor(db, platform, firm).process_once()
    assert v1_client.get("/v1/referrals", headers=firm["headers"]).json() == []


# ---------------------------------------------------------------------------
# the human send gate
# ---------------------------------------------------------------------------


def proposed_referral(v1_client, firm, db, platform, call_id="call-ref-send"):
    add_partner(v1_client, firm)
    # Real call order: qualify mid-call, complete at hangup — complete_call
    # links the caller's contact onto the lead, which the packet needs.
    qualify(v1_client, firm, call_id, injury="minor")
    r = v1_client.post(
        "/v1/calls/complete",
        json={
            "call_id": call_id,
            "summary": "Caller with a minor injury; refer out.",
            "structured": {"name": "Dana Torres", "phone": "+15125550111"},
            "outcome": "refer_out",
        },
        headers=firm["headers"],
    )
    assert r.status_code == 200
    make_processor(db, platform, firm).process_once()
    referrals = v1_client.get("/v1/referrals", headers=firm["headers"]).json()
    assert len(referrals) == 1
    return referrals[0]


def test_send_requires_client_consent(v1_client, firm, db, platform):
    ref = proposed_referral(v1_client, firm, db, platform)
    r = v1_client.post(
        f"/v1/referrals/{ref['id']}/send",
        json={"client_consent": False},
        headers=firm["headers"],
    )
    assert r.status_code == 422
    assert platform.email.sent == []  # nothing left the system


def test_send_with_consent_emails_partner_and_tracks_status(v1_client, firm, db, platform):
    ref = proposed_referral(v1_client, firm, db, platform)
    r = v1_client.post(
        f"/v1/referrals/{ref['id']}/send",
        json={"client_consent": True},
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    sent = platform.email.sent
    assert len(sent) == 1
    assert sent[0]["to"] == "intake@neighborfirm.example.com"
    assert "Dana Torres" in sent[0]["body"]
    assert "minor" in sent[0]["body"]

    # Double-send is refused; the partner's answer is then tracked.
    assert (
        v1_client.post(
            f"/v1/referrals/{ref['id']}/send",
            json={"client_consent": True},
            headers=firm["headers"],
        ).status_code
        == 409
    )
    r = v1_client.post(
        f"/v1/referrals/{ref['id']}/status",
        json={"status": "accepted"},
        headers=firm["headers"],
    )
    assert r.status_code == 200
    referrals = v1_client.get("/v1/referrals", headers=firm["headers"]).json()
    assert referrals[0]["status"] == "accepted"


def test_status_only_moves_from_sent(v1_client, firm, db, platform):
    ref = proposed_referral(v1_client, firm, db, platform)
    r = v1_client.post(
        f"/v1/referrals/{ref['id']}/status",
        json={"status": "accepted"},
        headers=firm["headers"],
    )
    assert r.status_code == 409  # still proposed, nothing was ever sent


def test_cross_tenant_referrals_are_invisible(v1_client, firm, second_firm, db, platform):
    ref = proposed_referral(v1_client, firm, db, platform)
    assert v1_client.get("/v1/referrals", headers=second_firm["headers"]).json() == []
    r = v1_client.post(
        f"/v1/referrals/{ref['id']}/send",
        json={"client_consent": True},
        headers=second_firm["headers"],
    )
    assert r.status_code == 404  # RLS: does not exist for firm B
