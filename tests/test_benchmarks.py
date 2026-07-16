"""Phase 4 — benchmark analytics: own funnel vs anonymized peer cohort.

The two privacy rules under test: cohort stats are k-anonymity suppressed
below MIN_COHORT peers, and no peer identifier or row-level data ever
appears in a response."""

import json

from api.benchmarks import FirmFunnel, benchmark_report, percentile_rank


# ---------------------------------------------------------------------------
# pure report assembly
# ---------------------------------------------------------------------------


def funnel(firm_id, qual=0.5, book=0.5, speed=30.0, latency=600.0, leads=10):
    return FirmFunnel(
        firm_id=firm_id,
        leads=leads,
        qualification_rate=qual,
        booking_rate=book,
        first_contact_p50_seconds=speed,
        latency_p95_ms=latency,
    )


def test_percentile_rank_directionality():
    cohort = [0.2, 0.4, 0.6, 0.8]
    assert percentile_rank(cohort, 0.7, higher_is_better=True) == 0.75
    # For latency, lower is better: beating 3 of 4 means rank 0.75.
    assert percentile_rank([500, 600, 700, 800], 550, higher_is_better=False) == 0.75


def test_small_cohorts_are_suppressed():
    funnels = [funnel("me"), funnel("peer-1"), funnel("peer-2")]
    report = benchmark_report(funnels, "me", days=30)
    assert report["suppressed"] is True
    assert report["cohort_firms"] == 2
    # Own numbers still show; cohort stats do not.
    assert report["metrics"]["qualification_rate"]["own"] == 0.5
    assert report["metrics"]["qualification_rate"]["cohort"] is None


def test_full_cohort_reports_percentiles_and_rank():
    funnels = [
        funnel("me", qual=0.8, latency=550),
        funnel("p1", qual=0.4, latency=600),
        funnel("p2", qual=0.5, latency=700),
        funnel("p3", qual=0.6, latency=800),
    ]
    report = benchmark_report(funnels, "me", days=30)
    assert report["suppressed"] is False
    qual = report["metrics"]["qualification_rate"]
    assert qual["cohort"] == {"p25": 0.45, "p50": 0.5, "p75": 0.55, "firms": 3}
    assert qual["percentile_rank"] == 1.0  # best in cohort
    latency = report["metrics"]["latency_p95_ms"]
    assert latency["percentile_rank"] == 1.0  # lowest latency wins too


def test_report_carries_no_peer_identifiers():
    funnels = [funnel("me")] + [funnel(f"peer-uuid-{i}") for i in range(5)]
    blob = json.dumps(benchmark_report(funnels, "me", days=30))
    assert "peer-uuid" not in blob
    assert "firm_id" not in blob


# ---------------------------------------------------------------------------
# end to end through the API
# ---------------------------------------------------------------------------


def _seed_firm_activity(db, firm_id, qualified, total, latency_ms):
    with db.firm(firm_id) as conn:
        for i in range(total):
            status = "qualified" if i < qualified else "new"
            conn.execute(
                "INSERT INTO leads (firm_id, source, status) VALUES (%s, 'phone', %s)",
                (firm_id, status),
            )
        conn.execute(
            "INSERT INTO calls (id, firm_id) VALUES (%s, %s)",
            (f"bench-{firm_id}", firm_id),
        )
        conn.execute(
            "INSERT INTO turn_metrics (firm_id, call_id, speech_id, eou_delay_ms,"
            " llm_ttft_ms, tts_ttfb_ms, total_ms)"
            " VALUES (%s, %s, 's1', 100, 200, 100, %s)",
            (firm_id, f"bench-{firm_id}", latency_ms),
        )


def _peer_firm(db, name):
    with db.admin() as conn:
        return str(
            conn.execute("INSERT INTO firms (name) VALUES (%s) RETURNING id", (name,)).fetchone()[
                "id"
            ]
        )


def test_benchmarks_endpoint_suppresses_then_reports(v1_client, firm, db):
    _seed_firm_activity(db, firm["firm_id"], qualified=8, total=10, latency_ms=550)
    for i in range(2):
        _seed_firm_activity(db, _peer_firm(db, f"Peer {i}"), qualified=5, total=10, latency_ms=700)

    r = v1_client.get("/v1/analytics/benchmarks", headers=firm["headers"]).json()
    assert r["suppressed"] is True and r["cohort_firms"] == 2

    # A third peer crosses the k-anonymity gate.
    _seed_firm_activity(db, _peer_firm(db, "Peer 2"), qualified=3, total=10, latency_ms=760)
    r = v1_client.get("/v1/analytics/benchmarks", headers=firm["headers"]).json()
    assert r["suppressed"] is False
    qual = r["metrics"]["qualification_rate"]
    assert qual["own"] == 0.8
    assert qual["cohort"]["firms"] == 3
    assert qual["percentile_rank"] == 1.0
    assert r["metrics"]["latency_p95_ms"]["percentile_rank"] == 1.0

    # No peer names or ids anywhere in the payload.
    blob = json.dumps(r)
    assert "Peer" not in blob
    for peer_marker in ("firm_id", "firms\": ["):
        assert peer_marker not in blob


def test_firm_with_no_activity_sees_suppressed_but_valid_shape(v1_client, second_firm):
    r = v1_client.get("/v1/analytics/benchmarks", headers=second_firm["headers"]).json()
    assert r["own_leads"] == 0
    assert set(r["metrics"]) == {
        "qualification_rate",
        "booking_rate",
        "first_contact_p50_seconds",
        "latency_p95_ms",
    }
