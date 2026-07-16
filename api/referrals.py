"""Smart referrals (Phase 4): route declined-but-viable cases to partners.

"Declined-but-viable" means the engine said ``refer_out`` — a real case the
firm simply doesn't take (below threshold, wrong practice area), exactly
what a referral network monetizes. Hard declines (e.g. blown statute of
limitations) are not viable and are never referred.

Flow, and where the humans are:

  1. ``lead.qualified`` with decision ``refer_out`` -> the event worker calls
     :func:`propose_for_lead`, which matches partners and inserts a
     ``proposed`` referral. Idempotent by ``UNIQUE (firm_id, lead_id)`` — an
     event retry can never propose twice. Registering partners *is* the
     firm's opt-in: no partners, no referrals.
  2. A human sends it (``POST /v1/referrals/{id}/send``) with the client's
     consent recorded. Client PII leaves the system only at this step —
     an AI proposing is fine, an AI sharing a client's file is not.
  3. The partner's answer is tracked (``accepted`` / ``declined``) so the
     firm can see which partners convert.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import psycopg

from api.platform import events as platform_events
from api.platform.db import Database

logger = logging.getLogger("caseline.referrals")


@dataclass(frozen=True)
class PartnerMatch:
    partner_id: str
    partner_name: str
    score: int
    reasons: list[str]


def match_partners(
    partners: list[dict], practice_area: str | None, state: str | None
) -> list[PartnerMatch]:
    """Rank partners for a lead. Explicit practice-area match beats a
    take-anything partner; a state match breaks ties. Score 0 = no match."""
    matches: list[PartnerMatch] = []
    pa = (practice_area or "").strip().lower()
    st = (state or "").strip().upper()
    for p in partners:
        score = 0
        reasons: list[str] = []
        areas = [a.strip().lower() for a in (p.get("practice_areas") or [])]
        states = [s.strip().upper() for s in (p.get("states") or [])]
        if pa and pa in areas:
            score += 2
            reasons.append(f"handles {practice_area}")
        elif not areas:
            score += 1
            reasons.append("accepts all practice areas")
        if st and st in states:
            score += 1
            reasons.append(f"licensed in {state}")
        elif not states:
            reasons.append("no state restriction")
        if score > 0:
            matches.append(
                PartnerMatch(
                    partner_id=str(p["id"]), partner_name=p["name"], score=score, reasons=reasons
                )
            )
    return sorted(matches, key=lambda m: (-m.score, m.partner_name))


def _caller_state(conn: psycopg.Connection, call_id: str | None) -> str | None:
    """Best available lead geography: the consent state recorded on the call
    (derived from the caller's area code in Phase 2)."""
    if not call_id:
        return None
    row = conn.execute(
        "SELECT consent_state FROM calls WHERE id = %s", (call_id,)
    ).fetchone()
    return row["consent_state"] if row else None


def propose_for_lead(db: Database, firm_id: str, payload: dict) -> str | None:
    """Propose a referral for a refer_out lead. Returns the referral id, or
    None when the feature is off (no partners) or nothing matches."""
    lead_id = payload.get("lead_id")
    if not lead_id:
        return None
    with db.firm(firm_id) as conn:
        partners = conn.execute(
            "SELECT id, name, practice_areas, states, contact_email FROM referral_partners"
            " WHERE active ORDER BY created_at"
        ).fetchall()
        if not partners:
            return None  # firm has not opted into referrals
        lead = conn.execute(
            "SELECT id, practice_area, call_id FROM leads WHERE id = %s", (lead_id,)
        ).fetchone()
        if lead is None:
            return None
        state = _caller_state(conn, lead["call_id"])
        matches = match_partners(partners, lead["practice_area"], state)
        if not matches:
            logger.info("lead %s: no partner matches (area=%s state=%s)",
                        lead_id, lead["practice_area"], state)
            return None
        best = matches[0]
        row = conn.execute(
            "INSERT INTO referrals (firm_id, lead_id, partner_id, match_reasons)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT (firm_id, lead_id) DO NOTHING RETURNING id",
            (firm_id, lead_id, best.partner_id, json.dumps(best.reasons)),
        ).fetchone()
        if row is None:
            return None  # already proposed (event retry) — idempotent
        platform_events.emit(
            conn,
            firm_id,
            "referral.proposed",
            {
                "referral_id": str(row["id"]),
                "lead_id": str(lead_id),
                "partner_id": best.partner_id,
                "partner_name": best.partner_name,
                "match_reasons": best.reasons,
            },
        )
    logger.info("referral proposed: lead %s -> %s (%s)", lead_id, best.partner_name, best.reasons)
    return str(row["id"])


def build_packet(conn: psycopg.Connection, firm_id: str, lead_id: str) -> dict:
    """The case facts a partner receives, assembled at send time: identity +
    qualification facts, nothing else (no transcript, no internal notes)."""
    row = conn.execute(
        "SELECT l.practice_area, l.qualification, l.created_at,"
        "       c.name AS contact_name, c.phone AS contact_phone, c.email AS contact_email"
        " FROM leads l LEFT JOIN contacts c ON c.id = l.contact_id WHERE l.id = %s",
        (lead_id,),
    ).fetchone()
    if row is None:
        return {}
    q = row["qualification"] or {}
    return {
        "contact_name": row["contact_name"],
        "contact_phone": row["contact_phone"],
        "contact_email": row["contact_email"],
        "practice_area": row["practice_area"],
        "incident_date": q.get("incident_date"),
        "injury_type": q.get("injury_type"),
        "in_treatment": q.get("in_treatment"),
        "has_insurance": q.get("has_insurance"),
        "lead_created_at": str(row["created_at"]),
    }


def packet_email_body(firm_name: str, packet: dict, reasons: list[str]) -> str:
    lines = [
        f"{firm_name} is referring a potential case to your firm.",
        "",
        f"Client: {packet.get('contact_name') or 'see below'}",
        f"Phone: {packet.get('contact_phone') or 'n/a'}",
        f"Practice area: {packet.get('practice_area') or 'n/a'}",
        f"Incident date: {packet.get('incident_date') or 'n/a'}",
        f"Injury: {packet.get('injury_type') or 'n/a'}",
        f"In treatment: {packet.get('in_treatment')}",
        f"Insurance involved: {packet.get('has_insurance')}",
        "",
        "Why you: " + "; ".join(reasons),
        "",
        "The client has consented to this referral. Please respond to accept or decline.",
    ]
    return "\n".join(lines)
