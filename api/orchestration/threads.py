"""Async thread orchestration (Phase 3): the same brain over SMS/email.

The voice worker and this module run the *same* orchestration policy — one
``AgentConfig`` (script, qualification rules, routing, guardrails), the same
``api.qualification`` rules engine, and the same ``GuardrailScreen`` on every
outbound utterance. Only the transport differs: instead of a held audio
connection, thread state lives in Postgres (``threads.state``) and follow-ups
are scheduled rows (``followups``), never held connections.

Two layers, deliberately separated:

  * The **brain** — ``intake_opening`` / ``advance_intake`` /
    ``advance_tracker`` — is pure: (config, state, inbound text) -> (new
    state, reply, actions). Deterministic slot-filling intake mirroring the
    voice script: incident date -> injury -> treatment -> insurance ->
    qualify -> book. Pure means the config-studio *test-call preview* runs
    the identical code with zero side effects.
  * The **engine** — ``ThreadEngine`` — executes actions: RLS-scoped
    persistence, event emission (``lead.qualified`` / ``consult.booked``
    payloads match the voice path, so CMS sync consumes threads unchanged),
    idempotent booking, follow-up scheduling, guardrail-screened sends.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from api import qualification
from api.compliance.outbound import next_allowed_time
from api.messaging import EmailProvider, SMSProvider
from api.orchestration.config import AgentConfig, load_agent_config
from api.orchestration.guardrails import GuardrailScreen
from api.platform import events as platform_events
from api.platform.db import Database
from api.platform.session_state import SessionStore

logger = logging.getLogger("caseline.orchestration.threads")

# Intake steps (threads.state["step"])
STEP_DATE = "collect_incident_date"
STEP_INJURY = "collect_injury"
STEP_TREATMENT = "collect_treatment"
STEP_INSURANCE = "collect_insurance"
STEP_SLOT = "offer_slot"
STEP_DONE = "done"
# Tracker step
STEP_AWAITING_UPDATE = "awaiting_update"

MAX_NUDGES = 2
NUDGE_AFTER_HOURS = 4.0
DEFAULT_TRACKER_CADENCE_DAYS = 14


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Deterministic parsers — the async stand-in for the voice LLM's extraction.
# Anything unparseable is re-asked once, then passed through raw so the
# qualification engine's needs-human-verification path applies (never
# auto-decline on a parsing failure — same rule as Phase 0).
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_SMALL_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "a couple of": 2, "couple": 2, "two": 2, "three": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RE_RELATIVE = re.compile(
    r"\b(a couple of|couple|an?|one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
    r"\s+(day|week|month|year)s?\s+ago\b"
)
_RE_MONTH_NAME = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?\b"
)
_RE_NUMERIC = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b")


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _infer_year(month: int, day: int, today: date) -> date | None:
    candidate = _safe_date(today.year, month, day)
    if candidate is None:
        return None
    # "June 1" said in March means *last* June — no year given never means
    # a future incident.
    return candidate if candidate <= today else _safe_date(today.year - 1, month, day)


def parse_date_phrase(raw: str, today: date) -> str | None:
    """Extract an incident date from conversational text; returns ISO or None."""
    text = raw.strip().lower()
    if not text:
        return None
    if "today" in text:
        return today.isoformat()
    if "yesterday" in text:
        return (today - timedelta(days=1)).isoformat()
    if m := _RE_RELATIVE.search(text):
        qty = _SMALL_NUMBERS.get(m.group(1), None)
        if qty is None:
            qty = int(m.group(1))
        unit_days = {"day": 1, "week": 7, "month": 30, "year": 365}[m.group(2)]
        return (today - timedelta(days=qty * unit_days)).isoformat()
    if m := _RE_ISO.search(text):
        parsed = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return parsed.isoformat() if parsed else None
    if m := _RE_MONTH_NAME.search(text):
        month, day = _MONTHS[m.group(1)], int(m.group(2))
        if m.group(3):
            parsed = _safe_date(int(m.group(3)), month, day)
        else:
            parsed = _infer_year(month, day, today)
        return parsed.isoformat() if parsed else None
    if m := _RE_NUMERIC.search(text):
        month, day = int(m.group(1)), int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            if year < 100:
                year += 2000
            parsed = _safe_date(year, month, day)
        else:
            parsed = _infer_year(month, day, today)
        return parsed.isoformat() if parsed else None
    return None


_RE_NO = re.compile(r"\b(no|nope|nah|not|don'?t|never|none)\b", re.IGNORECASE)
_RE_YES = re.compile(
    r"\b(yes|yeah|yep|yup|sure|correct|definitely|affirmative|i am|i do)\b", re.IGNORECASE
)


def parse_yes_no(raw: str) -> bool | None:
    """Yes/no from conversational text; None when it can't be determined."""
    if _RE_NO.search(raw):
        return False
    if _RE_YES.search(raw):
        return True
    return None


