"""Append-only event log + outbox consumer primitives.

Every meaningful moment (``call.completed``, ``lead.qualified``,
``consult.booked``, ...) is a row in ``events``, written in the same
transaction as the state change that caused it. Consumers (CMS sync,
analytics) poll the table as an outbox — nothing on the hot path ever makes
a synchronous external call.

``EventBus`` is the seam for GCP: locally the outbox poll *is* the bus; in
production a Pub/Sub publisher fans events out as well. Swapping is config,
not a rewrite (guiding principle #3).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import psycopg

logger = logging.getLogger("caseline.platform.events")

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30


@dataclass(frozen=True)
class Event:
    id: int
    firm_id: str
    type: str
    payload: dict
    attempts: int
    created_at: datetime


def emit(conn: psycopg.Connection, firm_id: str, type_: str, payload: dict) -> int:
    """Append an event inside the caller's transaction. Returns the event id."""
    row = conn.execute(
        "INSERT INTO events (firm_id, type, payload) VALUES (%s, %s, %s) RETURNING id",
        (str(firm_id), type_, json.dumps(payload)),
    ).fetchone()
    logger.info("event emitted type=%s firm=%s id=%s", type_, firm_id, row["id"])
    return row["id"]


class EventBus(Protocol):
    """Publish seam for out-of-process fan-out (Pub/Sub in production)."""

    def publish(self, event: Event) -> None: ...


class LogOnlyBus:
    """Local default: the durable consumer is the outbox poller; publishing
    beyond the log is a no-op."""

    def publish(self, event: Event) -> None:
        logger.debug("bus publish (log-only): %s %s", event.type, event.id)


class PubSubBus:
    """GCP Pub/Sub adapter. Deliberately import-lazy: only constructed when
    CASELINE_PUBSUB_TOPIC is configured on a GCP deployment."""

    def __init__(self, topic: str):
        from google.cloud import pubsub_v1  # type: ignore[import-not-found]

        self._publisher = pubsub_v1.PublisherClient()
        self._topic = topic

    def publish(self, event: Event) -> None:
        self._publisher.publish(
            self._topic,
            json.dumps(event.payload).encode(),
            event_type=event.type,
            firm_id=event.firm_id,
        )


# ---------------------------------------------------------------------------
# Outbox consumer primitives (used by workers/cms_sync.py via the admin role)
# ---------------------------------------------------------------------------


def claim_pending(conn: psycopg.Connection, limit: int = 20) -> list[Event]:
    """Claim due pending events. FOR UPDATE SKIP LOCKED makes concurrent
    workers safe: two pollers never process the same event."""
    rows = conn.execute(
        "SELECT id, firm_id, type, payload, attempts, created_at FROM events"
        " WHERE status = 'pending' AND next_attempt_at <= now()"
        " ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED",
        (limit,),
    ).fetchall()
    return [
        Event(
            id=r["id"],
            firm_id=str(r["firm_id"]),
            type=r["type"],
            payload=r["payload"],
            attempts=r["attempts"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def mark_processed(conn: psycopg.Connection, event_id: int) -> None:
    conn.execute(
        "UPDATE events SET status = 'processed', processed_at = now() WHERE id = %s",
        (event_id,),
    )


def mark_failed(conn: psycopg.Connection, event_id: int, attempts: int, error: str) -> str:
    """Record a failure: exponential backoff while attempts remain, dead-letter
    after MAX_ATTEMPTS. Returns the resulting status."""
    attempts += 1
    if attempts >= MAX_ATTEMPTS:
        conn.execute(
            "UPDATE events SET status = 'dead', attempts = %s, last_error = %s WHERE id = %s",
            (attempts, error[:2000], event_id),
        )
        logger.error("event %s dead-lettered after %s attempts: %s", event_id, attempts, error)
        return "dead"
    delay = BACKOFF_BASE_SECONDS * (2 ** (attempts - 1))
    conn.execute(
        "UPDATE events SET attempts = %s, last_error = %s,"
        " next_attempt_at = now() + make_interval(secs => %s) WHERE id = %s",
        (attempts, error[:2000], delay, event_id),
    )
    return "pending"


def replay_dead(conn: psycopg.Connection, event_id: int) -> None:
    """Requeue a dead-lettered event after the poison payload is fixed."""
    conn.execute(
        "UPDATE events SET status = 'pending', attempts = 0, next_attempt_at = now()"
        " WHERE id = %s AND status = 'dead'",
        (event_id,),
    )


def make_bus(pubsub_topic: str | None = None) -> EventBus:
    return PubSubBus(pubsub_topic) if pubsub_topic else LogOnlyBus()
