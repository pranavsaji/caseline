"""Phase 4 — qualification tuning from attorney verdicts.

Pure-engine tests first (suggestions are deterministic, threshold- and
sample-gated), then the end-to-end loop the feature exists for: attorneys
review leads -> suggestions appear -> a human applies the proposed rules
through the normal config PUT -> the very next qualification uses them.
"""

from datetime import date, timedelta

from api.orchestration.config import QualificationRules
from api.tuning import ReviewSample, analyze_reviews, sample_from_row

TODAY = date(2026, 7, 16)


def q(injury, verdict, age=100):
    return ReviewSample(
        verdict=verdict, decision="qualified", injury_type=injury, incident_age_days=age
    )


def r(injury, verdict, age=100):
    return ReviewSample(
        verdict=verdict, decision="refer_out", injury_type=injury, incident_age_days=age
    )


# ---------------------------------------------------------------------------
# suggestion engine (pure)
# ---------------------------------------------------------------------------


def test_frequently_rejected_injury_suggests_refer_out_addition():
    samples = [q("soft tissue only", "rejected") for _ in range(5)] + [
        q("soft tissue only", "accepted")
    ]
    report = analyze_reviews(samples, QualificationRules())
    kinds = {s.kind for s in report.suggestions}
    assert kinds == {"add_refer_out_injury"}
    assert "soft tissue only" in report.proposed_rules["refer_out_injuries"]
    # Proposal validates through the same model the config PUT enforces.
    QualificationRules.model_validate(report.proposed_rules)


def test_frequently_accepted_refer_out_injury_suggests_removal():
    samples = [r("minor", "accepted") for _ in range(5)]
    report = analyze_reviews(samples, QualificationRules())
    assert {s.kind for s in report.suggestions} == {"remove_refer_out_injury"}
    assert "minor" not in report.proposed_rules["refer_out_injuries"]


def test_small_samples_never_generate_suggestions():
    samples = [q("soft tissue only", "rejected") for _ in range(4)]
    report = analyze_reviews(samples, QualificationRules())
    assert report.suggestions == []
    assert report.proposed_rules is None


def test_mixed_verdicts_below_threshold_stay_quiet():
    samples = [q("whiplash", "rejected") for _ in range(5)] + [
        q("whiplash", "accepted") for _ in range(5)
    ]
    report = analyze_reviews(samples, QualificationRules())
    assert report.suggestions == []
    assert report.agreement_rate == 0.5


def test_stale_rejections_suggest_tighter_sol_gate():
    samples = (
        [q("whiplash", "accepted", age=a) for a in (90, 200, 340)]
        + [q("whiplash", "rejected", age=a) for a in (400, 450, 500, 600, 700)]
    )
    report = analyze_reviews(samples, QualificationRules())
    sol = [s for s in report.suggestions if s.kind == "tighten_sol_days"]
    assert len(sol) == 1
    # oldest accepted 340 -> rounded up to whole months = 360, tighter than 730
    assert sol[0].evidence["proposed_sol_days"] == 360
    assert report.proposed_rules["statute_of_limitations_days"] == 360


def test_sol_gate_never_loosens():
    # Attorneys accepting old cases must not widen a legal deadline gate.
    samples = [q("whiplash", "accepted", age=900) for _ in range(5)] + [
        q("whiplash", "rejected", age=100) for _ in range(5)
    ]
    report = analyze_reviews(samples, QualificationRules())
    assert not any(s.kind == "tighten_sol_days" for s in report.suggestions)


def test_sample_from_row_handles_bad_and_future_dates():
    created = TODAY
    good = sample_from_row("accepted", {"incident_date": "2026-01-10", "injury_type": "Burn "}, created)
    assert good.incident_age_days == (TODAY - date(2026, 1, 10)).days
    assert good.injury_type == "burn"
    bad = sample_from_row("rejected", {"incident_date": "last spring"}, created)
    assert bad.incident_age_days is None
    future = sample_from_row("rejected", {"incident_date": "2027-01-01"}, created)
    assert future.incident_age_days is None


# ---------------------------------------------------------------------------
# end to end: review -> suggest -> human applies -> engine behaves differently
# ---------------------------------------------------------------------------


def qualify(v1_client, firm, call_id, injury, days_ago=60):
    r = v1_client.post(
        "/v1/tools/qualify_lead",
        json={
            "call_id": call_id,
            "incident_date": (date.today() - timedelta(days=days_ago)).isoformat(),
            "injury_type": injury,
            "in_treatment": True,
            "has_insurance": True,
        },
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def review(v1_client, firm, lead_id, verdict, **kw):
    return v1_client.post(
        f"/v1/leads/{lead_id}/review",
        json={"verdict": verdict, **kw},
        headers=firm["headers"],
    )


def test_review_endpoint_records_and_overwrites_verdicts(v1_client, firm, db):
    lead = qualify(v1_client, firm, "call-rev-1", "whiplash")
    r = review(v1_client, firm, lead["lead_id"], "accepted", reviewer="R. Vance")
    assert r.status_code == 200
    # Re-review overwrites rather than duplicating.
    assert review(v1_client, firm, lead["lead_id"], "rejected").status_code == 200
    with db.firm(firm["firm_id"]) as conn:
        rows = conn.execute("SELECT verdict FROM lead_reviews").fetchall()
    assert [row["verdict"] for row in rows] == ["rejected"]


def test_review_validates_verdict_and_lead(v1_client, firm):
    lead = qualify(v1_client, firm, "call-rev-2", "whiplash")
    assert review(v1_client, firm, lead["lead_id"], "maybe").status_code == 422
    missing = "00000000-0000-0000-0000-000000000000"
    assert review(v1_client, firm, missing, "accepted").status_code == 404


def test_reviews_drive_suggestions_and_applied_rules_change_decisions(v1_client, firm):
    # Attorneys keep rejecting an injury type the engine qualifies.
    for i in range(5):
        lead = qualify(v1_client, firm, f"call-tune-{i}", "soft tissue only")
        assert lead["decision"] == "qualified"
        assert review(v1_client, firm, lead["lead_id"], "rejected").status_code == 200

    suggestions = v1_client.get("/v1/tuning/suggestions", headers=firm["headers"]).json()
    assert suggestions["reviews"] == 5
    assert suggestions["agreement_rate"] == 0.0
    assert [s["kind"] for s in suggestions["suggestions"]] == ["add_refer_out_injury"]
    assert "soft tissue only" in suggestions["proposed_rules"]["refer_out_injuries"]

    # A human applies the proposal through the normal validated config PUT.
    r = v1_client.put(
        f"/v1/agents/{firm['agent_id']}/config",
        json={"qualification_rules": suggestions["proposed_rules"]},
        headers=firm["headers"],
    )
    assert r.status_code == 200
    # The very next lead with that injury is referred out, not qualified.
    assert qualify(v1_client, firm, "call-tune-after", "soft tissue only")["decision"] == "refer_out"


def test_cross_tenant_reviews_are_invisible(v1_client, firm, second_firm):
    lead = qualify(v1_client, firm, "call-rls", "whiplash")
    assert review(v1_client, second_firm, lead["lead_id"], "accepted").status_code == 404
    suggestions = v1_client.get("/v1/tuning/suggestions", headers=second_firm["headers"]).json()
    assert suggestions["reviews"] == 0
