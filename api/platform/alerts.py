"""Alert evaluation (Phase 2 Workstream D).

A slow provider silently ruins calls before anyone complains — so alerting
is pull-evaluated from the same tables the dashboards read, with a webhook
seam for push delivery. Rules, in order of how fast they hurt:

  * latency SLO regression — global/firm p95 over the last hour breaches the
    800 ms hard ceiling, or degrades >30% against the trailing 7-day p95;
  * provider error spike — event handler failures recorded in the last hour;
  * DLQ growth — dead-lettered events needing human replay;
  * consumer backlog — the outbox is aging (worker down or drowning).

Evaluation runs on the admin role (cross-firm visibility is the point);
results are exposed on /v1/admin/ops/alerts and pushed by the sync worker.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass

from api.platform import events
from api.platform.db import Database

logger = logging.getLogger("caseline.platform.alerts")

LATENCY_SLO_MS = 800.0
REGRESSION_RATIO = 1.3
BACKLOG_AGE_SECONDS = 300.0
BACKLOG_DEPTH = 500
ERROR_SPIKE_THRESHOLD = 10


@dataclass(frozen=True)
class Alert:
    kind: str  # slo_breach | slo_regression | error_spike | dlq | backlog
    severity: str  # critical | warning
    message: str
    value: float | None = None


def _latency_alerts(db: Database) -> list[Alert]:
    with db.admin() as conn:
        row = conn.execute(
            "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms) AS p95_hour,"
            "       count(*) AS turns_hour"
            " FROM turn_metrics WHERE created_at > now() - interval '1 hour'"
        ).fetchone()
        baseline = conn.execute(
            "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms) AS p95_week"
            " FROM turn_metrics"
            " WHERE created_at BETWEEN now() - interval '7 days' AND now() - interval '1 hour'"
        ).fetchone()
    alerts: list[Alert] = []
    p95_hour, turns = row["p95_hour"], row["turns_hour"]
    if p95_hour is None or turns < 5:  # too little signal to alert on
        return alerts
    if p95_hour > LATENCY_SLO_MS:
        alerts.append(
            Alert(
                kind="slo_breach",
                severity="critical",
                message=f"p95 turn latency {p95_hour:.0f} ms over the last hour breaches the "
                f"{LATENCY_SLO_MS:.0f} ms SLO ({turns} turns)",
                value=round(p95_hour, 1),
            )
        )
    p95_week = baseline["p95_week"]
    if p95_week and p95_hour > p95_week * REGRESSION_RATIO:
        alerts.append(
            Alert(
                kind="slo_regression",
                severity="warning",
                message=f"p95 turn latency {p95_hour:.0f} ms is {p95_hour / p95_week:.1f}x the "
                f"trailing 7-day p95 ({p95_week:.0f} ms) — a provider is probably degrading",
                value=round(p95_hour, 1),
            )
        )
    return alerts


def _consumer_alerts(db: Database) -> list[Alert]:
    with db.admin() as conn:
        stats = events.queue_stats(conn)
        errors_hour = conn.execute(
            "SELECT count(*) AS n FROM events"
            " WHERE last_error IS NOT NULL"
            "   AND (processed_at > now() - interval '1 hour'"
            "        OR next_attempt_at > now() - interval '1 hour'"
            "        OR (status = 'dead' AND created_at > now() - interval '1 hour'))"
        ).fetchone()["n"]
    alerts: list[Alert] = []
    if stats["dead"]:
        alerts.append(
            Alert(
                kind="dlq",
                severity="critical",
                message=f"{stats['dead']} dead-lettered event(s) awaiting replay",
                value=float(stats["dead"]),
            )
        )
    age = stats["oldest_pending_age_seconds"]
    if (age and age > BACKLOG_AGE_SECONDS) or stats["pending"] > BACKLOG_DEPTH:
        alerts.append(
            Alert(
                kind="backlog",
                severity="warning",
                message=f"event backlog: {stats['pending']} pending, oldest "
                f"{(age or 0):.0f}s — is the sync worker up?",
                value=float(stats["pending"]),
            )
        )
    if errors_hour >= ERROR_SPIKE_THRESHOLD:
        alerts.append(
            Alert(
                kind="error_spike",
                severity="warning",
                message=f"{errors_hour} event-handler failures in the last hour — check "
                "provider status before the DLQ fills",
                value=float(errors_hour),
            )
        )
    return alerts


def evaluate(db: Database) -> list[Alert]:
    """All firing alerts, most severe first."""
    alerts = _latency_alerts(db) + _consumer_alerts(db)
    return sorted(alerts, key=lambda a: (a.severity != "critical", a.kind))


def notify(alerts: list[Alert], webhook_url: str | None = None) -> bool:
    """Push firing alerts to the configured webhook (Slack-compatible JSON).
    Returns True if a delivery was attempted and succeeded. Never raises —
    alerting must not take down the worker that runs it."""
    webhook_url = webhook_url or os.getenv("CASELINE_ALERT_WEBHOOK_URL")
    if not alerts or not webhook_url:
        return False
    try:
        import httpx

        payload = {
            "text": "\n".join(f"[{a.severity}] {a.kind}: {a.message}" for a in alerts),
            "alerts": [asdict(a) for a in alerts],
        }
        r = httpx.post(webhook_url, json=payload, timeout=5.0)
        r.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("alert webhook delivery failed: %s", exc)
        return False


def log_alerts(alerts: list[Alert]) -> None:
    for a in alerts:
        logger.log(
            logging.ERROR if a.severity == "critical" else logging.WARNING,
            "ALERT %s: %s", a.kind, a.message,
        )


__all__ = ["Alert", "evaluate", "notify", "log_alerts", "LATENCY_SLO_MS"]


def to_dicts(alerts: list[Alert]) -> list[dict]:
    return [asdict(a) for a in alerts]