def offer_slots(now: datetime, tz_name: str) -> list[dict]:
    """Two concrete consult options on the next business day, firm-local."""
    zone = ZoneInfo(tz_name)
    day = (now.astimezone(zone) + timedelta(days=1)).date()
    while day.weekday() >= 5:  # never offer a weekend slot
        day += timedelta(days=1)
    slots = []
    for hour, label in ((10, "10:00 AM"), (15, "3:00 PM")):
        dt = datetime.combine(day, time(hour), tzinfo=zone)
        slots.append(
            {"label": f"{day.strftime('%A, %B')} {day.day} at {label}", "iso": dt.isoformat()}
        )
    return slots


def parse_slot_choice(raw: str, slots: list[dict]) -> int | None:
    text = raw.strip().lower()
    # Explicit time-of-day / ordinal words win over incidental numbers
    # ("the afternoon one" is a clear pick despite containing "one").
    if re.search(r"\b(afternoon|second)\b", text):
        return 1 if len(slots) > 1 else None
    if re.search(r"\b(morning|first)\b", text):
        return 0
    first = re.search(r"\b(1|one|10(:00)?\s*(am)?)\b", text)
    second = re.search(r"\b(2|two|3(:00)?\s*(pm)?|15)\b", text)
    if first and not second:
        return 0
    if second and not first:
        return 1 if len(slots) > 1 else None
    return None


# ---------------------------------------------------------------------------
# The pure brain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    kind: str  # qualify | book | take_message | tracker_update | schedule_checkin
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BrainResult:
    state: dict
    reply: str | None
    actions: list[Action] = field(default_factory=list)
    close_reason: str | None = None


def _ask_injury(prefix: str = "") -> str:
    return f"{prefix}Briefly, what kind of injury did you have?"


def intake_opening(config: AgentConfig, name: str | None, source: str) -> tuple[dict, str]:
    """Initial state + first outbound message for a chaser/intake thread.
    The first message always carries the AI disclosure and the opt-out notice
    (CTIA) — config cannot turn either off on an outbound-initiated thread."""
    who = name or "there"
    text = (
        f"Hi {who}! This is {config.agent_name}, the AI intake assistant for "
        f"{config.firm_name}. Thanks for reaching out about your "
        f"{config.script.practice_area} matter — I can get you set up right now. "
        "First: what date did the incident happen? (Reply STOP to opt out.)"
    )
    return {"step": STEP_DATE, "slots": {}, "attempts": {}, "source": source}, text


