"""Typed tool layer: the deterministic actions the LLM can select.

Each tool is a plain, tested function — the LLM only ever chooses one and
fills its parameters; nothing probabilistic executes here (WAT-style
separation, guiding principle: the hot path is sacred). Every function takes
a ``ToolContext`` and firm-scoped data; every write goes through the RLS
connection and emits its event in the same transaction.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from api import qualification
from api.messaging import SMSProvider
from api.orchestration.config import AgentConfig
from api.platform import events
from api.platform.db import Database
from api.platform.session_state import SessionStore

logger = logging.getLogger("caseline.tools")


@dataclass
class ToolContext:
    db: Database
    store: SessionStore
    sms: SMSProvider
    firm_id: str
    config: AgentConfig


# ---------------------------------------------------------------------------
# lookup_caller
# ---------------------------------------------------------------------------


def lookup_caller(ctx: ToolContext, phone: str) -> dict:
    """Known-caller lookup by phone: returning lead, existing client, or new."""
    with ctx.db.firm(ctx.firm_id) as conn:
        contact = conn.execute(
            "SELECT id, name, phone, email, external_cms_id FROM contacts"
            " WHERE phone = %s ORDER BY created_at DESC LIMIT 1",
            (phone,),
        ).fetchone()
        if contact is None:
            return {"known": False}
        lead = conn.execute(
            "SELECT id, status, practice_area FROM leads"
            " WHERE contact_id = %s ORDER BY created_at DESC LIMIT 1",
            (contact["id"],),
        ).fetchone()
    return {
        "known": True,
        "contact_id": str(contact["id"]),
        "name": contact["name"],
        "in_cms": contact["external_cms_id"] is not None,
        "last_lead_status": lead["status"] if lead else None,
    }


# ---------------------------------------------------------------------------
# qualify_lead
# ---------------------------------------------------------------------------


def qualify_lead(
    ctx: ToolContext,
    call_id: str,
    incident_date: str,
    injury_type: str,
    in_treatment: bool,
    has_insurance: bool,
) -> dict:
    """Run the firm's qualification rules and persist the lead + decision."""
    rules = ctx.config.qualification
    result = qualification.qualify(
        incident_date=incident_date,
        injury_type=injury_type,
        in_treatment=in_treatment,
        has_insurance=has_insurance,
        config=qualification.QualificationConfig(
            statute_of_limitations_days=rules.statute_of_limitations_days,
            refer_out_injuries=frozenset(i.lower() for i in rules.refer_out_injuries),
        ),
    )
    qual_payload = {
        "incident_date": incident_date,
        "injury_type": injury_type,
        "in_treatment": in_treatment,
        "has_insurance": has_insurance,
        "decision": result.decision,
        "reasons": result.reasons,
    }
    with ctx.db.firm(ctx.firm_id) as conn:
        row = conn.execute(
            "INSERT INTO leads (firm_id, source, call_id, status, qualification, practice_area)"
            " VALUES (%s, 'phone', %s, %s, %s, %s) RETURNING id",
            (
                ctx.firm_id,
                call_id,
                result.decision,
                json.dumps(qual_payload),
                ctx.config.script.practice_area,
            ),
        ).fetchone()
        events.emit(
            conn,
            ctx.firm_id,
            "lead.qualified",
            {"lead_id": str(row["id"]), "call_id": call_id, **qual_payload},
        )
    return {"lead_id": str(row["id"]), "decision": result.decision, "reasons": result.reasons}


# ---------------------------------------------------------------------------
# schedule_consult
# ---------------------------------------------------------------------------


def schedule_consult(
    ctx: ToolContext,
    call_id: str,
    name: str,
    phone: str,
    slot_iso: str,
    idempotency_key: str | None = None,
) -> dict:
    """Book a consult, idempotently: retrying the same logical booking (same
    key) returns the original consult instead of double-booking."""
    key = idempotency_key or f"{call_id}:consult"
    slot_at = datetime.fromisoformat(slot_iso)
    with ctx.db.firm(ctx.firm_id) as conn:
        existing = conn.execute(
            "SELECT id FROM consults WHERE idempotency_key = %s", (key,)
        ).fetchone()
        if existing:
            return {"status": "booked", "consult_id": str(existing["id"]), "duplicate": True}
        lead = conn.execute(
            "SELECT id FROM leads WHERE call_id = %s ORDER BY created_at DESC LIMIT 1",
            (call_id,),
        ).fetchone()
        row = conn.execute(
            "INSERT INTO consults (firm_id, lead_id, name, phone, slot_at, idempotency_key)"
            " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (ctx.firm_id, lead["id"] if lead else None, name, phone, slot_at, key),
        ).fetchone()
        events.emit(
            conn,
            ctx.firm_id,
            "consult.booked",
            {
                "consult_id": str(row["id"]),
                "call_id": call_id,
                "name": name,
                "phone": phone,
                "slot_iso": slot_iso,
            },
        )
    return {"status": "booked", "consult_id": str(row["id"]), "duplicate": False}


