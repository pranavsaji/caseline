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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from api import qualification
from api.messaging import SMSProvider, normalize_phone, sms_outbound_enabled
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


# A firm with no configured hours still needs bookable times; weekdays 9-5 is
# the safe default (matches config.is_open treating empty hours as open).
_DEFAULT_BUSINESS_HOURS = {d: [["09:00", "17:00"]] for d in ("mon", "tue", "wed", "thu", "fri")}
_DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_SLOT_MINUTES = 60
_MIN_LEAD = timedelta(hours=2)  # don't offer a slot in the next couple hours


def _firm_tz(ctx: ToolContext) -> ZoneInfo:
    try:
        return ZoneInfo(ctx.config.timezone or "America/Chicago")
    except Exception:
        return ZoneInfo("America/Chicago")


def _booked_slots(ctx: ToolContext, tz: ZoneInfo, after: datetime) -> set[datetime]:
    with ctx.db.firm(ctx.firm_id) as conn:
        rows = conn.execute(
            "SELECT slot_at FROM consults WHERE slot_at >= %s", (after,)
        ).fetchall()
    return {r["slot_at"].astimezone(tz).replace(second=0, microsecond=0) for r in rows}


def _generate_slots(ctx: ToolContext, days: int, max_slots: int) -> list[datetime]:
    """Open, bookable slots from the firm's business hours (firm tz), excluding
    already-booked times and anything too soon."""
    tz = _firm_tz(ctx)
    now = datetime.now(tz)
    hours = ctx.config.business_hours or _DEFAULT_BUSINESS_HOURS
    booked = _booked_slots(ctx, tz, now)
    out: list[datetime] = []
    for d in range(days + 1):
        day = now + timedelta(days=d)
        for start, end in hours.get(_DAY_KEYS[day.weekday()], []):
            sh, sm = (int(x) for x in start.split(":"))
            eh, em = (int(x) for x in end.split(":"))
            cur = day.replace(hour=sh, minute=sm, second=0, microsecond=0)
            end_dt = day.replace(hour=eh, minute=em, second=0, microsecond=0)
            while cur + timedelta(minutes=_SLOT_MINUTES) <= end_dt:
                if cur >= now + _MIN_LEAD and cur.replace(second=0, microsecond=0) not in booked:
                    out.append(cur)
                cur += timedelta(minutes=_SLOT_MINUTES)
        if len(out) >= max_slots:
            break
    return sorted(out)[:max_slots]


def _fmt_slot(dt: datetime) -> str:
    return dt.strftime("%A, %B %-d at %-I:%M %p")


def available_slots(ctx: ToolContext, days: int = 14, max_slots: int = 6) -> dict:
    """Real consultation availability: bookable slots from the firm's business
    hours minus what's already booked. The agent offers these instead of
    accepting any time the caller names."""
    slots = _generate_slots(ctx, days, max_slots)
    return {
        "slots": [{"slot_iso": s.isoformat(), "label": _fmt_slot(s)} for s in slots],
        "timezone": str(_firm_tz(ctx)),
    }


def _slot_is_available(ctx: ToolContext, slot_at: datetime) -> bool:
    """Whether a specific requested slot is offerable: inside business hours,
    far enough out, and not already taken."""
    tz = _firm_tz(ctx)
    want = slot_at.astimezone(tz).replace(second=0, microsecond=0)
    now = datetime.now(tz)
    if want < now + _MIN_LEAD:
        return False
    hours = ctx.config.business_hours or _DEFAULT_BUSINESS_HOURS
    windows = hours.get(_DAY_KEYS[want.weekday()], [])
    hhmm = want.strftime("%H:%M")
    in_hours = any(start <= hhmm < end for start, end in windows)
    if not in_hours:
        return False
    return want not in _booked_slots(ctx, tz, now)


def schedule_consult(
    ctx: ToolContext,
    call_id: str,
    name: str,
    phone: str,
    slot_iso: str,
    idempotency_key: str | None = None,
) -> dict:
    """Book a consult, idempotently: retrying the same logical booking (same
    key) returns the original consult instead of double-booking. Refuses a slot
    that isn't actually available so the agent can offer a real alternative."""
    key = idempotency_key or f"{call_id}:consult"
    try:
        slot_at = datetime.fromisoformat(slot_iso)
    except (ValueError, TypeError):
        return {"status": "unavailable", "reason": "bad_slot", "alternatives": available_slots(ctx)["slots"]}
    with ctx.db.firm(ctx.firm_id) as conn:
        existing = conn.execute(
            "SELECT id FROM consults WHERE idempotency_key = %s", (key,)
        ).fetchone()
        if existing:
            return {"status": "booked", "consult_id": str(existing["id"]), "duplicate": True}
    if not _slot_is_available(ctx, slot_at):
        # Taken / outside hours / too soon — hand back real options to offer.
        return {"status": "unavailable", "reason": "slot_taken", "alternatives": available_slots(ctx)["slots"]}
    with ctx.db.firm(ctx.firm_id) as conn:
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
    # STT frequently mangles a spoken number; normalize and refuse to hand a
    # bad 'To' to the transport (Twilio 422 -> otherwise a 500 that fails the
    # turn). A failed send is a normal outcome the agent handles, not an error.
    normalized = normalize_phone(to)
    if normalized is None:
        logger.warning("send_sms: invalid destination %r for call %s", to, call_id)
        return {"status": "failed", "reason": "invalid_number", "to": to}
    # Outbound SMS can be switched off (e.g. pending A2P 10DLC approval) so the
    # agent never promises a text the carrier will reject.
    if not sms_outbound_enabled():
        logger.info("send_sms: outbound SMS disabled; not sending to %s", normalized)
        return {"status": "failed", "reason": "disabled", "to": normalized}
    try:
        provider_id = ctx.sms.send(normalized, body)
    except httpx.HTTPError as exc:
        # Transport rejected it (unregistered 10DLC campaign, unverified number,
        # trial limits, outage). `exc` carries the provider's own reason.
        logger.warning("send_sms: transport error to %s: %s", normalized, exc)
        return {"status": "failed", "reason": "transport_error", "to": normalized}
    with ctx.db.firm(ctx.firm_id) as conn:
        row = conn.execute(
            "INSERT INTO messages (firm_id, channel, thread_id, direction, body)"
            " VALUES (%s, 'sms', %s, 'out', %s) RETURNING id",
            (ctx.firm_id, normalized, body),
        ).fetchone()
        events.emit(
            conn,
            ctx.firm_id,
            "message.sent",
            {"message_id": str(row["id"]), "call_id": call_id, "to": normalized, "provider_id": provider_id},
        )
    return {"status": "sent", "message_id": str(row["id"]), "to": normalized}


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
    consent_state: str | None = None,
    two_party_consent: bool | None = None,
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
            " caller_type, summary, structured, consent_state, two_party_consent)"
            " VALUES (%s, %s, %s, %s, now(), %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (firm_id, id) DO UPDATE SET ended_at = now(), outcome = EXCLUDED.outcome,"
            " caller_type = EXCLUDED.caller_type, summary = EXCLUDED.summary,"
            " structured = EXCLUDED.structured, consent_state = EXCLUDED.consent_state,"
            " two_party_consent = EXCLUDED.two_party_consent",
            (
                call_id,
                ctx.firm_id,
                ctx.config.agent_id,
                from_number,
                outcome or structured.get("decision"),
                caller_type,
                summary,
                json.dumps(structured),
                consent_state,
                two_party_consent,
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
