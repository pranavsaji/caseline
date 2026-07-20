#!/usr/bin/env python3
"""Seed realistic demo data for the dashboard's Threads, Referrals, and Tuning
sections (which are empty on a fresh firm), plus a few booked consults so the
calendar looks lived-in.

Idempotent: every seeded row carries a stable marker, and each section is
skipped if its marker rows already exist. Pass --reset to delete previously
seeded rows first and re-seed.

Usage:
  python scripts/seed_demo_data.py [--reset]

Reads CASELINE_DATABASE_URL from the env (preferred) or .env. Against prod use
the Postgres public proxy URL, since the internal host won't resolve off-Railway.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg
from dotenv import dotenv_values
from psycopg.rows import dict_row

# A stable tag on every seeded row so the seed is idempotent and reversible.
MARKER = "seed:demo-v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _future_weekday(days_ahead: int, hour: int) -> datetime:
    """A timestamp `days_ahead` from now, nudged to the next weekday, at `hour`."""
    d = _now() + timedelta(days=days_ahead)
    while d.weekday() >= 5:  # Sat/Sun -> Monday
        d += timedelta(days=1)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0)


def _ago(days: float) -> datetime:
    return _now() - timedelta(days=days)


# --- reference data -------------------------------------------------------

REFERRAL_PARTNERS = [
    {
        "name": "Lone Star Workers' Comp Group",
        "practice_areas": ["workers_comp"],
        "states": ["TX"],
        "contact_email": "intake@lonestarwc.example",
        "contact_phone": "+15125550310",
        "notes": "Fast turnaround on comp claims; takes TX referrals same day.",
    },
    {
        "name": "Gulf Coast Medical Malpractice",
        "practice_areas": ["medical_malpractice"],
        "states": ["TX", "LA"],
        "contact_email": "referrals@gulfcoastmedmal.example",
        "contact_phone": "+15125550311",
        "notes": "Med-mal specialists; require records before accepting.",
    },
    {
        "name": "Hill Country Family Law",
        "practice_areas": ["family"],
        "states": ["TX"],
        "contact_email": "hello@hillcountryfamily.example",
        "contact_phone": "+15125550312",
        "notes": "Divorce, custody, mediation.",
    },
    {
        "name": "Cascade Employment Advocates",
        "practice_areas": ["employment"],
        "states": ["TX", "CA"],
        "contact_email": "cases@cascadeemployment.example",
        "contact_phone": "+15125550313",
        "notes": "Wrongful termination and wage disputes.",
    },
]

# Tuning needs leads with a stored qualification + an attorney verdict. The mix
# below is deliberately imperfect so the tuning report produces a real
# suggestion rather than a flat 100%: the engine 'qualified' six soft-tissue
# leads but attorneys rejected five of them (>=5 samples, >=80% rejected — the
# thresholds _injury_suggestions needs) → "add soft tissue to refer_out". The
# rest are genuine wins that keep the agreement matrix realistic.
TUNING_LEADS = [
    # (injury, decision, incident_days_ago, in_treatment, has_insurance, verdict, reason)
    # Soft-tissue cluster: engine qualifies, attorneys mostly reject -> suggestion.
    ("soft tissue", "qualified", 40, False, True, "rejected", "Soft tissue, not treating — low value."),
    ("soft tissue", "qualified", 55, False, False, "rejected", "No treatment, no insurance."),
    ("soft tissue", "qualified", 30, False, True, "rejected", "Minor soft-tissue, declined to sign."),
    ("soft tissue", "qualified", 65, False, True, "rejected", "Stale, soft-tissue only."),
    ("soft tissue", "qualified", 22, False, True, "rejected", "Low severity."),
    ("soft tissue", "qualified", 18, True, True, "accepted", "Borderline but treating — took it."),
    # Genuine wins the engine and attorneys agree on.
    ("whiplash", "qualified", 20, True, True, "accepted", "Clear liability, treating."),
    ("whiplash", "qualified", 14, True, True, "accepted", "Good case."),
    ("broken arm", "qualified", 12, True, True, "accepted", "Strong case."),
    ("back injury", "qualified", 30, True, True, "accepted", "Ongoing treatment."),
    ("concussion", "qualified", 8, True, True, "accepted", "ER records available."),
    ("spinal injury", "qualified", 25, True, True, "accepted", "High value, retained."),
    ("fracture", "qualified", 18, True, True, "accepted", "Good documentation."),
]

# Threads: mid-flight SMS/email conversations across intake + treatment tracker.
THREADS = [
    {
        "channel": "sms",
        "address": "+15125550401",
        "goal": "intake",
        "status": "open",
        "contact": ("Marcus Bell", "+15125550401", None),
        "messages": [
            ("out", "Hi Marcus, this is Caseline for Saji & Partners — you asked about a car accident claim. Is now an okay time for a few quick questions?", 1.2),
            ("in", "yeah that works", 1.1),
            ("out", "Great. When did the accident happen, and are you currently getting treatment?", 1.0),
            ("in", "last tuesday, seeing a chiropractor now", 0.4),
        ],
    },
    {
        "channel": "sms",
        "address": "+15125550402",
        "goal": "intake",
        "status": "closed",
        "closed_reason": "booked",
        "contact": ("Dana Whitfield", "+15125550402", None),
        "messages": [
            ("out", "Hi Dana — following up on your website inquiry about a slip and fall. A few quick questions to see if we can help?", 3.0),
            ("in", "sure", 2.9),
            ("out", "Thanks. Are you currently treating, and do you have the incident date?", 2.9),
            ("in", "yes, physical therapy. it was june 30", 2.8),
            ("out", "Perfect — you're a good fit. I booked you with an attorney. You'll get a confirmation shortly.", 2.7),
        ],
    },
    {
        "channel": "email",
        "address": "priya.n@example.com",
        "goal": "intake",
        "status": "open",
        "contact": ("Priya Nair", None, "priya.n@example.com"),
        "messages": [
            ("out", "Hello Priya, thanks for reaching out to Saji & Partners about your workplace injury. Could you tell us when it happened and whether a report was filed?", 2.0),
            ("in", "It was about 3 weeks ago. Yes, I filed a report with HR the same day.", 1.5),
            ("out", "Thank you — that's helpful. Are you receiving medical treatment currently?", 1.4),
        ],
    },
    {
        "channel": "sms",
        "address": "+15125550403",
        "goal": "treatment_tracker",
        "status": "open",
        "contact": ("Luis Ortega", "+15125550403", None),
        "messages": [
            ("out", "Hi Luis, checking in from Saji & Partners. How is your treatment going this week?", 7.0),
            ("in", "better, went to PT twice", 6.8),
            ("out", "Glad to hear it. Any new appointments scheduled we should note for your file?", 6.8),
            ("in", "yeah ortho on the 28th", 6.7),
            ("out", "Noted, thank you. We'll check back next week.", 6.6),
        ],
    },
    {
        "channel": "email",
        "address": "t.franklin@example.com",
        "goal": "treatment_tracker",
        "status": "open",
        "contact": ("Tara Franklin", None, "t.franklin@example.com"),
        "messages": [
            ("out", "Hi Tara, your monthly treatment check-in from Saji & Partners. How are you feeling, and are you still seeing your providers?", 5.0),
            ("in", "Still in PT, and I have an MRI scheduled next month.", 4.6),
        ],
    },
]


def _conn(db_url: str) -> psycopg.Connection:
    c = psycopg.connect(db_url, row_factory=dict_row)
    return c


def _set_firm(cur, firm_id: str) -> None:
    # Satisfy row-level security for every insert on tenant tables.
    cur.execute("SELECT set_config('app.firm_id', %s, false)", (str(firm_id),))


def _seed(cur, firm_id: str, agent_id: str) -> dict:
    counts = {"referral_partners": 0, "referrals": 0, "threads": 0, "messages": 0,
              "tuning_leads": 0, "lead_reviews": 0, "consults": 0}

    def add_contact(name, phone, email) -> str:
        cur.execute(
            "INSERT INTO contacts (firm_id, name, phone, email, external_cms_id)"
            " VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (firm_id, name, phone, email, MARKER),
        )
        return cur.fetchone()["id"]

    def add_lead(contact_id, source, practice_area, qualification, status="new") -> str:
        cur.execute(
            "INSERT INTO leads (firm_id, source, contact_id, status, qualification,"
            " practice_area, external_cms_id) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (firm_id, source, contact_id, status,
             json.dumps(qualification) if qualification else None, practice_area, MARKER),
        )
        return cur.fetchone()["id"]

    # --- referral partners + referrals -----------------------------------
    partner_ids = {}
    for p in REFERRAL_PARTNERS:
        cur.execute(
            "INSERT INTO referral_partners (firm_id, name, practice_areas, states,"
            " contact_email, contact_phone, active, notes)"
            " VALUES (%s,%s,%s,%s,%s,%s,true,%s) RETURNING id",
            (firm_id, p["name"], p["practice_areas"], p["states"],
             p["contact_email"], p["contact_phone"], f'{p["notes"]} [{MARKER}]'),
        )
        partner_ids[p["name"]] = cur.fetchone()["id"]
        counts["referral_partners"] += 1

    referrals = [
        # (contact, practice_area, partner, status, reasons, consent, sent_days_ago)
        (("Owen Reyes", "+15125550420", None), "workers_comp",
         "Lone Star Workers' Comp Group", "sent",
         ["out of our practice area (workers' comp)", "partner covers TX"], True, 2),
        (("Sandra Mills", None, "sandra.mills@example.com"), "medical_malpractice",
         "Gulf Coast Medical Malpractice", "accepted",
         ["med-mal specialty required", "partner covers TX"], True, 6),
        (("Greg Tan", "+15125550421", None), "family",
         "Hill Country Family Law", "proposed",
         ["family law, outside personal injury"], False, None),
    ]
    for contact, area, partner_name, status, reasons, consent, sent_days in referrals:
        cid = add_contact(*contact)
        lid = add_lead(cid, "phone", area,
                       {"decision": "refer_out", "injury_type": None, "practice_area": area})
        sent_at = _ago(sent_days) if sent_days is not None else None
        packet = {"contact_name": contact[0], "practice_area": area,
                  "summary": f"Referred out: {area.replace('_', ' ')} matter."}
        cur.execute(
            "INSERT INTO referrals (firm_id, lead_id, partner_id, status, match_reasons,"
            " packet, client_consent, sent_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (firm_id, lid, partner_ids[partner_name], status, json.dumps(reasons),
             json.dumps(packet), consent, sent_at),
        )
        counts["referrals"] += 1

    # --- tuning: leads with qualification + attorney verdicts ------------
    for injury, decision, inc_days, treating, insured, verdict, reason in TUNING_LEADS:
        cid = add_contact(f"{injury.title()} Claimant", None, None)
        incident_date = (_now().date() - timedelta(days=inc_days)).isoformat()
        qualification = {
            "decision": decision,
            "injury_type": injury,
            "incident_date": incident_date,
            "in_treatment": treating,
            "has_insurance": insured,
            "reasons": [reason],
        }
        lid = add_lead(cid, "phone", "personal injury", qualification,
                       status="qualified" if decision == "qualified" else "new")
        cur.execute(
            "INSERT INTO lead_reviews (firm_id, lead_id, verdict, reviewer, reason,"
            " created_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (firm_id, lid, verdict, "Attorney (demo)", reason, _ago(inc_days / 3)),
        )
        counts["tuning_leads"] += 1
        counts["lead_reviews"] += 1

    # --- threads + messages ----------------------------------------------
    for t in THREADS:
        cid = add_contact(*t["contact"])
        last_in = last_out = None
        # created_at anchored to the oldest message.
        oldest = max(m[2] for m in t["messages"])
        cur.execute(
            "INSERT INTO threads (firm_id, channel, address, contact_id, goal, status,"
            " closed_reason, state, created_at, updated_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (firm_id, t["channel"], t["address"], cid, t["goal"], t["status"],
             t.get("closed_reason"), json.dumps({"seed": MARKER}),
             _ago(oldest), _ago(min(m[2] for m in t["messages"]))),
        )
        tid = cur.fetchone()["id"]
        for direction, body, days_ago in t["messages"]:
            ts = _ago(days_ago)
            cur.execute(
                "INSERT INTO messages (firm_id, channel, thread_id, direction, body, ts)"
                " VALUES (%s,%s,%s,%s,%s,%s)",
                (firm_id, t["channel"], str(tid), direction, body, ts),
            )
            counts["messages"] += 1
            if direction == "in":
                last_in = ts
            else:
                last_out = ts
        cur.execute(
            "UPDATE threads SET last_inbound_at=%s, last_outbound_at=%s WHERE id=%s",
            (last_in, last_out, tid),
        )
        counts["threads"] += 1

    # --- a few booked consults across the month (calendar looks used) ----
    for i, (name, phone, days_ahead, hour) in enumerate([
        ("Marcus Bell", "+15125550401", 2, 10),
        ("Dana Whitfield", "+15125550402", 5, 14),
        ("Priya Nair", "+15125550430", 9, 11),
        ("Owen Reyes", "+15125550420", 16, 15),
    ]):
        slot = _future_weekday(days_ahead, hour)
        cur.execute(
            "INSERT INTO consults (firm_id, name, phone, slot_at, idempotency_key)"
            " VALUES (%s,%s,%s,%s,%s) ON CONFLICT (firm_id, idempotency_key) DO NOTHING",
            (firm_id, name, phone, slot, f"{MARKER}:consult:{i}"),
        )
        counts["consults"] += cur.rowcount

    return counts


def _already_seeded(cur, firm_id: str) -> bool:
    _set_firm(cur, firm_id)
    cur.execute(
        "SELECT count(*) AS n FROM referral_partners WHERE notes LIKE %s", (f"%{MARKER}%",)
    )
    return cur.fetchone()["n"] > 0


def _reset(cur, firm_id: str) -> None:
    _set_firm(cur, firm_id)
    # Delete children before parents. Seeded leads/contacts carry MARKER in
    # external_cms_id; referrals/reviews/consults/threads reference them.
    cur.execute("DELETE FROM referrals WHERE lead_id IN"
                " (SELECT id FROM leads WHERE external_cms_id=%s)", (MARKER,))
    cur.execute("DELETE FROM referral_partners WHERE notes LIKE %s", (f"%{MARKER}%",))
    cur.execute("DELETE FROM lead_reviews WHERE lead_id IN"
                " (SELECT id FROM leads WHERE external_cms_id=%s)", (MARKER,))
    cur.execute("DELETE FROM messages WHERE thread_id IN"
                " (SELECT id::text FROM threads WHERE state->>'seed'=%s)", (MARKER,))
    cur.execute("DELETE FROM threads WHERE state->>'seed'=%s", (MARKER,))
    cur.execute("DELETE FROM consults WHERE idempotency_key LIKE %s", (f"{MARKER}:%",))
    cur.execute("DELETE FROM leads WHERE external_cms_id=%s", (MARKER,))
    cur.execute("DELETE FROM contacts WHERE external_cms_id=%s", (MARKER,))


def main() -> int:
    reset = "--reset" in sys.argv[1:]
    db_url = os.environ.get("CASELINE_DATABASE_URL") or dotenv_values(".env").get(
        "CASELINE_DATABASE_URL"
    )
    if not db_url:
        print("CASELINE_DATABASE_URL not set (env or .env)", file=sys.stderr)
        return 1

    with _conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM firms ORDER BY created_at LIMIT 1")
            firm = cur.fetchone()
            if not firm:
                print("No firm found — run onboarding first.", file=sys.stderr)
                return 1
            firm_id = firm["id"]
            cur.execute("SELECT id FROM agents WHERE firm_id=%s ORDER BY created_at LIMIT 1",
                        (firm_id,))
            agent = cur.fetchone()
            agent_id = agent["id"] if agent else None

            if reset:
                _reset(cur, firm_id)
                conn.commit()
                print("Reset: removed previously seeded rows.")

            if _already_seeded(cur, firm_id):
                print("Already seeded (marker present). Pass --reset to re-seed.")
                return 0

            _set_firm(cur, firm_id)
            counts = _seed(cur, firm_id, agent_id)
            conn.commit()

    print(f"Seeded demo data for firm {firm['name']!r}:")
    for k, v in counts.items():
        print(f"  {k:18} +{v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