# ---------------------------------------------------------------------------
# transfer_to_human
# ---------------------------------------------------------------------------


def transfer_to_human(ctx: ToolContext, call_id: str, reason: str) -> dict:
    """Resolve the escape hatch: a live transfer target during business
    hours, the after-hours behavior otherwise. The actual SIP REFER happens
    in the voice worker; this decides and audits."""
    routing = ctx.config.routing
    open_now = ctx.config.is_open()
    if routing.transfer_number and open_now:
        action, target = "transfer", routing.transfer_number
    else:
        action, target = routing.after_hours_behavior, None
    with ctx.db.firm(ctx.firm_id) as conn:
        events.emit(
            conn,
            ctx.firm_id,
            "call.transfer_requested",
            {
                "call_id": call_id,
                "reason": reason,
                "action": action,
                "target": target,
                "business_hours_open": open_now,
            },
        )
    return {"action": action, "target": target}


# ---------------------------------------------------------------------------
# send_sms
# ---------------------------------------------------------------------------


def send_sms(ctx: ToolContext, call_id: str, to: str, body: str) -> dict:
    provider_id = ctx.sms.send(to, body)
    with ctx.db.firm(ctx.firm_id) as conn:
        row = conn.execute(
            "INSERT INTO messages (firm_id, channel, thread_id, direction, body)"
            " VALUES (%s, 'sms', %s, 'out', %s) RETURNING id",
            (ctx.firm_id, to, body),
        ).fetchone()
        events.emit(
            conn,
            ctx.firm_id,
            "message.sent",
            {"message_id": str(row["id"]), "call_id": call_id, "to": to, "provider_id": provider_id},
        )
    return {"status": "sent", "message_id": str(row["id"])}


# ---------------------------------------------------------------------------
# take_message
# ---------------------------------------------------------------------------


def take_message(ctx: ToolContext, call_id: str, caller_name: str, phone: str, body: str) -> dict:
    with ctx.db.firm(ctx.firm_id) as conn:
        row = conn.execute(
            "INSERT INTO messages (firm_id, channel, thread_id, direction, body)"
            " VALUES (%s, 'voice_note', %s, 'in', %s) RETURNING id",
            (ctx.firm_id, call_id, f"Message from {caller_name} ({phone}): {body}"),
        ).fetchone()
        events.emit(
            conn,
            ctx.firm_id,
            "message.taken",
            {
                "message_id": str(row["id"]),
                "call_id": call_id,
                "caller_name": caller_name,
                "phone": phone,
                "body": body,
            },
        )
    return {"status": "taken", "message_id": str(row["id"])}


# ---------------------------------------------------------------------------
# complete_call (the write_to_cms tool lands here; CMS write is async)
# ---------------------------------------------------------------------------


def complete_call(
    ctx: ToolContext,
    call_id: str,
    summary: str,
    structured: dict,
    outcome: str | None = None,
    caller_type: str | None = None,
    from_number: str | None = None,
) -> dict:
    """Persist the call outcome and emit ``call.completed``. The CMS write is
    performed by the async worker consuming that event — never inline
    (cross-phase rule: no synchronous CMS calls from the voice path)."""
    with ctx.db.firm(ctx.firm_id) as conn:
        # Upsert the contact the structured facts describe, if any.
        contact_id = None
        name = structured.get("name") or structured.get("caller_name")
        phone = structured.get("phone") or from_number
        if name and phone:
            existing = conn.execute(
                "SELECT id FROM contacts WHERE phone = %s LIMIT 1", (phone,)
            ).fetchone()
            if existing:
                contact_id = existing["id"]
            else:
                contact_id = conn.execute(
                    "INSERT INTO contacts (firm_id, name, phone) VALUES (%s, %s, %s) RETURNING id",
                    (ctx.firm_id, name, phone),
                ).fetchone()["id"]
        conn.execute(
            "INSERT INTO calls (id, firm_id, agent_id, from_number, ended_at, outcome,"
            " caller_type, summary, structured)"
            " VALUES (%s, %s, %s, %s, now(), %s, %s, %s, %s)"
            " ON CONFLICT (firm_id, id) DO UPDATE SET ended_at = now(), outcome = EXCLUDED.outcome,"
            " caller_type = EXCLUDED.caller_type, summary = EXCLUDED.summary,"
            " structured = EXCLUDED.structured",
            (
                call_id,
                ctx.firm_id,
                ctx.config.agent_id,
                from_number,
                outcome or structured.get("decision"),
                caller_type,
                summary,
                json.dumps(structured),
            ),
        )
        if contact_id is not None:
            conn.execute(
                "UPDATE leads SET contact_id = %s WHERE call_id = %s AND contact_id IS NULL",
                (contact_id, call_id),
            )
        events.emit(
            conn,
            ctx.firm_id,
            "call.completed",
            {
                "call_id": call_id,
                "summary": summary,
                "structured": structured,
                "outcome": outcome or structured.get("decision"),
                "contact_id": str(contact_id) if contact_id else None,
            },
        )
    return {"status": "saved", "call_id": call_id}
