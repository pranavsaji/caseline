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


def test_hangup_ends_call_and_is_idempotent(v1_client, firm):
    # Place a (dry-run) call, then hang it up from the dashboard. The default
    # LoggingDialer never held a real room, so hangup reports "already_ended" —
    # but the endpoint succeeds and emits the event.
    placed = v1_client.post(
        "/v1/calls/dial",
        json={"to_number": "+14155550123"},
        headers=firm["headers"],
    ).json()
    call_id = placed["call_id"]

    r = v1_client.post(f"/v1/calls/{call_id}/hangup", headers=firm["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "already_ended"  # LoggingDialer: nothing to tear down
    assert r.json()["call_id"] == call_id

    # Idempotent: a second hangup on the same call still succeeds.
    again = v1_client.post(f"/v1/calls/{call_id}/hangup", headers=firm["headers"])
    assert again.status_code == 200


def test_hangup_unknown_call_is_404(v1_client, firm):
    r = v1_client.post("/v1/calls/outbound-manual-doesnotexist/hangup", headers=firm["headers"])
    assert r.status_code == 404


def test_hangup_requires_auth(v1_client):
    r = v1_client.post("/v1/calls/outbound-manual-x/hangup")
    assert r.status_code in (401, 403)
