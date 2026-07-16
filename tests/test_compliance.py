"""Phase 2 compliance: PII redaction pipeline, per-state consent, gated raw
transcripts, log scrubbing. Exit criterion: redaction verified on
transcripts and logs."""

import logging

from api.compliance.consent import area_code_of, consent_policy
from api.compliance.redaction import (
    RedactingFilter,
    redact_structured,
    redact_text,
    redact_turns,
)

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_redacts_ssn_email_phone_card_address():
    text = (
        "My SSN is 123-45-6789, email dana.torres@example.com, "
        "call me at (512) 555-0142 or +15125550142. Card 4111 1111 1111 1111. "
        "I live at 42 Maple Street."
    )
    out = redact_text(text)
    assert "123-45-6789" not in out
    assert "dana.torres@example.com" not in out
    assert "555-0142" not in out
    assert "15125550142" not in out
    assert "4111" not in out
    assert "42 Maple Street" not in out
    assert "[REDACTED:ssn]" in out and "[REDACTED:email]" in out
    assert "[REDACTED:phone]" in out and "[REDACTED:card]" in out
    assert "[REDACTED:address]" in out


def test_incident_dates_and_case_facts_survive_redaction():
    """Dates are case facts the pipeline runs on — never redacted."""
    text = "The crash happened on 2026-03-15 and I saw Dr. Smith on March 20."
    assert redact_text(text) == text


def test_non_card_digit_runs_survive():
    """A 13-16 digit claim number that fails Luhn is not a credit card."""
    text = "My claim number is 1234567890123456."
    assert "1234567890123456" in redact_text(text) or "[REDACTED:card]" not in redact_text(text)


def test_redact_turns_does_not_mutate_original():
    turns = [{"role": "user", "text": "Call me at 512-555-0142."}]
    redacted = redact_turns(turns)
    assert "555-0142" in turns[0]["text"]
    assert "[REDACTED:phone]" in redacted[0]["text"]


def test_redact_structured_is_key_aware():
    payload = {
        "name": "Dana Torres",
        "phone": "+15125550142",
        "decision": "qualified",
        "nested": {"email": "d@example.com", "summary": "reach her at 512-555-0142"},
    }
    out = redact_structured(payload)
    assert out["name"] == "[REDACTED:name]"
    assert out["phone"] == "[REDACTED:phone]"
    assert out["decision"] == "qualified"  # non-PII fields untouched
    assert out["nested"]["email"] == "[REDACTED:email]"
    assert "[REDACTED:phone]" in out["nested"]["summary"]


def test_logging_filter_scrubs_records(caplog):
    logger = logging.getLogger("caseline.test.redaction")
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    records = []
    handler.emit = lambda record: records.append(record.getMessage())  # capture post-filter
    logger.addHandler(handler)
    logger.propagate = False
    logger.warning("caller %s booked", "+15125550142")
    logger.removeHandler(handler)
    assert records and "+15125550142" not in records[0]
    assert "[REDACTED:phone]" in records[0]


# ---------------------------------------------------------------------------
# Per-state consent
# ---------------------------------------------------------------------------


def test_area_code_parsing():
    assert area_code_of("+15125550142") == 512
    assert area_code_of("(415) 555-0100") == 415
    assert area_code_of("5551") is None
    assert area_code_of(None) is None


def test_one_party_caller_and_firm_needs_no_forced_disclosure():
    policy = consent_policy("+15125550142", firm_state="TX")  # TX <-> TX, one-party
    assert policy.caller_state == "TX"
    assert not policy.two_party


def test_two_party_caller_state_forces_disclosure():
    policy = consent_policy("+14155550100", firm_state="TX")  # CA caller
    assert policy.caller_state == "CA"
    assert policy.two_party and policy.disclosure_required


def test_two_party_firm_state_forces_disclosure():
    policy = consent_policy("+15125550142", firm_state="WA")  # WA firm
    assert policy.two_party


def test_unknown_number_defaults_to_two_party():
    """Toll-free/unknown/international -> safe default: assume all-party."""
    assert consent_policy("+448081570192", firm_state="TX").two_party
    assert consent_policy(None, firm_state="TX").two_party
    assert consent_policy("+18005550100", firm_state="TX").two_party  # 800 unmapped


# ---------------------------------------------------------------------------
# API wiring: gated transcripts + consent in agent config
# ---------------------------------------------------------------------------


def _post_transcript(v1_client, firm, call_id="call-red-1"):
    r = v1_client.post(
        f"/v1/calls/{call_id}/transcript",
        json={
            "turns": [
                {"role": "user", "text": "My number is 512-555-0142, email d@example.com"},
                {"role": "assistant", "text": "Got it, thanks Dana."},
            ]
        },
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    return call_id


def test_default_token_gets_redacted_transcript(v1_client, firm):
    call_id = _post_transcript(v1_client, firm)
    call = v1_client.get(f"/v1/calls/{call_id}", headers=firm["headers"]).json()
    assert call["transcript_redacted"] is True
    text = " ".join(t["text"] for t in call["transcript"])
    assert "512-555-0142" not in text and "d@example.com" not in text
    assert "[REDACTED:phone]" in text


def test_raw_scope_token_gets_unredacted_transcript(v1_client, firm):
    call_id = _post_transcript(v1_client, firm, call_id="call-red-2")
    r = v1_client.post(
        f"/v1/admin/firms/{firm['firm_id']}/tokens",
        json={"name": "compliance-review", "scopes": ["transcripts:raw"]},
        headers={"X-Admin-Token": "test-admin-token"},
    )
    raw_headers = {"Authorization": f"Bearer {r.json()['token']}"}
    call = v1_client.get(f"/v1/calls/{call_id}", headers=raw_headers).json()
    assert call["transcript_redacted"] is False
    assert "512-555-0142" in call["transcript"][0]["text"]


def test_agent_config_includes_consent_and_forces_disclosure(v1_client, firm):
    # Firm turns the disclosure off...
    agents_cfg = v1_client.get("/v1/agent-config", headers=firm["headers"]).json()
    r = v1_client.put(
        f"/v1/agents/{agents_cfg['agent_id']}/config",
        json={"script_config": {"recording_disclosure": False, "firm_state": "TX"}},
        headers=firm["headers"],
    )
    assert r.status_code == 200
    # ...a Texas caller: one-party, disclosure stays off.
    cfg = v1_client.get(
        "/v1/agent-config", params={"from_number": "+15125550142"}, headers=firm["headers"]
    ).json()
    assert cfg["consent"] == {
        "caller_state": "TX", "two_party": False, "disclosure_required": False,
    }
    assert not cfg["script"]["recording_disclosure"]
    # ...a California caller: two-party rules override the firm's setting.
    cfg = v1_client.get(
        "/v1/agent-config", params={"from_number": "+14155550100"}, headers=firm["headers"]
    ).json()
    assert cfg["consent"]["two_party"] is True
    assert cfg["script"]["recording_disclosure"] is True
    assert "recorded" in cfg["instructions"]


def test_complete_call_records_consent_policy(v1_client, firm):
    r = v1_client.post(
        "/v1/calls/complete",
        json={
            "call_id": "call-consent-1",
            "summary": "Qualified lead.",
            "structured": {"decision": "qualified"},
            "consent_state": "CA",
            "two_party_consent": True,
        },
        headers=firm["headers"],
    )
    assert r.status_code == 200
    call = v1_client.get("/v1/calls/call-consent-1", headers=firm["headers"]).json()
    assert call["consent_state"] == "CA"
    assert call["two_party_consent"] is True
