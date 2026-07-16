"""SQLite persistence for the Phase 0 prototype.

Deliberately thin: stdlib sqlite3, one connection per operation, no ORM.
Phase 1 replaces this wholesale with Postgres + SQLAlchemy, so nothing here
is worth abstracting further.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS consults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    slot_iso TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cms_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    structured TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turn_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT NOT NULL,
    speech_id TEXT NOT NULL,
    eou_delay_ms REAL NOT NULL,
    llm_ttft_ms REAL NOT NULL,
    tts_ttfb_ms REAL NOT NULL,
    total_ms REAL NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- consults ---

    def save_consult(self, name: str, phone: str, slot_iso: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO consults (name, phone, slot_iso, created_at) VALUES (?, ?, ?, ?)",
                (name, phone, slot_iso, _now()),
            )
            return cur.lastrowid

    def list_consults(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM consults ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # --- mock CMS ---

    def save_cms_record(self, call_id: str, summary: str, structured: dict) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO cms_records (call_id, summary, structured, created_at)"
                " VALUES (?, ?, ?, ?)",
                (call_id, summary, json.dumps(structured), _now()),
            )
            return cur.lastrowid

    def list_cms_records(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM cms_records ORDER BY id").fetchall()
        records = []
        for r in rows:
            rec = dict(r)
            rec["structured"] = json.loads(rec["structured"])
            records.append(rec)
        return records

    # --- latency metrics ---

    def save_turn_metrics(
        self,
        call_id: str,
        speech_id: str,
        eou_delay_ms: float,
        llm_ttft_ms: float,
        tts_ttfb_ms: float,
        total_ms: float,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO turn_metrics"
                " (call_id, speech_id, eou_delay_ms, llm_ttft_ms, tts_ttfb_ms, total_ms, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (call_id, speech_id, eou_delay_ms, llm_ttft_ms, tts_ttfb_ms, total_ms, _now()),
            )
            return cur.lastrowid

    def call_latency_summary(self, call_id: str) -> dict:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT total_ms FROM turn_metrics WHERE call_id = ?", (call_id,)
            ).fetchall()
        totals = sorted(r["total_ms"] for r in rows)
        if not totals:
            return {
                "call_id": call_id,
                "turns": 0,
                "p50_ms": None,
                "p95_ms": None,
                "max_ms": None,
                "within_budget": None,
            }
        if len(totals) == 1:
            p50, p95 = totals[0], totals[0]
        else:
            quantiles = statistics.quantiles(totals, n=100, method="inclusive")
            p50, p95 = quantiles[49], quantiles[94]
        return {
            "call_id": call_id,
            "turns": len(totals),
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "max_ms": round(totals[-1], 1),
            "within_budget": p95 <= 800.0,
        }
