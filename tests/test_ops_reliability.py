"""Phase 2 reliability: concurrent workers never double-process an event
(the claim-protocol fix), crashed claims are reclaimed via visibility
timeout, and the DLQ has replay tooling + alerting behind admin ops
endpoints. Exit criterion: zero duplicate CMS writes under fault injection —
now including the concurrency dimension."""

import threading

from api.platform import alerts, events
from integrations.mock import MockProvider
from workers.cms_sync import EventProcessor

ADMIN = {"X-Admin-Token": "test-admin-token"}


def _complete_call(v1_client, firm, call_id, name, phone):
    r = v1_client.post(
        "/v1/calls/complete",
        json={
            "call_id": call_id,
            "summary": "Qualified lead.",
            "structured": {"name": name, "phone": phone, "decision": "qualified"},
        },
        headers=firm["headers"],
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Concurrent claim safety
# ---------------------------------------------------------------------------


def test_concurrent_workers_never_double_process(v1_client, firm, db, platform):
    """Two workers race the same outbox: every event is handled exactly once.

    Before the Phase 2 claim protocol, claim_pending's row locks died with
    the claim transaction while events stayed 'pending' — a second poller
    could re-claim and re-write to the CMS."""
    n = 12
    for i in range(n):
        _complete_call(
            v1_client, firm, f"call-race-{i}", f"Caller {i}", f"+1512555{1000 + i:04d}"
        )

    cms_a, cms_b = MockProvider(), MockProvider()
    proc_a = EventProcessor(db, platform.cipher, provider_overrides={firm["firm_id"]: cms_a})
    proc_b = EventProcessor(db, platform.cipher, provider_overrides={firm["firm_id"]: cms_b})

    barrier = threading.Barrier(2)
    processed = []

    def run(proc):
        barrier.wait()
        total = 0
        for _ in range(8):  # drain in small competing batches
            total += proc.process_once(limit=3)["processed"]
        processed.append(total)

    threads = [threading.Thread(target=run, args=(p,)) for p in (proc_a, proc_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(processed) == n  # every event processed exactly once, total
    assert len(cms_a.contacts) + len(cms_b.contacts) == n  # zero duplicate CMS writes
    assert len(cms_a.matters) + len(cms_b.matters) == n
    assert len(cms_a.notes) + len(cms_b.notes) == n
    with db.admin() as conn:
        stats = events.queue_stats(conn)
    assert stats["pending"] == 0 and stats["processing"] == 0 and stats["dead"] == 0


def test_visibility_timeout_reclaims_crashed_worker_events(v1_client, firm, db):
    _complete_call(v1_client, firm, "call-crash", "Crash Test", "+15125559999")
    with db.admin() as conn:
        claimed = events.claim_pending(conn)
    assert len(claimed) == 1  # worker claims... then "crashes" (never marks)
    with db.admin() as conn:
        assert events.claim_pending(conn) == []  # claim is committed: nobody else takes it
    with db.admin() as conn:  # time passes beyond the visibility timeout
        conn.execute(
            "UPDATE events SET claimed_at = now() - make_interval(secs => %s)"
            " WHERE status = 'processing'",
            (events.PROCESSING_TIMEOUT_SECONDS + 1,),
        )
    with db.admin() as conn:
        reclaimed = events.claim_pending(conn)
    assert [e.id for e in reclaimed] == [claimed[0].id]


# ---------------------------------------------------------------------------
# Admin ops: queue overview, DLQ replay, alerts
# ---------------------------------------------------------------------------


def test_ops_overview_reports_queue_depth(v1_client, firm):
    _complete_call(v1_client, firm, "call-ops", "Ops Test", "+15125550001")
    r = v1_client.get("/v1/admin/ops/overview", headers=ADMIN)
    assert r.status_code == 200
    q = r.json()["queue"]
    assert q["pending"] == 1 and q["dead"] == 0


def test_dead_event_listing_and_replay_endpoint(v1_client, firm, db, platform):
    cms = MockProvider()
    cms.fail_next = 999
    proc = EventProcessor(db, platform.cipher, provider_overrides={firm["firm_id"]: cms})
    _complete_call(v1_client, firm, "call-dead", "Dead Letter", "+15125550002")
    for _ in range(events.MAX_ATTEMPTS):
        with db.admin() as conn:
            conn.execute("UPDATE events SET next_attempt_at = now() WHERE status = 'pending'")
        proc.process_once()

    dead = v1_client.get("/v1/admin/events/dead", headers=ADMIN).json()
    assert len(dead) == 1 and "injected" in dead[0]["last_error"]

    cms.fail_next = 0
    r = v1_client.post(f"/v1/admin/events/{dead[0]['id']}/replay", headers=ADMIN)
    assert r.json()["status"] == "requeued"
    assert proc.process_once()["processed"] == 1
    # replaying a non-dead event is a 409, not a silent requeue
    assert v1_client.post(
        f"/v1/admin/events/{dead[0]['id']}/replay", headers=ADMIN
    ).status_code == 409


def test_ops_endpoints_require_admin_token(v1_client, firm):
    for path in ("/v1/admin/ops/overview", "/v1/admin/ops/alerts", "/v1/admin/events/dead"):
        assert v1_client.get(path, headers=firm["headers"]).status_code == 401


# ---------------------------------------------------------------------------
# Alert evaluation
# ---------------------------------------------------------------------------


def _post_turns(v1_client, firm, total_ms, n):
    for i in range(n):
        v1_client.post(
            "/v1/metrics/turn",
            json={
                "call_id": "call-slo",
                "speech_id": f"s{i}",
                "eou_delay_ms": 100,
                "llm_ttft_ms": total_ms / 2,
                "tts_ttfb_ms": total_ms / 2 - 100,
                "total_ms": total_ms,
            },
            headers=firm["headers"],
        )


def test_no_alerts_on_healthy_system(v1_client, firm, db):
    _post_turns(v1_client, firm, 450, 8)
    assert alerts.evaluate(db) == []


def test_slo_breach_alert_fires(v1_client, firm, db):
    _post_turns(v1_client, firm, 1200, 8)
    firing = alerts.evaluate(db)
    assert any(a.kind == "slo_breach" and a.severity == "critical" for a in firing)
    r = v1_client.get("/v1/admin/ops/alerts", headers=ADMIN)
    assert r.json()["firing"] >= 1


def test_dlq_alert_fires(v1_client, firm, db, platform):
    cms = MockProvider()
    cms.fail_next = 999
    proc = EventProcessor(db, platform.cipher, provider_overrides={firm["firm_id"]: cms})
    _complete_call(v1_client, firm, "call-dlq-alert", "DLQ Alert", "+15125550003")
    for _ in range(events.MAX_ATTEMPTS):
        with db.admin() as conn:
            conn.execute("UPDATE events SET next_attempt_at = now() WHERE status = 'pending'")
        proc.process_once()
    firing = alerts.evaluate(db)
    assert any(a.kind == "dlq" for a in firing)
