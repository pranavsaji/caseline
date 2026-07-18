"""Operator-initiated outbound dial endpoint (POST /v1/calls/dial).

Without a SIP outbound trunk configured the default LoggingDialer records the
intent but does not place a call (placed=false); the attempt still lands as a
`calls` row and a `call.outbound_requested` event.
"""


def test_dial_records_call_as_dry_run(v1_client, firm):
    r = v1_client.post(
        "/v1/calls/dial",
        json={"to_number": "+14155550123", "purpose": "partner firm intro"},
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["placed"] is False  # LoggingDialer default (no SIP trunk)
    assert body["dialer"] == "logging"
    assert body["call_id"].startswith("outbound-manual-")
    assert body["note"]  # explains the dry-run

    # The attempt is durably recorded as an outbound call.
    calls = v1_client.get("/v1/calls", headers=firm["headers"]).json()
    assert any(c["id"] == body["call_id"] and c["direction"] == "out" for c in calls)


def test_dial_normalizes_operator_pasted_number(v1_client, firm):
    # Operators paste numbers straight off a screen; the endpoint forgives
    # common US formatting (dashes, a bare 10-digit number) and coerces to E.164.
    r = v1_client.post(
        "/v1/calls/dial",
        json={"to_number": "415-555-0123"},
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["to_number"] == "+14155550123"


def test_dial_rejects_non_e164(v1_client, firm):
    # Genuinely un-dialable input (letters, too few digits) can't be coerced.
    r = v1_client.post(
        "/v1/calls/dial",
        json={"to_number": "555-CALL-NOW"},
        headers=firm["headers"],
    )
    assert r.status_code == 422, r.text


def test_dial_requires_auth(v1_client):
    r = v1_client.post("/v1/calls/dial", json={"to_number": "+14155550123"})
    assert r.status_code in (401, 403)
