"""Intake-funnel benchmarks (Phase 4): the analytics product.

A firm sees its own funnel against an anonymized peer cohort: qualification
rate, booking rate, speed-to-lead, and turn latency, with the firm's
percentile rank in each. Two privacy rules, enforced here and asserted in
tests:

  * **Aggregates only.** Per-firm metrics are computed with the platform
    role (this is deliberately cross-tenant — it is the product), but the
    response never contains another firm's id, name, or any row-level data.
  * **k-anonymity.** Benchmarks are suppressed unless at least
    ``MIN_COHORT`` *other* firms had activity in the window — with two
    peers, "the cohort median" is just your competitor's number.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.platform.db import Database

# Peers (excluding the requesting firm) required before cohort stats exist.
MIN_COHORT = 3

# metric key -> (label, higher_is_better)
METRICS: dict[str, tuple[str, bool]] = {
    "qualification_rate": ("Qualification rate", True),
    "booking_rate": ("Booking rate (of qualified)", True),
    "first_contact_p50_seconds": ("Speed to lead p50 (s)", False),
    "latency_p95_ms": ("Turn latency p95 (ms)", False),
}


@dataclass(frozen=True)
class FirmFunnel:
    firm_id: str
    leads: int
    qualification_rate: float | None
    booking_rate: float | None
    first_contact_p50_seconds: float | None
    latency_p95_ms: float | None

    def metric(self, key: str) -> float | None:
        return getattr(self, key)


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile (same convention as Postgres
    percentile_cont) over an already-sorted list."""
    if not sorted_values:
        raise ValueError("no values")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def percentile_rank(cohort: list[float], own: float, higher_is_better: bool) -> float:
    """Share of the cohort the firm beats or ties (0..1, 1 = best in cohort)."""
    if not cohort:
        raise ValueError("no cohort")
    if higher_is_better:
        beaten = sum(1 for v in cohort if own >= v)
    else:
        beaten = sum(1 for v in cohort if own <= v)
    return round(beaten / len(cohort), 3)


def collect_funnels(db: Database, days: int) -> list[FirmFunnel]:
    """Per-firm funnel aggregates over the window. Platform-role query by
    design; only firms with lead activity participate."""
    with db.admin() as conn:
        rows = conn.execute(
            """
            SELECT f.id AS firm_id,
                   count(l.id) AS leads,
                   count(l.id) FILTER (WHERE l.status = 'qualified')::float
                       / nullif(count(l.id), 0) AS qualification_rate,
                   (SELECT count(*) FROM consults co
                     WHERE co.firm_id = f.id
                       AND co.created_at > now() - make_interval(days => %(days)s))::float
                       / nullif(count(l.id) FILTER (WHERE l.status = 'qualified'), 0)
                       AS booking_rate,
                   (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY
                            extract(epoch FROM l2.first_contact_at - l2.created_at))
                      FROM leads l2
                     WHERE l2.firm_id = f.id AND l2.first_contact_at IS NOT NULL
                       AND l2.created_at > now() - make_interval(days => %(days)s))
                       AS first_contact_p50_seconds,
                   (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY tm.total_ms)
                      FROM turn_metrics tm
                     WHERE tm.firm_id = f.id
                       AND tm.created_at > now() - make_interval(days => %(days)s))
                       AS latency_p95_ms
              FROM firms f
              LEFT JOIN leads l ON l.firm_id = f.id
                   AND l.created_at > now() - make_interval(days => %(days)s)
             GROUP BY f.id
            HAVING count(l.id) > 0
            """,
            {"days": days},
        ).fetchall()
    return [
        FirmFunnel(
            firm_id=str(r["firm_id"]),
            leads=r["leads"],
            qualification_rate=r["qualification_rate"],
            booking_rate=r["booking_rate"],
            first_contact_p50_seconds=r["first_contact_p50_seconds"],
            latency_p95_ms=r["latency_p95_ms"],
        )
        for r in rows
    ]


def benchmark_report(funnels: list[FirmFunnel], own_firm_id: str, days: int) -> dict:
    """Assemble the firm-facing report: own metrics always; cohort stats only
    past the k-anonymity gate. No peer identifiers, ever."""
    own = next((f for f in funnels if f.firm_id == own_firm_id), None)
    peers = [f for f in funnels if f.firm_id != own_firm_id]
    suppressed = len(peers) < MIN_COHORT

    metrics: dict[str, dict] = {}
    for key, (label, higher_is_better) in METRICS.items():
        own_value = own.metric(key) if own else None
        entry: dict = {
            "label": label,
            "own": round(own_value, 3) if own_value is not None else None,
            "higher_is_better": higher_is_better,
            "cohort": None,
            "percentile_rank": None,
        }
        if not suppressed:
            values = sorted(v for f in peers if (v := f.metric(key)) is not None)
            if len(values) >= MIN_COHORT:
                entry["cohort"] = {
                    "p25": round(_percentile(values, 0.25), 3),
                    "p50": round(_percentile(values, 0.50), 3),
                    "p75": round(_percentile(values, 0.75), 3),
                    "firms": len(values),
                }
                if own_value is not None:
                    entry["percentile_rank"] = percentile_rank(
                        values, own_value, higher_is_better
                    )
        metrics[key] = entry

    return {
        "days": days,
        "own_leads": own.leads if own else 0,
        "cohort_firms": len(peers),
        "suppressed": suppressed,
        "suppressed_reason": (
            f"benchmarks need at least {MIN_COHORT} peer firms with activity"
            if suppressed
            else None
        ),
        "metrics": metrics,
    }
