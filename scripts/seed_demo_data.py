#!/usr/bin/env python3
"""Seed realistic demo data for the dashboard's Threads, Referrals, and Tuning
sections (which are empty on a fresh firm), plus a few booked consults so the
calendar looks lived-in.

Idempotent: every seeded row carries a stable marker, and each section is
skipped if its marker rows already exist. Pass --reset to delete previously
seeded rows first and re-seed.

Usage:
  python scripts/seed_demo_data.py [--reset] [--firm <name-or-id>]

--firm picks the tenant to seed (name or uuid); without it the oldest firm is
used, which is what a single-firm deploy wants.

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

# Calls + per-turn latency for the Analytics page. Without these, a freshly
# onboarded firm shows "No calls yet", "No turn metrics yet", and dashes for
# answer speed and booked rate, because every one of those panels reads `calls`
# or `turn_metrics` — tables the rest of this seed never touches. Qualification
# and booking rate still render (they read leads/consults), which makes the page
# look half-broken rather than empty.
#
# Outcomes are a realistic mix, including a couple of abandoned calls (outcome
# and ended_at both NULL — that is exactly how analytics_outcomes counts them).
#
# (from_number, caller_type, outcome, days_ago, duration_s, turns)
CALLS = [
    ("+15125550501", "prospect", "qualified", 27.3, 214, 9),
    ("+15125550502", "prospect", "refer_out", 26.1, 132, 6),
    ("+15125550503", "prospect", "qualified", 24.6, 251, 11),
    ("+15125550504", "spam", "spam", 23.9, 18, 2),
    ("+15125550505", "prospect", "qualified", 22.4, 198, 8),
    ("+15125550506", "existing_client", "transferred", 21.0, 96, 4),
    ("+15125550507", "prospect", "not_qualified", 19.7, 143, 7),
    ("+15125550508", "prospect", "qualified", 18.2, 232, 10),
    ("+15125550509", "prospect", "qualified", 16.8, 188, 8),
    ("+15125550510", "spam", "spam", 15.5, 22, 2),
    ("+15125550511", "prospect", "refer_out", 14.1, 127, 6),
    ("+15125550512", "prospect", "qualified", 12.9, 241, 10),
    ("+15125550513", "existing_client", "transferred", 11.4, 88, 4),
    ("+15125550514", "prospect", "not_qualified", 10.2, 151, 7),
    ("+15125550515", "prospect", "qualified", 8.7, 205, 9),
    # Caller hung up mid-intake: no outcome, no ended_at.
    ("+15125550516", "prospect", None, 7.3, None, 3),
    ("+15125550517", "prospect", "qualified", 6.1, 219, 9),
    ("+15125550518", "prospect", "refer_out", 5.4, 118, 5),
    ("+15125550519", "prospect", "qualified", 4.2, 236, 10),
    ("+15125550520", "existing_client", "transferred", 3.6, 79, 4),
    ("+15125550521", "prospect", "qualified", 2.8, 193, 8),
    ("+15125550522", "prospect", "not_qualified", 2.1, 147, 7),
    ("+15125550523", "prospect", "qualified", 1.4, 228, 10),
    ("+15125550524", "prospect", None, 0.6, None, 2),
]

# Provider mix so "Latency by provider" has more than one row to compare. The
# second stack is the failover path, hence fewer calls and slightly worse TTFT.
# The factor is applied to LLM TTFT only, and is kept small on purpose: every
# seeded turn must stay under the 800 ms p95 SLO, or the demo dashboard shows a
# breach badge and contradicts the product's headline claim.
CALL_PROVIDERS = [
    ("deepgram", "deepseek", "cartesia", 1.00),
    ("deepgram", "openai", "cartesia", 1.06),
]

# Per-turn latency budget in ms, split across the stages the dashboard charts.
# Tuned to sit under the 800 ms p95 SLO with headroom, and to vary enough that
# p50 and p95 are visibly different rather than a flat line.
TURN_LATENCY_MS = [
    # (eou_delay, stt, llm_ttft, tts_ttfb, guardrail)
    (118, 84, 232, 141, 2.1),
    (96, 71, 198, 126, 1.7),
    (142, 92, 274, 158, 2.4),
    (104, 78, 211, 133, 1.9),
    (131, 88, 256, 149, 2.2),
    (89, 66, 187, 119, 1.6),
    (155, 97, 291, 167, 2.6),
    (112, 81, 224, 138, 2.0),
    (127, 86, 247, 145, 2.3),
    (99, 74, 205, 129, 1.8),
    (152, 95, 288, 161, 2.5),
    (108, 79, 218, 136, 1.9),
]


# Webform/ad leads for the speed-to-lead header on /threads. That panel reads
# ONLY `leads` with source in ('web','ad') from the last 30 days — a firm can
# have a full Conversations table and still show dashes there, because threads
# and leads are different tables. These rows are what the chaser would have
# produced: created_at when the form was submitted, first_contact_at when the
# chaser's first text went out.
#
# The spread is deliberately not uniform. Most contacts land in seconds (the
# chaser fires off the lead.created event), a couple are slower, and one is
# never contacted at all — so contact rate is realistically short of 100% and
# p95 sits meaningfully above p50 instead of collapsing onto it. Kept under the
# 60 s SLO because that is the honest picture of the system working.
#
# (contact, source, practice_area, days_ago, seconds_to_first_contact | None)
CHASER_LEADS = [
    (("Alicia Moreno", "+15125550440", None), "web", "personal injury", 27.4, 6),
    (("Devon Pratt", None, "devon.pratt@example.com"), "web", "personal injury", 25.1, 11),
    (("Rhonda K. Silva", "+15125550441", None), "ad", "personal injury", 23.8, 4),
    (("Marcus Bell", "+15125550401", None), "web", "personal injury", 21.2, 9),
    (("Tomas Iverson", "+15125550442", None), "web", "personal injury", 18.6, 38),
    (("Nadia Hassan", None, "n.hassan@example.com"), "ad", "personal injury", 16.9, 7),
    (("Curtis Lang", "+15125550443", None), "web", "personal injury", 14.3, 5),
    (("Bethany Cole", "+15125550444", None), "web", "personal injury", 12.7, 19),
    (("Ray Okafor", None, "ray.okafor@example.com"), "ad", "personal injury", 10.4, 8),
    (("Simone Vaught", "+15125550445", None), "web", "personal injury", 8.8, 3),
    (("Hector Ramos", "+15125550446", None), "web", "personal injury", 6.2, 31),
    (("Junie Whitlock", None, "junie.w@example.com"), "web", "personal injury", 4.5, 12),
    (("Aaron Delgado", "+15125550447", None), "ad", "personal injury", 2.9, 6),
    # Submitted with a bad number and a bounced email — nothing to contact.
    (("Pat Nolan", "+15125550448", None), "web", "personal injury", 1.6, None),
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
            ("out", "Hi Marcus, this is Caseline for {firm} — you asked about a car accident claim. Is now an okay time for a few quick questions?", 1.2),
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
            ("out", "Hello Priya, thanks for reaching out to {firm} about your workplace injury. Could you tell us when it happened and whether a report was filed?", 2.0),
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
            ("out", "Hi Luis, checking in from {firm}. How is your treatment going this week?", 7.0),
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
            ("out", "Hi Tara, your monthly treatment check-in from {firm}. How are you feeling, and are you still seeing your providers?", 5.0),
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


def _seed(cur, firm_id: str, agent_id: str, firm_name: str = "the firm") -> dict:
    counts = {"referral_partners": 0, "referrals": 0, "threads": 0, "messages": 0,
              "tuning_leads": 0, "lead_reviews": 0, "consults": 0, "chaser_leads": 0,
              "calls": 0, "turn_metrics": 0}

    def add_contact(name, phone, email) -> str:
        cur.execute(
            "INSERT INTO contacts (firm_id, name, phone, email, external_cms_id)"
            " VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (firm_id, name, phone, email, MARKER),
        )
        return cur.fetchone()["id"]

    def add_lead(contact_id, source, practice_area, qualification, status="new",
                 created_at=None, first_contact_at=None) -> str:
        cur.execute(
            "INSERT INTO leads (firm_id, source, contact_id, status, qualification,"
            " practice_area, external_cms_id, created_at, first_contact_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s, coalesce(%s, now()), %s) RETURNING id",
            (firm_id, source, contact_id, status,
             json.dumps(qualification) if qualification else None, practice_area, MARKER,
             created_at, first_contact_at),
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

    # --- calls + turn metrics: the whole Analytics page -------------------
    # Leads are attached to qualified calls (leads.call_id), and consults to
    # those leads, so the call-level booked rate has something to join on —
    # it counts calls that produced a consult, not consults in isolation.
    booked_call_leads = []
    for idx, (phone, caller_type, outcome, days_ago, duration, turns) in enumerate(CALLS):
        call_id = f"{MARKER}:call:{idx}"
        started = _ago(days_ago)
        ended = None if duration is None else started + timedelta(seconds=duration)
        stt, llm, tts, factor = CALL_PROVIDERS[idx % len(CALL_PROVIDERS)]

        totals = []
        for t in range(turns):
            eou, stt_ms, llm_ms, tts_ms, guard = TURN_LATENCY_MS[
                (idx * 3 + t) % len(TURN_LATENCY_MS)
            ]
            llm_ms *= factor
            total = eou + stt_ms + llm_ms + tts_ms + guard
            totals.append(total)
            cur.execute(
                "INSERT INTO turn_metrics (firm_id, call_id, speech_id, eou_delay_ms,"
                " stt_ms, llm_ttft_ms, tts_ttfb_ms, guardrail_ms, total_ms,"
                " stt_provider, llm_provider, tts_provider, created_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (firm_id, call_id, f"{call_id}:turn:{t}", eou, stt_ms, llm_ms, tts_ms,
                 guard, total, stt, llm, tts,
                 started + timedelta(seconds=12 * (t + 1))),
            )
        totals.sort()
        p50 = totals[len(totals) // 2]
        p95 = totals[min(len(totals) - 1, int(len(totals) * 0.95))]

        cur.execute(
            "INSERT INTO calls (id, firm_id, agent_id, direction, from_number,"
            " started_at, ended_at, outcome, caller_type, summary,"
            " latency_p50_ms, latency_p95_ms)"
            " VALUES (%s,%s,%s,'in',%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (firm_id, id) DO NOTHING",
            (call_id, firm_id, agent_id, phone, started, ended, outcome, caller_type,
             f"Inbound {caller_type.replace('_', ' ')} call — "
             f"{outcome.replace('_', ' ') if outcome else 'caller hung up mid-intake'}.",
             round(p50, 1), round(p95, 1)),
        )
        counts["calls"] += cur.rowcount
        counts["turn_metrics"] += turns

        if outcome == "qualified":
            cid = add_contact(f"Caller {phone[-4:]}", phone, None)
            cur.execute(
                "INSERT INTO leads (firm_id, source, contact_id, call_id, status,"
                " practice_area, external_cms_id, created_at)"
                " VALUES (%s,'phone',%s,%s,'qualified',%s,%s,%s) RETURNING id",
                (firm_id, cid, call_id, "personal injury", MARKER, started),
            )
            booked_call_leads.append((cur.fetchone()["id"], f"Caller {phone[-4:]}", phone))

    # Roughly half the qualified calls booked on the spot.
    for i, (lead_id, name, phone) in enumerate(booked_call_leads[::2]):
        cur.execute(
            "INSERT INTO consults (firm_id, lead_id, name, phone, slot_at, idempotency_key)"
            " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (firm_id, idempotency_key) DO NOTHING",
            (firm_id, lead_id, name, phone, _future_weekday(3 + i * 2, 10 + (i % 6)),
             f"{MARKER}:callconsult:{i}"),
        )
        counts["consults"] += cur.rowcount

    # --- webform/ad leads: the speed-to-lead panel on /threads ------------
    for contact, source, area, days_ago, secs in CHASER_LEADS:
        cid = add_contact(*contact)
        created = _ago(days_ago)
        add_lead(
            cid, source, area, None,
            status="new" if secs is None else "contacted",
            created_at=created,
            first_contact_at=None if secs is None else created + timedelta(seconds=secs),
        )
        counts["chaser_leads"] += 1

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
                # Messages name the firm they came from, so the seeded
                # transcript has to say whichever firm it is being seeded into.
                (firm_id, t["channel"], str(tid), direction,
                 body.format(firm=firm_name), ts),
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


# Every read and delete below filters on firm_id explicitly rather than leaning
# on RLS. This script connects as the table OWNER, and the tenant tables are
# ENABLE ROW LEVEL SECURITY without FORCE — which means policies do not apply to
# this connection at all. _set_firm() still sets app.firm_id (the INSERTs want
# it, and it is correct if the script is ever pointed at a non-owner role), but
# nothing here may treat it as a filter: an unscoped DELETE on a multi-firm
# deploy would wipe every tenant's seeded rows, silently and irreversibly.


def _already_seeded(cur, firm_id: str) -> bool:
    _set_firm(cur, firm_id)
    cur.execute(
        "SELECT count(*) AS n FROM referral_partners WHERE firm_id=%s AND notes LIKE %s",
        (firm_id, f"%{MARKER}%"),
    )
    return cur.fetchone()["n"] > 0


def _reset(cur, firm_id: str) -> None:
    _set_firm(cur, firm_id)
    # Delete children before parents. Seeded leads/contacts carry MARKER in
    # external_cms_id; referrals/reviews/consults/threads reference them.
    cur.execute("DELETE FROM referrals WHERE firm_id=%s AND lead_id IN"
                " (SELECT id FROM leads WHERE firm_id=%s AND external_cms_id=%s)",
                (firm_id, firm_id, MARKER))
    cur.execute("DELETE FROM referral_partners WHERE firm_id=%s AND notes LIKE %s",
                (firm_id, f"%{MARKER}%"))
    cur.execute("DELETE FROM lead_reviews WHERE firm_id=%s AND lead_id IN"
                " (SELECT id FROM leads WHERE firm_id=%s AND external_cms_id=%s)",
                (firm_id, firm_id, MARKER))
    cur.execute("DELETE FROM messages WHERE firm_id=%s AND thread_id IN"
                " (SELECT id::text FROM threads WHERE firm_id=%s AND state->>'seed'=%s)",
                (firm_id, firm_id, MARKER))
    cur.execute("DELETE FROM threads WHERE firm_id=%s AND state->>'seed'=%s", (firm_id, MARKER))
    cur.execute("DELETE FROM consults WHERE firm_id=%s AND idempotency_key LIKE %s",
                (firm_id, f"{MARKER}:%"))
    cur.execute("DELETE FROM turn_metrics WHERE firm_id=%s AND call_id LIKE %s",
                (firm_id, f"{MARKER}:call:%"))
    # Leads reference calls by the (firm_id, id) key, so calls go after them.
    cur.execute("DELETE FROM leads WHERE firm_id=%s AND external_cms_id=%s", (firm_id, MARKER))
    cur.execute("DELETE FROM calls WHERE firm_id=%s AND id LIKE %s",
                (firm_id, f"{MARKER}:call:%"))
    cur.execute("DELETE FROM contacts WHERE firm_id=%s AND external_cms_id=%s",
                (firm_id, MARKER))


def main() -> int:
    args = sys.argv[1:]
    reset = "--reset" in args
    firm_ref = None
    if "--firm" in args:
        i = args.index("--firm")
        if i + 1 >= len(args):
            print("--firm needs a firm name or uuid", file=sys.stderr)
            return 1
        firm_ref = args[i + 1]

    db_url = os.environ.get("CASELINE_DATABASE_URL") or dotenv_values(".env").get(
        "CASELINE_DATABASE_URL"
    )
    if not db_url:
        print("CASELINE_DATABASE_URL not set (env or .env)", file=sys.stderr)
        return 1

    with _conn(db_url) as conn:
        with conn.cursor() as cur:
            # Default to the oldest firm (the single-firm case). With more than
            # one firm on the deploy, seeding the wrong tenant is silent and
            # annoying to undo, so --firm selects explicitly.
            if firm_ref:
                cur.execute(
                    "SELECT id, name FROM firms WHERE id::text = %s OR name = %s",
                    (firm_ref, firm_ref),
                )
            else:
                cur.execute("SELECT id, name FROM firms ORDER BY created_at LIMIT 1")
            firm = cur.fetchone()
            if not firm:
                where = f"matching {firm_ref!r}" if firm_ref else "found"
                print(f"No firm {where} — run onboarding first.", file=sys.stderr)
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
            counts = _seed(cur, firm_id, agent_id, firm["name"])
            conn.commit()

    print(f"Seeded demo data for firm {firm['name']!r}:")
    for k, v in counts.items():
        print(f"  {k:18} +{v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
