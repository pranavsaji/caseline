"""The pure thread brain: parsers, intake state machine, tracker, preview.

Everything here is side-effect free — the same code path the config studio's
test-call preview runs, which is exactly why it must behave like the live
channels."""

from datetime import date, datetime, timezone

from api.orchestration.config import AgentConfig, GuardrailSettings, QualificationRules
from api.orchestration.threads import (
    advance_intake,
    advance_tracker,
    intake_opening,
    offer_slots,
    parse_date_phrase,
    parse_slot_choice,
    parse_yes_no,
    preview_conversation,
)

NOW = datetime(2026, 7, 16, 15, 0, tzinfo=timezone.utc)  # a Thursday
TODAY = date(2026, 7, 16)


def make_config(**overrides) -> AgentConfig:
    return AgentConfig(
        firm_id="f-1",
        agent_id="a-1",
        firm_name="Bluebonnet Injury Law",
        agent_name="Casey",
        **overrides,
    )


# --- parsers ---


def test_parse_date_phrase_formats():
    assert parse_date_phrase("2026-06-01", TODAY) == "2026-06-01"
    assert parse_date_phrase("it was on 6/1/2026", TODAY) == "2026-06-01"
    assert parse_date_phrase("6/1/26", TODAY) == "2026-06-01"
    assert parse_date_phrase("June 1st", TODAY) == "2026-06-01"
    assert parse_date_phrase("around December 25", TODAY) == "2025-12-25"  # never a future incident
    assert parse_date_phrase("2 weeks ago", TODAY) == "2026-07-02"
    assert parse_date_phrase("a month ago", TODAY) == "2026-06-16"
    assert parse_date_phrase("yesterday", TODAY) == "2026-07-15"
    assert parse_date_phrase("when the moon was full", TODAY) is None
    assert parse_date_phrase("2/30/2026", TODAY) is None  # impossible date


def test_parse_yes_no():
    assert parse_yes_no("Yes") is True
    assert parse_yes_no("yeah I am") is True
    assert parse_yes_no("no") is False
    assert parse_yes_no("I don't have insurance") is False
    assert parse_yes_no("maybe") is None


def test_offer_slots_skips_weekends():
    friday = datetime(2026, 7, 17, 15, 0, tzinfo=timezone.utc)
    slots = offer_slots(friday, "America/Chicago")
    assert len(slots) == 2
    assert all("Monday" in s["label"] for s in slots)  # Fri + 1 -> Sat -> Mon
    assert parse_slot_choice("1", slots) == 0
    assert parse_slot_choice("the afternoon one", slots) == 1
    assert parse_slot_choice("whenever", slots) is None


# --- intake state machine ---


def drive(config, messages, state=None):
    """Feed messages through advance_intake, returning (state, results)."""
    if state is None:
        state, _ = intake_opening(config, "Dana", "web")
    results = []
    for m in messages:
        result = advance_intake(config, state, m, now=NOW, contact_name="Dana")
        state = result.state
        results.append(result)
    return state, results


def test_happy_path_qualifies_and_books():
    config = make_config()
    _, opening = intake_opening(config, "Dana", "web")
    assert "STOP" in opening  # opt-out notice on the first outbound message
    assert "Casey" in opening and "Bluebonnet" in opening

    state, results = drive(config, ["It was on June 1", "broken arm from a car accident", "yes", "yes"])
    qualify = [a for r in results for a in r.actions if a.kind == "qualify"]
    assert len(qualify) == 1
    assert qualify[0].data["decision"] == "qualified"
    assert qualify[0].data["incident_date"] == "2026-06-01"
    assert state["step"] == "offer_slot"
    assert len(state["offered_slots"]) == 2

    _, results = drive(config, ["1"], state=state)
    book = [a for a in results[0].actions if a.kind == "book"]
    assert len(book) == 1
    assert book[0].data["slot_iso"] == state["offered_slots"][0]["iso"]
    assert results[0].close_reason == "booked"


def test_refer_out_injury_closes_kindly():
    config = make_config()
    _, results = drive(config, ["yesterday", "property damage only", "no", "no"])
    assert results[-1].close_reason == "refer_out"
    assert [a.data["decision"] for r in results for a in r.actions if a.kind == "qualify"] == ["refer_out"]


def test_stale_incident_declines():
    config = make_config(qualification=QualificationRules(statute_of_limitations_days=365))
    _, results = drive(config, ["2 years ago", "back injury", "yes", "yes"])
    assert results[-1].close_reason == "decline"


def test_unparseable_date_reasks_once_then_defers_to_humans():
    config = make_config()
    state, results = drive(config, ["when the moon was full", "honestly no idea"])
    assert "didn't catch" in results[0].reply
    assert state["step"] == "collect_injury"  # second failure moves on, never blocks
    assert state["slots"]["incident_date"] == "honestly no idea"
    # ...and the qualification engine flags it instead of declining
    state, results = drive(config, ["whiplash", "yes", "yes"], state=state)
    qualify = [a for r in results for a in r.actions if a.kind == "qualify"][0]
    assert qualify.data["decision"] == "qualified"
    assert any("human verification" in r for r in qualify.data["reasons"])


def test_slot_confusion_hands_off_to_humans():
    config = make_config()
    state, _ = drive(config, ["yesterday", "broken leg", "yes", "yes"])
    state, results = drive(config, ["whenever works", "surprise me"], state=state)
    assert results[0].close_reason is None  # first miss re-asks
    assert results[1].close_reason == "needs_human_scheduling"
    assert [a.kind for a in results[1].actions] == ["take_message"]


# --- treatment tracker ---


def test_tracker_progress_update_schedules_next_checkin():
    config = make_config()
    result = advance_tracker(config, {"cadence_days": 7}, "Still doing PT twice a week")
    kinds = [a.kind for a in result.actions]
    assert kinds == ["tracker_update", "schedule_checkin"]
    assert result.actions[0].data["kind"] == "progress"
    assert result.close_reason is None
    assert "7 days" in result.reply


def test_tracker_completion_closes_thread():
    config = make_config()
    result = advance_tracker(config, {"cadence_days": 14}, "I was discharged last week, all done")
    assert result.close_reason == "treatment_complete"
    assert result.actions[0].data["kind"] == "treatment_complete"


# --- config-studio preview: same brain, zero side effects ---


def test_preview_runs_full_conversation():
    config = make_config()
    out = preview_conversation(
        config, ["two weeks ago", "broken arm", "yes", "yes", "1"], now=NOW
    )
    assert out["closed_reason"] == "booked"
    assert [a["kind"] for a in out["actions"]] == ["qualify", "book"]
    assert out["turns"][0]["role"] == "agent"
    assert "Casey" in out["instructions"]


def test_preview_applies_guardrails_to_replies():
    config = make_config(
        guardrails=GuardrailSettings(extra_blocked_patterns=[r"\bGood news\b"])
    )
    out = preview_conversation(config, ["yesterday", "broken arm", "yes", "yes"], now=NOW)
    deflected = [t for t in out["turns"] if t.get("guardrail_tripped")]
    assert len(deflected) == 1
    assert deflected[0]["text"] == config.guardrails.deflection_line