def advance_intake(
    config: AgentConfig,
    state: dict,
    inbound: str,
    *,
    now: datetime | None = None,
    contact_name: str | None = None,
) -> BrainResult:
    """One turn of the intake state machine. Pure: no I/O, no side effects."""
    now = now or _utcnow()
    state = json.loads(json.dumps(state))  # never mutate the caller's copy
    slots: dict = state.setdefault("slots", {})
    attempts: dict = state.setdefault("attempts", {})
    step = state.get("step", STEP_DATE)
    text = inbound.strip()
    actions: list[Action] = []
    reply: str | None = None
    close_reason: str | None = None
    today = now.astimezone(ZoneInfo(config.timezone)).date()

    if step == STEP_DATE:
        parsed = parse_date_phrase(text, today)
        if parsed:
            slots["incident_date"] = parsed
            state["step"] = STEP_INJURY
            reply = _ask_injury("Got it. ")
        elif attempts.get("incident_date", 0) < 1:
            attempts["incident_date"] = attempts.get("incident_date", 0) + 1
            reply = (
                "Sorry, I didn't catch the date. You can say it like 6/1/2026, "
                "'June 1', or 'two weeks ago'."
            )
        else:
            # Never block intake on a date we can't parse — the qualification
            # engine flags it for human verification instead of declining.
            slots["incident_date"] = text
            state["step"] = STEP_INJURY
            reply = _ask_injury("No problem — our team will confirm the exact date with you. ")

    elif step == STEP_INJURY:
        slots["injury_type"] = text[:200]
        state["step"] = STEP_TREATMENT
        reply = "Thanks. Are you currently receiving medical treatment for it? (yes/no)"

    elif step == STEP_TREATMENT:
        answer = parse_yes_no(text)
        if answer is None and attempts.get("in_treatment", 0) < 1:
            attempts["in_treatment"] = attempts.get("in_treatment", 0) + 1
            reply = "Just to confirm — are you currently receiving medical treatment? A quick yes or no works."
        else:
            slots["in_treatment"] = bool(answer)
            state["step"] = STEP_INSURANCE
            reply = "And is there insurance involved — yours or the other party's? (yes/no)"

    elif step == STEP_INSURANCE:
        answer = parse_yes_no(text)
        if answer is None and attempts.get("has_insurance", 0) < 1:
            attempts["has_insurance"] = attempts.get("has_insurance", 0) + 1
            reply = "Sorry — is there any insurance involved? A quick yes or no works."
        else:
            slots["has_insurance"] = bool(answer)
            rules = config.qualification
            result = qualification.qualify(
                incident_date=str(slots.get("incident_date", "")),
                injury_type=str(slots.get("injury_type", "")),
                in_treatment=bool(slots.get("in_treatment")),
                has_insurance=bool(slots.get("has_insurance")),
                config=qualification.QualificationConfig(
                    statute_of_limitations_days=rules.statute_of_limitations_days,
                    refer_out_injuries=frozenset(i.lower() for i in rules.refer_out_injuries),
                ),
                today=today,
            )
            actions.append(Action("qualify", {**slots, "decision": result.decision, "reasons": result.reasons}))
            if result.decision == qualification.DECISION_QUALIFIED:
                offered = offer_slots(now, config.timezone)
                state["offered_slots"] = offered
                state["step"] = STEP_SLOT
                reply = (
                    f"Good news — this sounds like something {config.firm_name} may be able "
                    f"to help with. I can book you a free consultation: reply 1 for "
                    f"{offered[0]['label']} or 2 for {offered[1]['label']}."
                )
            elif result.decision == qualification.DECISION_REFER_OUT:
                state["step"] = STEP_DONE
                close_reason = "refer_out"
                reply = (
                    f"Thank you for sharing all that. Based on what you've described, "
                    f"{config.firm_name} may not be the best fit for this matter, but our "
                    "team will review it and may connect you with a firm that can help. "
                    "You'll hear from us either way."
                )
            else:
                state["step"] = STEP_DONE
                close_reason = "decline"
                reply = (
                    "Thank you for sharing all that. The time window for this kind of case "
                    "may have passed, so we likely can't take it on — but our team will "
                    "double-check and reach out if there's a path forward."
                )

    elif step == STEP_SLOT:
        offered = state.get("offered_slots", [])
        choice = parse_slot_choice(text, offered) if offered else None
        if choice is not None:
            chosen = offered[choice]
            actions.append(Action("book", {"slot_iso": chosen["iso"], "label": chosen["label"]}))
            state["step"] = STEP_DONE
            close_reason = "booked"
            reply = (
                f"Perfect — you're booked for {chosen['label']}. An attorney from "
                f"{config.firm_name} will call you then. If you need to change it, "
                "just reply here."
            )
        elif attempts.get("slot", 0) < 1:
            attempts["slot"] = attempts.get("slot", 0) + 1
            labels = " or ".join(s["label"] for s in offered)
            reply = f"Just reply 1 or 2 to pick a time ({labels})."
        else:
            actions.append(Action("take_message", {"body": text, "caller_name": contact_name or "Web lead"}))
            state["step"] = STEP_DONE
            close_reason = "needs_human_scheduling"
            reply = (
                "No problem — I'll have our intake team reach out to find a time that "
                "works for you. Thanks!"
            )

    else:  # STEP_DONE or unknown: the thread should already be closed
        reply = None

    return BrainResult(state=state, reply=reply, actions=actions, close_reason=close_reason)


# --- treatment tracker brain ---


_RE_TREATMENT_DONE = re.compile(
    r"\b(done|finished|discharged|completed?|released|wrapped up|all better|no more (treatment|appointments))\b",
    re.IGNORECASE,
)


