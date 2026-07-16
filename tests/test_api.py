"""Backend endpoint tests against an isolated per-test SQLite database."""


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_qualify_endpoint_qualified(client):
    r = client.post(
        "/qualify",
        json={
            "incident_date": "2026-06-01",
            "injury_type": "whiplash",
            "in_treatment": True,
            "has_insurance": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "qualified"
    assert body["reasons"]


def test_qualify_endpoint_decline(client):
    r = client.post(
        "/qualify",
        json={
            "incident_date": "2020-01-01",
            "injury_type": "whiplash",
            "in_treatment": False,
            "has_insurance": True,
        },
    )
    assert r.json()["decision"] == "decline"


def test_qualify_endpoint_validation_error(client):
    r = client.post("/qualify", json={"incident_date": "2026-06-01"})
    assert r.status_code == 422


def test_schedule_persists_consult(client):
    r = client.post(
        "/schedule",
        json={"name": "Jamie Doe", "phone": "+15125550100", "slot_iso": "2026-07-20T15:00:00"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "booked"

    consults = client.get("/consults").json()
    assert len(consults) == 1
    assert consults[0]["name"] == "Jamie Doe"
    assert consults[0]["slot_iso"] == "2026-07-20T15:00:00"


def test_mock_cms_round_trip(client):
    structured = {
        "incident_date": "2026-06-01",
        "injury_type": "whiplash",
        "in_treatment": True,
        "has_insurance": True,
        "decision": "qualified",
    }
    r = client.post(
        "/mock-cms",
        json={"call_id": "room-abc", "summary": "New PI lead, consult booked.", "structured": structured},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "saved"

    records = client.get("/mock-cms").json()
    assert len(records) == 1
    assert records[0]["call_id"] == "room-abc"
    assert records[0]["structured"] == structured  # JSON survives the round trip intact


def test_turn_metrics_and_call_summary(client):
    # 20 turns: 19 fast, 1 slow — p95 stays under budget, max shows the outlier.
    for i in range(19):
        client.post(
            "/metrics/turn",
            json={
                "call_id": "room-abc",
                "speech_id": f"turn-{i}",
                "eou_delay_ms": 150.0,
                "llm_ttft_ms": 200.0,
                "tts_ttfb_ms": 80.0,
                "total_ms": 430.0,
            },
        )
    client.post(
        "/metrics/turn",
        json={
            "call_id": "room-abc",
            "speech_id": "turn-slow",
            "eou_delay_ms": 400.0,
            "llm_ttft_ms": 700.0,
            "tts_ttfb_ms": 150.0,
            "total_ms": 1250.0,
        },
    )
    summary = client.get("/metrics/calls/room-abc").json()
    assert summary["turns"] == 20
    assert summary["p50_ms"] == 430.0
    assert summary["max_ms"] == 1250.0
    assert summary["within_budget"] is True


def test_call_summary_empty_call(client):
    summary = client.get("/metrics/calls/no-such-call").json()
    assert summary["turns"] == 0
    assert summary["p50_ms"] is None
    assert summary["within_budget"] is None


def test_call_summary_over_budget(client):
    for i in range(3):
        client.post(
            "/metrics/turn",
            json={
                "call_id": "slow-call",
                "speech_id": f"t{i}",
                "eou_delay_ms": 500.0,
                "llm_ttft_ms": 600.0,
                "tts_ttfb_ms": 200.0,
                "total_ms": 1300.0,
            },
        )
    summary = client.get("/metrics/calls/slow-call").json()
    assert summary["within_budget"] is False