def tracker_opening(config: AgentConfig, name: str | None, cadence_days: int) -> tuple[dict, str]:
    who = name or "there"
    text = (
        f"Hi {who}, this is {config.agent_name} with {config.firm_name}. While your case "
        f"moves forward I'll check in every {cadence_days} days about your medical "
        "treatment and any documents your legal team needs. You can also text me an "
        "update anytime. (Reply STOP to opt out.)"
    )
    return {"step": STEP_AWAITING_UPDATE, "cadence_days": cadence_days, "updates": 0}, text


def tracker_checkin_message(config: AgentConfig, name: str | None) -> str:
    who = name or "there"
    return (
        f"Hi {who}, quick check-in from {config.firm_name}: how is your treatment going? "
        "Any new providers or appointments — or are you finished treating?"
    )


def advance_tracker(config: AgentConfig, state: dict, inbound: str) -> BrainResult:
    """One turn of the treatment-tracker state machine. Pure."""
    state = json.loads(json.dumps(state))
    state["updates"] = int(state.get("updates", 0)) + 1
    cadence = int(state.get("cadence_days", DEFAULT_TRACKER_CADENCE_DAYS))
    if _RE_TREATMENT_DONE.search(inbound):
        actions = [Action("tracker_update", {"kind": "treatment_complete", "note": inbound.strip()})]
        reply = (
            "That's great news — I've let your legal team know you've finished treating. "
            "They'll be in touch about next steps."
        )
        return BrainResult(state=state, reply=reply, actions=actions, close_reason="treatment_complete")
    actions = [
        Action("tracker_update", {"kind": "progress", "note": inbound.strip()}),
        Action("schedule_checkin", {"cadence_days": cadence}),
    ]
    reply = (
        "Thanks for the update — I've shared it with your legal team. "
        f"I'll check in again in about {cadence} days; text me sooner if anything changes."
    )
    return BrainResult(state=state, reply=reply, actions=actions)


# ---------------------------------------------------------------------------
# Test-call preview (config studio v1): the same brain, zero side effects.
# ---------------------------------------------------------------------------


def preview_conversation(
    config: AgentConfig,
    caller_messages: list[str],
    *,
    now: datetime | None = None,
    contact_name: str | None = "Preview Caller",
) -> dict:
    """Simulate an intake conversation against a (possibly unsaved) config."""
    now = now or _utcnow()
    screen = GuardrailScreen(extra_blocked_patterns=config.guardrails.extra_blocked_patterns)
    state, opening = intake_opening(config, contact_name, source="preview")
    turns: list[dict] = [{"role": "agent", "text": opening}]
    actions: list[dict] = []
    close_reason: str | None = None
    for message in caller_messages:
        if close_reason:
            break
        turns.append({"role": "caller", "text": message})
        result = advance_intake(config, state, message, now=now, contact_name=contact_name)
        state = result.state
        actions.extend({"kind": a.kind, **a.data} for a in result.actions)
        if result.reply:
            verdict = screen.screen(result.reply)
            turns.append(
                {
                    "role": "agent",
                    "text": result.reply if verdict.allowed else config.guardrails.deflection_line,
                    "guardrail_tripped": None if verdict.allowed else verdict.category,
                }
            )
        close_reason = result.close_reason
    return {
        "turns": turns,
        "actions": actions,
        "closed_reason": close_reason,
        "final_step": state.get("step"),
        "instructions": config.instructions(),
    }


# ---------------------------------------------------------------------------
# The engine: persistence, events, sends. Everything RLS-scoped.
# ---------------------------------------------------------------------------


class ThreadEngine:
    def __init__(self, db: Database, store: SessionStore, sms: SMSProvider, email: EmailProvider):
        self.db = db
        self.store = store
        self.sms = sms
        self.email = email

    # --- helpers ---

    def _config(self, firm_id: str) -> AgentConfig | None:
        return load_agent_config(self.db, self.store, firm_id)

    def _deliver(self, config: AgentConfig, channel: str, address: str, body: str) -> str:
        """Guardrail-screened outbound send. Same policy as the voice path:
        a tripped screen speaks the deflection line, never the raw text."""
        screen = GuardrailScreen(extra_blocked_patterns=config.guardrails.extra_blocked_patterns)
        verdict = screen.screen(body)
        if not verdict.allowed:
            logger.warning("thread guardrail tripped (%s); deflecting", verdict.category)
            body = config.guardrails.deflection_line
        if channel == "email":
            return self.email.send(address, f"{config.firm_name} — your case inquiry", body)
        return self.sms.send(address, body)

    def _record_outbound(self, conn, firm_id: str, thread_id: str, channel: str, body: str) -> None:
        conn.execute(
            "INSERT INTO messages (firm_id, channel, thread_id, direction, body)"
            " VALUES (%s, %s, %s, 'out', %s)",
            (firm_id, channel, thread_id, body),
        )
        conn.execute(
            "UPDATE threads SET last_outbound_at = now(), updated_at = now() WHERE id = %s",
            (thread_id,),
        )

    def _schedule_followup(
        self, conn, firm_id: str, thread_id: str | None, type_: str, due_at: datetime, payload: dict | None = None
    ) -> None:
        conn.execute(
            "INSERT INTO followups (firm_id, thread_id, type, due_at, payload)"
            " VALUES (%s, %s, %s, %s, %s)",
            (firm_id, thread_id, type_, due_at, json.dumps(payload or {})),
        )

    def _cancel_followups(self, conn, thread_id: str, type_: str | None = None) -> None:
        extra = " AND type = %s" if type_ else ""
        params = (thread_id, type_) if type_ else (thread_id,)
        conn.execute(
            f"UPDATE followups SET status = 'canceled', done_at = now()"
            f" WHERE thread_id = %s AND status = 'pending'{extra}",
            params,
        )

    def _close_thread(self, conn, firm_id: str, thread_id: str, reason: str) -> None:
        conn.execute(
            "UPDATE threads SET status = 'closed', closed_reason = %s, updated_at = now()"
            " WHERE id = %s",
            (reason, thread_id),
        )
        self._cancel_followups(conn, thread_id)
        platform_events.emit(conn, firm_id, "thread.closed", {"thread_id": thread_id, "reason": reason})

    def send_manual_message(self, firm_id: str, thread_id: str, body: str) -> dict:
        """Staff-triggered outbound follow-up on an open thread. Same guardrail
        screen and outbound bookkeeping as an automated send; a manual reach-out
        disarms any pending no-reply nudge so the client isn't double-contacted."""
        config = self._config(firm_id)
        if config is None:
            raise RuntimeError("firm has no configured agent")
        with self.db.firm(firm_id) as conn:
            thread = conn.execute(
                "SELECT id, channel, address, status FROM threads WHERE id = %s",
                (thread_id,),
            ).fetchone()
            if thread is None:
                raise KeyError("thread not found")
            if thread["status"] != "open":
                raise RuntimeError("thread is closed")
            self._deliver(config, thread["channel"], thread["address"], body)
            self._record_outbound(conn, firm_id, thread_id, thread["channel"], body)
            self._cancel_followups(conn, thread_id, "chaser.nudge")
            platform_events.emit(
                conn, firm_id, "thread.manual_message", {"thread_id": thread_id}
            )
        return {"status": "sent", "thread_id": thread_id}

    # --- starting threads ---

    def start_intake_thread(
        self,
        firm_id: str,
        *,
        channel: str,
        address: str,
        contact_id: str | None,
        lead_id: str | None,
        name: str | None,
        source: str = "web",
        now: datetime | None = None,
    ) -> str:
        """First contact for a chased lead: create (or reuse) the open thread,
        send the opening message, stamp the speed-to-lead metric, and arm the
        no-reply nudge."""
        now = now or _utcnow()
        config = self._config(firm_id)
        if config is None:
            raise RuntimeError(f"firm {firm_id} has no configured agent")
        state, opening = intake_opening(config, name, source)
        with self.db.firm(firm_id) as conn:
            existing = conn.execute(
                "SELECT id FROM threads WHERE channel = %s AND address = %s AND status = 'open'",
                (channel, address),
            ).fetchone()
            if existing:
                return str(existing["id"])  # a live conversation already exists — never restart it
            thread_id = str(
                conn.execute(
                    "INSERT INTO threads (firm_id, channel, address, contact_id, lead_id, goal, state)"
                    " VALUES (%s, %s, %s, %s, %s, 'intake', %s) RETURNING id",
                    (firm_id, channel, address, contact_id, lead_id, json.dumps(state)),
                ).fetchone()["id"]
            )
            self._deliver(config, channel, address, opening)
            self._record_outbound(conn, firm_id, thread_id, channel, opening)
            if lead_id:
                conn.execute(
                    "UPDATE leads SET first_contact_at = now(), status = 'contacted'"
                    " WHERE id = %s AND first_contact_at IS NULL",
                    (lead_id,),
                )
            nudge_at = now + timedelta(hours=NUDGE_AFTER_HOURS)
            if channel == "sms":
                nudge_at = max(nudge_at, next_allowed_time(address, config.timezone, nudge_at))
            self._schedule_followup(conn, firm_id, thread_id, "chaser.nudge", nudge_at)
            platform_events.emit(
                conn,
                firm_id,
                "thread.started",
                {"thread_id": thread_id, "channel": channel, "goal": "intake", "lead_id": lead_id},
            )
        return thread_id

    def enroll_tracker(
        self,
        firm_id: str,
        *,
        name: str,
        phone: str,
        matter_description: str | None = None,
        cadence_days: int = DEFAULT_TRACKER_CADENCE_DAYS,
        now: datetime | None = None,
    ) -> str:
        """Enroll a signed client in the treatment tracker: intro message now,
        check-ins on a cadence, updates fanned out to the CMS as tasks."""
        now = now or _utcnow()
        config = self._config(firm_id)
        if config is None:
            raise RuntimeError(f"firm {firm_id} has no configured agent")
        state, opening = tracker_opening(config, name, cadence_days)
        if matter_description:
            state["matter_description"] = matter_description
        with self.db.firm(firm_id) as conn:
            contact = conn.execute(
                "SELECT id FROM contacts WHERE phone = %s LIMIT 1", (phone,)
            ).fetchone()
            contact_id = (
                contact["id"]
                if contact
                else conn.execute(
                    "INSERT INTO contacts (firm_id, name, phone) VALUES (%s, %s, %s) RETURNING id",
                    (firm_id, name, phone),
                ).fetchone()["id"]
            )
            existing = conn.execute(
                "SELECT id FROM threads WHERE channel = 'sms' AND address = %s AND status = 'open'",
                (phone,),
            ).fetchone()
            if existing:
                # An open intake thread becomes the tracker thread — same
                # conversation from the client's point of view.
                thread_id = str(existing["id"])
                conn.execute(
                    "UPDATE threads SET goal = 'treatment_tracker', state = %s, updated_at = now()"
                    " WHERE id = %s",
                    (json.dumps(state), thread_id),
                )
            else:
                thread_id = str(
                    conn.execute(
                        "INSERT INTO threads (firm_id, channel, address, contact_id, goal, state)"
                        " VALUES (%s, 'sms', %s, %s, 'treatment_tracker', %s) RETURNING id",
                        (firm_id, phone, contact_id, json.dumps(state)),
                    ).fetchone()["id"]
                )
            self._deliver(config, "sms", phone, opening)
            self._record_outbound(conn, firm_id, thread_id, "sms", opening)
            checkin_at = next_allowed_time(phone, config.timezone, now + timedelta(days=cadence_days))
            self._schedule_followup(conn, firm_id, thread_id, "tracker.checkin", checkin_at)
            platform_events.emit(
                conn,
                firm_id,
                "thread.started",
                {"thread_id": thread_id, "channel": "sms", "goal": "treatment_tracker"},
            )
        return thread_id

    # --- inbound ---

    def handle_inbound(
        self, firm_id: str, *, channel: str, address: str, body: str, now: datetime | None = None
    ) -> dict:
        """Advance the open thread for this address by one turn (creating a
        fresh intake thread when a new number texts in cold)."""
        now = now or _utcnow()
        config = self._config(firm_id)
        if config is None:
            raise RuntimeError(f"firm {firm_id} has no configured agent")
        with self.db.firm(firm_id) as conn:
            thread = conn.execute(
                "SELECT id, goal, state, contact_id, lead_id FROM threads"
                " WHERE channel = %s AND address = %s AND status = 'open'",
                (channel, address),
            ).fetchone()
            if thread is None:
                # Cold inbound: same receptionist behavior as an inbound call —
                # start intake. Texting in first is express consent to reply.
                state, opening = intake_opening(config, None, channel)
                thread_id = str(
                    conn.execute(
                        "INSERT INTO threads (firm_id, channel, address, goal, state)"
                        " VALUES (%s, %s, %s, 'intake', %s) RETURNING id",
                        (firm_id, channel, address, json.dumps(state)),
                    ).fetchone()["id"]
                )
                conn.execute(
                    "INSERT INTO messages (firm_id, channel, thread_id, direction, body)"
                    " VALUES (%s, %s, %s, 'in', %s)",
                    (firm_id, channel, thread_id, body),
                )
                conn.execute("UPDATE threads SET last_inbound_at = now() WHERE id = %s", (thread_id,))
                self._deliver(config, channel, address, opening)
                self._record_outbound(conn, firm_id, thread_id, channel, opening)
                platform_events.emit(
                    conn, firm_id, "thread.started",
                    {"thread_id": thread_id, "channel": channel, "goal": "intake", "lead_id": None},
                )
                return {"thread_id": thread_id, "reply": opening, "closed_reason": None}

            thread_id = str(thread["id"])
            conn.execute(
                "INSERT INTO messages (firm_id, channel, thread_id, direction, body)"
                " VALUES (%s, %s, %s, 'in', %s)",
                (firm_id, channel, thread_id, body),
            )
            conn.execute(
                "UPDATE threads SET last_inbound_at = now(), updated_at = now() WHERE id = %s",
                (thread_id,),
            )
            # A reply disarms any pending no-reply nudge.
            self._cancel_followups(conn, thread_id, "chaser.nudge")

            contact_name = None
            if thread["contact_id"]:
                row = conn.execute(
                    "SELECT name FROM contacts WHERE id = %s", (thread["contact_id"],)
                ).fetchone()
                contact_name = row["name"] if row else None

            if thread["goal"] == "treatment_tracker":
                result = advance_tracker(config, thread["state"], body)
            else:
                result = advance_intake(
                    config, thread["state"], body, now=now, contact_name=contact_name
                )

            self._execute_actions(conn, firm_id, thread, result, config, now, contact_name)
            conn.execute(
                "UPDATE threads SET state = %s, updated_at = now() WHERE id = %s",
                (json.dumps(result.state), thread_id),
            )
            if result.reply:
                self._deliver(config, channel, address, result.reply)
                self._record_outbound(conn, firm_id, thread_id, channel, result.reply)
            if result.close_reason:
                self._close_thread(conn, firm_id, thread_id, result.close_reason)
        return {"thread_id": thread_id, "reply": result.reply, "closed_reason": result.close_reason}

    # --- actions ---

    def _execute_actions(
        self,
        conn,
        firm_id: str,
        thread,
        result: BrainResult,
        config: AgentConfig,
        now: datetime,
        contact_name: str | None,
    ) -> None:
        thread_id = str(thread["id"])
        address = conn.execute("SELECT address, channel FROM threads WHERE id = %s", (thread_id,)).fetchone()
        for action in result.actions:
            if action.kind == "qualify":
                payload = dict(action.data)
                lead_id = thread["lead_id"]
                if lead_id:
                    conn.execute(
                        "UPDATE leads SET status = %s, qualification = %s WHERE id = %s",
                        (payload["decision"], json.dumps(payload), lead_id),
                    )
                else:
                    source = "sms" if address["channel"] == "sms" else "email"
                    lead_id = conn.execute(
                        "INSERT INTO leads (firm_id, source, contact_id, status, qualification, practice_area)"
                        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                        (
                            firm_id,
                            source,
                            thread["contact_id"],
                            payload["decision"],
                            json.dumps(payload),
                            config.script.practice_area,
                        ),
                    ).fetchone()["id"]
                    conn.execute(
                        "UPDATE threads SET lead_id = %s WHERE id = %s", (lead_id, thread_id)
                    )
                platform_events.emit(
                    conn,
                    firm_id,
                    "lead.qualified",
                    {"lead_id": str(lead_id), "thread_id": thread_id, **payload},
                )
            elif action.kind == "book":
                phone = address["address"] if address["channel"] == "sms" else ""
                key = f"thread:{thread_id}:consult"
                existing = conn.execute(
                    "SELECT id FROM consults WHERE idempotency_key = %s", (key,)
                ).fetchone()
                if existing:
                    continue  # a retried turn must never double-book
                consult = conn.execute(
                    "INSERT INTO consults (firm_id, lead_id, name, phone, slot_at, idempotency_key)"
                    " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        firm_id,
                        thread["lead_id"],
                        contact_name or "Web lead",
                        phone,
                        datetime.fromisoformat(action.data["slot_iso"]),
                        key,
                    ),
                ).fetchone()
                platform_events.emit(
                    conn,
                    firm_id,
                    "consult.booked",
                    {
                        "consult_id": str(consult["id"]),
                        "thread_id": thread_id,
                        "name": contact_name or "Web lead",
                        "phone": phone,
                        "slot_iso": action.data["slot_iso"],
                    },
                )
            elif action.kind == "take_message":
                platform_events.emit(
                    conn,
                    firm_id,
                    "message.taken",
                    {
                        "thread_id": thread_id,
                        "caller_name": action.data.get("caller_name"),
                        "phone": address["address"],
                        "body": action.data.get("body", ""),
                    },
                )
            elif action.kind == "tracker_update":
                state = result.state
                platform_events.emit(
                    conn,
                    firm_id,
                    "tracker.update",
                    {
                        "thread_id": thread_id,
                        "name": contact_name,
                        "phone": address["address"],
                        "kind": action.data["kind"],
                        "note": action.data.get("note", ""),
                        "matter_description": state.get("matter_description"),
                    },
                )
            elif action.kind == "schedule_checkin":
                cadence = int(action.data.get("cadence_days", DEFAULT_TRACKER_CADENCE_DAYS))
                due = next_allowed_time(
                    address["address"], config.timezone, now + timedelta(days=cadence)
                )
                self._schedule_followup(conn, firm_id, thread_id, "tracker.checkin", due)

    # --- scheduled follow-ups (claimed and dispatched by the worker) ---

    def run_followup(self, firm_id: str, followup: dict, now: datetime | None = None) -> str:
        """Execute one due followup. Returns a short outcome string (logged
        and counted by the worker)."""
        now = now or _utcnow()
        config = self._config(firm_id)
        if config is None:
            return "skipped:no_config"
        ftype = followup["type"]
        payload = followup.get("payload") or {}

        if ftype == "chaser.start":
            self.start_intake_thread(
                firm_id,
                channel=payload.get("channel", "sms"),
                address=payload["address"],
                contact_id=payload.get("contact_id"),
                lead_id=payload.get("lead_id"),
                name=payload.get("name"),
                source=payload.get("source", "web"),
                now=now,
            )
            return "chaser_started"

        thread_id = str(followup["thread_id"]) if followup.get("thread_id") else None
        if thread_id is None:
            return "skipped:no_thread"
        with self.db.firm(firm_id) as conn:
            thread = conn.execute(
                "SELECT id, channel, address, status, state, last_inbound_at, contact_id"
                " FROM threads WHERE id = %s",
                (thread_id,),
            ).fetchone()
            if thread is None or thread["status"] != "open":
                return "skipped:thread_closed"

            if ftype == "chaser.nudge":
                # Quiet hours can drift between scheduling and execution
                # (deferred starts, retries) — re-check at send time.
                if thread["channel"] == "sms":
                    allowed_at = next_allowed_time(thread["address"], config.timezone, now)
                    if allowed_at > now:
                        self._schedule_followup(conn, firm_id, thread_id, "chaser.nudge", allowed_at)
                        return "rescheduled:quiet_hours"
                state = json.loads(json.dumps(thread["state"]))
                nudges = int(state.get("nudges", 0))
                if nudges >= MAX_NUDGES:
                    self._close_thread(conn, firm_id, thread_id, "unresponsive")
                    return "closed:unresponsive"
                state["nudges"] = nudges + 1
                nudge = (
                    f"Hi, just checking in from {config.firm_name} — still happy to help "
                    "with your case whenever you're ready. Reply anytime."
                )
                self._deliver(config, thread["channel"], thread["address"], nudge)
                self._record_outbound(conn, firm_id, thread_id, thread["channel"], nudge)
                conn.execute(
                    "UPDATE threads SET state = %s WHERE id = %s", (json.dumps(state), thread_id)
                )
                next_nudge = now + timedelta(hours=24)
                if thread["channel"] == "sms":
                    next_nudge = max(next_nudge, next_allowed_time(thread["address"], config.timezone, next_nudge))
                self._schedule_followup(conn, firm_id, thread_id, "chaser.nudge", next_nudge)
                return "nudged"

            if ftype == "tracker.checkin":
                contact_name = None
                if thread["contact_id"]:
                    row = conn.execute(
                        "SELECT name FROM contacts WHERE id = %s", (thread["contact_id"],)
                    ).fetchone()
                    contact_name = row["name"] if row else None
                message = tracker_checkin_message(config, contact_name)
                self._deliver(config, thread["channel"], thread["address"], message)
                self._record_outbound(conn, firm_id, thread_id, thread["channel"], message)
                return "checkin_sent"

        return f"skipped:unknown_type:{ftype}"
