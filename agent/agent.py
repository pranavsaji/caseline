"""Caseline voice worker: LiveKit Agents intake receptionist.

Pipeline (cascading, per architecture doc §3.2):
  Deepgram Nova-3 STT -> Claude Haiku 4.5 -> Cartesia Sonic-3 TTS
  Silero VAD + multilingual semantic turn detector
  preemptive_generation=True, min_endpointing_delay=0.4s

Phase 1: instructions, qualification rules, routing, and guardrails come
from the firm's agent config (fetched from the backend at call start, cached
server-side in Redis). A regex guardrail screen sits between LLM output and
TTS. If the backend or config is unreachable the worker still answers, on
safe Phase 0 defaults — config can never take down a call.

Run (backend must be up on CASELINE_BACKEND_URL):
  python -m agent.agent console   # local mic/speaker smoke test, no telephony
  python -m agent.agent dev       # connect to LiveKit, take real calls
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
    get_job_context,
    metrics,
)
from livekit.plugins import silero
from livekit.plugins.turn_detector.english import EnglishModel

from agent import providers
from agent.backend_client import BackendClient
from agent.latency import TurnLatencyTracker, TurnSample
from api.orchestration.guardrails import FunctionCallStripper, GuardrailScreen, StreamGuard

load_dotenv()
logger = logging.getLogger("caseline.agent")

# Phase 0 fallback: used when no firm config is available so a backend
# outage degrades to the generic script instead of dead air.
DEFAULT_INSTRUCTIONS = (
    "You are Caseline, the AI intake receptionist for a personal injury law firm. "
    "Warm, concise, human — short spoken sentences, no lists, no jargon. "
    "Greet the caller, find out if they have a potential injury case, and collect: "
    "incident date, injury type, whether they are receiving treatment, and insurance "
    "status. Convert any date the caller gives you to ISO format (YYYY-MM-DD) before "
    "calling tools. You do NOT give legal advice, quote fees, or predict outcomes — "
    "if asked, say an attorney will cover that in the consultation. "
    "Once you have the four facts, call qualify_lead. If qualified, offer to book a "
    "consultation and call schedule_consult with the caller's name, phone number, and "
    "chosen slot. If the decision is refer_out or decline, be kind, explain the firm "
    "may not be the right fit, and take a message. If the caller is an insurance "
    "adjuster, existing client, or spam, be polite and take a message. "
    "Before ending any call, call write_to_cms with a short summary and the structured "
    "facts you collected. Never invent facts the caller did not state."
)
DEFAULT_DEFLECTION = (
    "That's exactly the kind of question our attorneys will answer in your "
    "consultation — I can't speak to it myself."
)
DEFAULT_GREETING = (
    "Greet the caller warmly, say you're with the firm's intake team, "
    "and ask how you can help."
)


def _greeting_text(config: dict | None) -> str:
    """A fixed opening line spoken directly via TTS (no LLM call), so the caller
    hears a greeting immediately. Includes the firm name, the AI disclosure, and
    — when required by config or consent policy — the recording disclosure."""
    config = config or {}
    firm = config.get("firm_name") or "our office"
    agent = config.get("agent_name") or "Caseline"
    script = config.get("script") or {}
    consent = config.get("consent") or {}
    disclose = script.get("recording_disclosure", True) or consent.get("disclosure_required")
    recording = " Just so you know, this call may be recorded for quality purposes." if disclose else ""
    return (
        f"Thanks for calling {firm}. This is {agent}, the AI intake assistant."
        f"{recording} How can I help you today?"
    )


def _outbound_greeting_text(config: dict | None) -> str:
    """Opening line for calls WE place (dashboard 'Place a call' or the lead
    chaser). The agent initiated this call, so it must NOT say 'thanks for
    calling' — it identifies itself, says why it's reaching out, and politely
    checks it's a good time."""
    config = config or {}
    firm = config.get("firm_name") or "our office"
    agent = config.get("agent_name") or "Caseline"
    script = config.get("script") or {}
    consent = config.get("consent") or {}
    disclose = script.get("recording_disclosure", True) or consent.get("disclosure_required")
    recording = " Just so you know, this call may be recorded for quality purposes." if disclose else ""
    return (
        f"Hi, this is {agent}, the AI assistant with {firm}. I'm reaching out to "
        f"follow up about your injury inquiry.{recording} Is now an okay time to talk?"
    )


OUTBOUND_INSTRUCTION = (
    "THIS IS AN OUTBOUND CALL: YOU placed this call — you are calling the person, "
    "they did NOT call you. Never say 'thanks for calling' and never claim or "
    "imply that they called you; if they ask why you're calling, explain warmly "
    "that you're following up from the firm about their potential injury case. "
    "Since you're the one interrupting their day, be especially polite: identify "
    "yourself and the firm, confirm it's a good time, and if it isn't, apologize "
    "and offer to call back at a better time or take a quick note."
)


STYLE_INSTRUCTION = (
    "CONVERSATION STYLE: sound like a warm, genuinely polite, competent human "
    "receptionist, not a form. Always be courteous — greet them kindly, say "
    "'please' and 'thank you' naturally, thank them for details they share, and "
    "never sound curt, blunt, robotic, or impatient. Speak in short, natural "
    "spoken sentences. Ask ONE thing at a time and wait for the answer — never "
    "stack multiple questions in one breath. Do not re-confirm or re-ask "
    "something the caller already told you; acknowledge it and move on. Mirror a "
    "detail back only once, briefly, if you truly need to verify it. Lead with "
    "empathy — react like a kind person would ('Oh no, I'm so sorry that "
    "happened') before getting to the next question, and be extra gentle and "
    "patient if they're in pain, upset, or confused. Never read internal fields, "
    "tool names, JSON, IDs, or system details aloud. Keep the call moving toward: "
    "understand the injury, qualify, and (if a fit) book a real consultation."
)

QUALIFYING_INSTRUCTION = (
    "COLLECTING THE FACTS: qualify_lead needs four facts — incident date, injury "
    "type, whether they're currently in treatment, and insurance status. Do NOT "
    "call qualify_lead until the caller has actually TOLD you all four. If you "
    "haven't yet asked whether they're getting treatment, or about insurance, "
    "ASK — one question at a time — and wait for the answer. Never assume, "
    "default, or guess a fact the caller didn't state (especially the treatment "
    "and insurance yes/no): a guessed 'no' can wrongly decline or mis-handle a "
    "real case. For the injury, get what actually got hurt (e.g. 'my back', "
    "'broke my wrist'), not a vague 'injured badly'. If the caller is upset, "
    "rambling, or gives things out of order, stay patient and keep gently "
    "gathering the missing facts — don't give up and wrap up the call early. "
    "After you qualify a good case, do NOT jump straight to goodbye: offer the "
    "consultation and try to book it before ending."
)

def _sms_enabled() -> bool:
    """Mirrors `api.messaging.sms_outbound_enabled` — the agent is a separate
    service with its own env, so it reads the same flag independently rather
    than importing the API package."""
    return os.getenv("CASELINE_SMS_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


SCHEDULING_INSTRUCTION = (
    "SCHEDULING: you do NOT know the firm's calendar from memory. When a qualified "
    "caller wants to book, FIRST call get_available_slots, then offer two or three "
    "of those real times in natural language (e.g. 'I have Monday the 20th at 10 "
    "or 2, or Tuesday at 11'). Only book a time the tool returned. If the caller "
    "asks for a time that isn't open, say it's taken and offer the nearest real "
    "options. You need the caller's name and phone number before booking."
)

# Appended only when outbound SMS is actually available. Offering a text the
# carrier will reject makes the agent apologize mid-booking, which reads as a
# broken product — so when SMS is off we confirm verbally instead.
SMS_ENABLED_INSTRUCTION = (
    "CONFIRMATION TEXT: after a successful booking you may offer an SMS "
    "confirmation — but only claim the text was sent if send_sms reports "
    "success; if it didn't go through, say so and offer to read the details "
    "instead."
)

SMS_DISABLED_INSTRUCTION = (
    "CONFIRMATION TEXT: text messaging is NOT available right now. Never offer "
    "to send a text, and never say you have sent or will send one. Confirm the "
    "booking out loud instead: repeat the day and time, give the office address "
    "clearly, and tell them the office will follow up to confirm. Do not "
    "mention that texting is unavailable or broken — simply confirm verbally."
)

CLOSING_INSTRUCTION = (
    "ENDING THE CALL: when the caller confirms they have nothing more, wrap up "
    "in this order — first make sure you've called write_to_cms, then call "
    "end_call. Put your warm one-sentence goodbye in end_call's `farewell` "
    "argument (thank them for calling, and mention the booked consult if there "
    "is one) — end_call speaks that goodbye and waits for it to finish before "
    "hanging up. Do NOT say the goodbye as a separate message and then call "
    "end_call; that would make the caller hear it twice. Just call end_call "
    "with the farewell."
)


def _current_time_line(timezone: str | None) -> str:
    """A system-prompt line anchoring the model to the real current date/time
    in the firm's timezone, so relative dates ("today", "a few hours ago")
    resolve to a correct ISO date instead of a hallucinated year."""
    try:
        tz = ZoneInfo(timezone) if timezone else ZoneInfo("America/Chicago")
    except Exception:  # unknown tz string — fall back rather than crash the call
        tz = ZoneInfo("America/Chicago")
    now = datetime.now(tz)
    stamp = now.strftime("%A, %B %d, %Y, %I:%M %p").replace(" 0", " ")
    return (
        f"CURRENT DATE AND TIME: it is {stamp} ({now.tzname()}). "
        "Use this as the source of truth for the current date. When the caller "
        'refers to a time relative to now ("today", "yesterday", "a few hours '
        'ago", "last week", "a couple months back"), compute the absolute date '
        "from it and pass ISO format (YYYY-MM-DD) to tools. Never guess the year."
    )


class IntakeAgent(Agent):
    def __init__(
        self,
        backend: BackendClient,
        call_id: str,
        config: dict | None,
        on_guardrail: "Callable[[str, float], None] | None" = None,
        outbound: bool = False,
    ):
        config = config or {}
        instructions = config.get("instructions") or DEFAULT_INSTRUCTIONS
        # The model has no inherent sense of "now" and will otherwise guess the
        # year (it once stamped a same-day accident as 2024, which tripped the
        # statute-of-limitations gate and wrongly declined the lead). Anchor it
        # to the real current date in the firm's timezone so it can resolve
        # "today" / "a few hours ago" / "last week" into a correct ISO date.
        instructions = f"{instructions}\n\n{_current_time_line(config.get('timezone'))}"
        instructions = f"{instructions}\n\n{STYLE_INSTRUCTION}"
        # On outbound calls the agent placed the call — tell it so it never claims
        # the caller rang in ("thanks for calling" / "you called me").
        if outbound:
            instructions = f"{instructions}\n\n{OUTBOUND_INSTRUCTION}"
        instructions = f"{instructions}\n\n{QUALIFYING_INSTRUCTION}"
        instructions = f"{instructions}\n\n{SCHEDULING_INSTRUCTION}"
        sms_rule = SMS_ENABLED_INSTRUCTION if _sms_enabled() else SMS_DISABLED_INSTRUCTION
        instructions = f"{instructions}\n\n{sms_rule}"
        instructions = f"{instructions}\n\n{CLOSING_INSTRUCTION}"
        super().__init__(instructions=instructions)
        self._backend = backend
        self._call_id = call_id
        self._config = config
        guardrails = config.get("guardrails") or {}
        self._screen = GuardrailScreen(
            extra_blocked_patterns=guardrails.get("extra_blocked_patterns", [])
        )
        self._deflection = guardrails.get("deflection_line") or DEFAULT_DEFLECTION
        self._on_guardrail = on_guardrail

    # --- guardrail pass between LLM and TTS (plan.md Workstream B) ---

    async def llm_node(self, chat_ctx, tools, model_settings):
        guard = StreamGuard(self._screen, self._deflection)
        deflected = False
        last_chunk = None
        # Strip any tool-call syntax a model emits as text (llama does this)
        # before it can be spoken/shown, then run the content guardrail.
        stripper = FunctionCallStripper()
        # Time only the safety pass's own work (strip + regex screen per chunk),
        # not the LLM wait, so guardrail_ms reflects the overhead it adds.
        guard_secs = 0.0

        def _feed(text: str):
            nonlocal guard_secs
            t0 = time.perf_counter()
            clean = stripper.feed(text)
            out = guard.feed(clean) if clean else None
            guard_secs += time.perf_counter() - t0
            return out

        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            if isinstance(chunk, str):
                released = None if guard.tripped else _feed(chunk)
                if guard.tripped and not deflected:
                    deflected = True
                    yield ((released + " ") if released else "") + guard.deflection_line
                elif released:
                    yield released
                continue
            last_chunk = chunk
            delta = getattr(chunk, "delta", None)
            content = getattr(delta, "content", None) if delta is not None else None
            if content is None:
                yield chunk  # tool calls / usage chunks pass through untouched
                continue
            if guard.tripped:
                delta.content = None
                if getattr(delta, "tool_calls", None):
                    yield chunk
                continue
            released = _feed(content)
            if guard.tripped and not deflected:
                deflected = True
                logger.warning(
                    "guardrail tripped on call %s: %s (%s)",
                    self._call_id,
                    guard.tripped.category,
                    guard.tripped.matched,
                )
                delta.content = ((released + " ") if released else "") + guard.deflection_line
                yield chunk
            elif released:
                delta.content = released
                yield chunk
            elif getattr(delta, "tool_calls", None):
                delta.content = None
                yield chunk
        t0 = time.perf_counter()
        # Drain the stripper's tail into the guard, then flush the guard.
        stripped_tail = stripper.flush()
        released = guard.feed(stripped_tail) if stripped_tail else None
        flushed = guard.flush()
        parts = [p for p in (released, flushed) if p]
        remaining = " ".join(parts) if parts else None
        guard_secs += time.perf_counter() - t0
        if remaining:
            if last_chunk is not None and getattr(last_chunk, "delta", None) is not None:
                final = last_chunk.model_copy(deep=True)
                final.delta.content = remaining
                final.delta.tool_calls = []
                yield final
            else:
                yield remaining
        elif guard.tripped and not deflected:
            yield guard.deflection_line

        # Attribute this turn's guardrail overhead to its speech_id so it lands
        # in the same per-turn latency sample as EOU/LLM/TTS.
        if self._on_guardrail is not None:
            try:
                speech = self.session.current_speech
                if speech is not None:
                    self._on_guardrail(speech.id, guard_secs * 1000)
            except Exception:  # instrumentation must never break a turn
                logger.debug("guardrail latency report failed", exc_info=True)

    # --- typed tools: the LLM selects, the backend executes ---

    @function_tool
    async def lookup_caller(self, phone: str) -> str:
        """Check whether a caller is already known to the firm before treating
        them as a brand-new lead.

        Args:
            phone: Caller's phone number in E.164 or as spoken.
        """
        if not self._backend.v1:
            return "unknown caller (lookup unavailable)"
        result = await self._backend.lookup_caller(phone)
        logger.info("lookup_caller -> %s", result)
        if not result.get("known"):
            return "new caller, not in our records"
        return (
            f"known caller: {result['name']}, last lead status: "
            f"{result.get('last_lead_status') or 'none'}"
        )

    @function_tool
    async def qualify_lead(
        self, incident_date: str, injury_type: str, in_treatment: bool, has_insurance: bool
    ) -> str:
        """Qualify a potential personal-injury lead once all four facts are known.

        Args:
            incident_date: Date of the incident in ISO format (YYYY-MM-DD).
            injury_type: Short description of the injury (e.g. "whiplash", "broken arm", "minor").
            in_treatment: Whether the caller is currently receiving medical treatment.
            has_insurance: Whether any insurance (theirs or the other party's) is involved.
        """
        result = await self._backend.qualify_lead(
            incident_date, injury_type, in_treatment, has_insurance, call_id=self._call_id
        )
        logger.info("qualify_lead -> %s", result)
        return result["decision"]

    @function_tool
    async def get_available_slots(self) -> str:
        """Get the firm's real open consultation times. Call this BEFORE offering
        the caller any appointment — offer only these slots, and if the time they
        want isn't listed, offer the nearest available ones instead. Never invent
        a time."""
        if not self._backend.v1:
            return "scheduling is unavailable right now; take a message with a good callback time instead"
        result = await self._backend.get_available_slots()
        slots = result.get("slots", [])
        logger.info("get_available_slots -> %d slots", len(slots))
        if not slots:
            return "no open consultation slots in the next two weeks; offer to take a message so the office can call back"
        labels = [s["label"] for s in slots]
        # Give the model both the spoken labels and the exact ISO to book with.
        pairs = "; ".join(f"{s['label']} ({s['slot_iso']})" for s in slots)
        return (
            "Available consultation times — offer 2 or 3 of these in natural language and, "
            "once the caller picks one, call schedule_consult with its exact slot_iso: " + pairs
        )

    @function_tool
    async def schedule_consult(self, name: str, phone: str, slot_iso: str) -> str:
        """Book a consultation for a qualified lead. Only book a slot returned by
        get_available_slots.

        Args:
            name: Caller's full name.
            phone: Caller's phone number.
            slot_iso: Chosen consultation slot as an ISO 8601 datetime — must be
                one of the slot_iso values from get_available_slots.
        """
        result = await self._backend.schedule_consult(
            name, phone, slot_iso, call_id=self._call_id
        )
        logger.info("schedule_consult -> %s", result)
        if result.get("status") == "unavailable":
            alts = result.get("alternatives") or []
            if alts:
                opts = "; ".join(f"{a['label']} ({a['slot_iso']})" for a in alts[:3])
                return (
                    "That time isn't available. Apologize briefly and offer these instead, "
                    "then call schedule_consult again with the chosen slot_iso: " + opts
                )
            return "That time isn't available and nothing else is open soon; offer to take a message."
        return "booked"

    @function_tool
    async def transfer_to_human(self, reason: str) -> str:
        """Transfer the caller to a human at the firm when they ask for a person,
        are upset, or the situation needs judgment you don't have.

        Args:
            reason: One short sentence on why the caller needs a human.
        """
        if not self._backend.v1:
            return "transfer unavailable; offer to take a detailed message instead"
        result = await self._backend.transfer_to_human(self._call_id, reason)
        logger.info("transfer_to_human -> %s", result)
        if result["action"] == "transfer" and result.get("target"):
            asyncio.create_task(_try_sip_transfer(self._call_id, result["target"]))
            return "transferring the caller now — tell them you're connecting them"
        return "no one is available right now; apologize and take a detailed message instead"

    @function_tool
    async def send_sms(self, to: str, body: str) -> str:
        """Send the caller a short SMS (e.g. consult confirmation with the firm's
        address). Only with the caller's permission.

        Args:
            to: Destination phone number.
            body: Message text, one or two sentences.
        """
        if not self._backend.v1 or not _sms_enabled():
            # Texting is switched off — steer the agent to confirm verbally
            # rather than surface a technical failure to the caller.
            return (
                "texting is not available; do NOT mention texting — instead confirm the "
                "appointment out loud with the day, time, and office address"
            )
        result = await self._backend.send_sms(self._call_id, to, body)
        logger.info("send_sms -> %s", result)
        if result.get("status") != "sent":
            # Don't claim it sent. Tell the caller the text didn't go through and
            # offer the info another way (read the address, or they can call in).
            return (
                "the text could not be sent to that number; let the caller know and offer "
                "to read them the details or have the office follow up"
            )
        return "sent"

    @function_tool
    async def take_message(self, caller_name: str, phone: str, message: str) -> str:
        """Take a message for the firm (adjusters, existing clients, declined
        leads, after-hours transfer requests).

        Args:
            caller_name: The caller's name.
            phone: Callback number.
            message: The message content.
        """
        if not self._backend.v1:
            return "noted"
        result = await self._backend.take_message(self._call_id, caller_name, phone, message)
        logger.info("take_message -> %s", result)
        return result["status"]

    @function_tool
    async def write_to_cms(self, summary: str, structured: str) -> str:
        """Write the intake record to the firm's case management system. Call this
        once before the call ends.

        Args:
            summary: Two-to-three sentence summary of the call and its outcome.
            structured: A JSON object (as a string) of the structured facts
                collected — incident_date, injury_type, in_treatment,
                has_insurance, caller name/phone, decision, and consult slot if
                booked. Passed as a JSON string because a free-form object
                parameter produces a tool schema that strict function-calling
                providers (e.g. Groq) reject.
        """
        try:
            facts = json.loads(structured) if isinstance(structured, str) else structured
        except (json.JSONDecodeError, TypeError):
            # Model handed us something that isn't valid JSON — keep it rather
            # than dropping the record; the CMS layer stores it as-is.
            facts = {"raw": structured}
        result = await self._backend.write_to_cms(self._call_id, summary, facts)
        logger.info("write_to_cms -> %s", result)
        return result["status"]

    @function_tool
    async def end_call(
        self,
        context: RunContext,
        farewell: str = "Thanks so much for calling. Take care and feel better soon!",
    ) -> str:
        """Hang up and end the call once the conversation is truly finished —
        after you have written to the CMS and the caller has nothing more.

        Do NOT say your goodbye in a separate turn; pass it here as ``farewell``
        and this tool speaks it, waits for it to finish playing, and only then
        disconnects — so the caller always hears a warm sign-off instead of the
        line suddenly going dead.

        Args:
            farewell: A short, warm one-sentence goodbye that thanks the caller
                for calling (e.g. "Thanks for calling — we'll see you Monday at
                one, take care!"). Reference the booking if one was made.
        """
        logger.info("end_call requested for %s", self._call_id)
        # 1) If the model happened to speak anything in this same turn, let that
        #    finish first (RunContext.wait_for_playout is the supported way to
        #    await the tool's own turn without the circular-wait error).
        try:
            await context.wait_for_playout()
        except Exception:
            logger.debug("end_call: wait_for_playout failed", exc_info=True)
        # 2) Speak our guaranteed farewell and wait for it to fully play out.
        #    This covers the common case where the model calls end_call with no
        #    spoken goodbye at all — the reason calls were dropping silently.
        #    Non-interruptible so it can't be cut short before hangup.
        try:
            handle = self.session.say(farewell, allow_interruptions=False)
            await handle.wait_for_playout()
        except Exception:  # never let a teardown detail keep the call alive
            logger.debug("end_call: could not speak/await farewell", exc_info=True)
        # 3) wait_for_playout resolves when the server has pushed the audio, but
        #    the caller's client (browser WebRTC / SIP jitter buffer) still needs
        #    a beat to actually play the tail. Drain briefly so the goodbye isn't
        #    truncated by the room teardown below.
        try:
            await asyncio.sleep(0.75)
        except Exception:
            pass
        # Deleting the room disconnects every participant (caller + agent) and
        # triggers the job shutdown callback (transcript flush, CMS drain).
        try:
            get_job_context().delete_room()
        except Exception as exc:
            logger.warning("end_call: room delete failed: %s", exc)
        return "call ended"


async def _try_sip_transfer(room_name: str, target: str) -> None:
    """Best-effort live transfer via LiveKit SIP REFER. Failures are logged,
    never raised — the agent falls back to taking a message."""
    try:
        from livekit import api as lk_api

        async with lk_api.LiveKitAPI() as lk:
            participants = await lk.room.list_participants(
                lk_api.ListParticipantsRequest(room=room_name)
            )
            sip_participant = next(
                (p for p in participants.participants if str(p.kind) == "3" or "sip" in p.identity.lower()),
                None,
            )
            if sip_participant is None:
                logger.warning("no SIP participant in %s to transfer", room_name)
                return
            await lk.sip.transfer_sip_participant(
                lk_api.TransferSIPParticipantRequest(
                    room_name=room_name,
                    participant_identity=sip_participant.identity,
                    transfer_to=f"tel:{target}",
                    play_dialtone=True,
                )
            )
            logger.info("SIP transfer of %s to %s initiated", room_name, target)
    except Exception as exc:  # noqa: BLE001 — transfer failure must not kill the call
        logger.warning("SIP transfer failed for %s -> %s: %s", room_name, target, exc)


def _history_turns(session: AgentSession) -> list[dict]:
    turns: list[dict] = []
    try:
        for item in session.history.items:
            if getattr(item, "type", "") != "message":
                continue
            text = getattr(item, "text_content", None)
            if text:
                turns.append({"role": str(item.role), "text": text})
    except Exception as exc:  # noqa: BLE001 — transcript capture is best-effort
        logger.warning("failed to extract transcript: %s", exc)
    return turns


async def _warm_llm_cache(primary_llm: object, agent: "IntakeAgent") -> None:
    """Absorb the first-call cold cost on the PRIMARY LLM while the greeting plays,
    so the caller's first real turn is warm.

    The first turn is otherwise the slowest of the call: a fresh TCP+TLS connect
    plus the first ephemeral-cache WRITE of the large, stable (system prompt + all
    nine tool schemas) prefix. Measured cold, that first write runs several seconds
    — long enough that it can trip the FallbackAdapter's 5s per-attempt timeout,
    mark a healthy-but-slow primary UNAVAILABLE, and stall the caller ~16s before a
    fallback answers (observed on a live web call). Two fixes here:

      * Warm the PRIMARY INSTANCE directly, not through the FallbackAdapter — a
        slow warmup must not flip the adapter's health state and drop the primary
        for the caller's first real turn. (The primary's own httpx read timeout is
        generous, so a cold call completes instead of being killed at 5s.)
      * Drain each generation FULLY (not break-after-one-token) so the cache write
        actually lands and the connection is pooled before the caller speaks.

    The ~8s greeting (plus session.start) is otherwise idle, so by the caller's
    first sentence the real turn through the adapter is a warm cache hit (~1.5s
    TTFT, well under the 5s failover budget). Best-effort: any failure is ignored,
    a warmup problem must never affect the call."""
    try:
        from livekit.agents.llm import ChatContext

        ctx = ChatContext.empty()
        ctx.add_message(role="system", content=agent.instructions)
        ctx.add_message(role="user", content="hello")
        t0 = time.perf_counter()
        # First pass pays the cold connect + cache write; the second confirms the
        # warm read path. Drain both fully so the write completes before turn one.
        for _ in range(2):
            stream = primary_llm.chat(chat_ctx=ctx, tools=agent.tools)  # type: ignore[attr-defined]
            try:
                async for _chunk in stream:
                    pass
            finally:
                await stream.aclose()
        logger.info("llm cache warmup complete in %.0fms", (time.perf_counter() - t0) * 1000)
    except Exception:  # noqa: BLE001 — warmup is a latency optimization, not required
        logger.debug("llm cache warmup skipped", exc_info=True)


def prewarm(proc: JobProcess) -> None:
    # Pre-load VAD so it never costs a caller their first-turn latency.
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    call_id = ctx.room.name
    # Calls WE place get room names prefixed "outbound-" (dashboard dial:
    # "outbound-manual-…"; lead chaser: "outbound-<lead>"). Everything else is
    # someone reaching us (inbound SIP "call-…", web "web-manual-…").
    is_outbound = call_id.startswith("outbound")
    backend = BackendClient()
    tracker = TurnLatencyTracker(call_id=call_id)
    usage = metrics.UsageCollector()

    # Per-firm config (cached server-side); None -> safe Phase 0 defaults.
    # from_number (when telephony provides it) drives per-state consent.
    from_number = os.getenv("CASELINE_TEST_FROM_NUMBER")  # SIP attrs land here later
    config = await backend.get_agent_config(from_number=from_number)
    # Phase 4: voice_id may be a cloned per-firm voice (voice_profiles ->
    # agents.voice_id); the TTS stage doesn't care where the id came from.
    voice_id = (config or {}).get("voice_id") or os.getenv("CARTESIA_VOICE_ID") or None
    greeting = _outbound_greeting_text(config) if is_outbound else _greeting_text(config)

    # Phase 4: selective S2S is evidence-gated (agent/s2s.py). Until a live
    # benchmark verdict justifies it, the greeting rides the cascaded
    # pipeline like every other turn — this logs which path is serving.
    from agent.s2s import plan_greeting

    greeting_plan = plan_greeting()
    logger.info("greeting mode: %s (%s)", greeting_plan.mode, greeting_plan.reason)

    # Phase 2: each stage is a failover stack (primary + optional fallbacks
    # behind a health-check driven FallbackAdapter — mid-call cutover).
    # The firm's chosen LLM (Config Studio -> agents.llm_config) overrides the
    # worker's env default per call; empty falls back to CASELINE_LLM_PROVIDERS.
    llm_spec = ((config or {}).get("llm") or {}).get("providers") or None
    if llm_spec:
        logger.info("call %s using firm-selected LLM: %s", call_id, llm_spec)
    stt_stack = providers.build_stt()
    llm_stack = providers.build_llm(llm_spec)
    tts_stack = providers.build_tts(voice_id)

    session = AgentSession(
        stt=stt_stack.adapter,
        llm=llm_stack.adapter,
        tts=tts_stack.adapter,
        vad=ctx.proc.userdata["vad"],
        # English-only turn detector: the intake agent speaks and listens in
        # English (greeting, instructions, TTS language all "en"), so the lighter
        # English model does the same job as the multilingual one with a smaller,
        # faster inference on every end-of-utterance — shaving the EOU term of
        # turn latency without any behaviour change for these calls.
        turn_detection=EnglishModel(),
        preemptive_generation=True,  # fire LLM on STT partials
        min_endpointing_delay=0.4,  # tuned turn-taking (architecture doc §9)
        # Barge-in: the caller can talk over the agent and it stops immediately.
        # Enabled explicitly (not just relying on defaults) and tuned to trigger
        # quickly — 0.3s of speech is enough, and no minimum word count — so a
        # caller can cut the agent off mid-sentence the way they would a person.
        allow_interruptions=True,
        min_interruption_duration=0.3,
        min_interruption_words=0,
    )

    def _report(turn: TurnSample | None) -> None:
        if turn is None:
            return
        payload = {
            "call_id": call_id,
            "speech_id": turn.speech_id,
            "eou_delay_ms": turn.eou_delay_ms,
            "stt_ms": turn.stt_ms,
            "llm_ttft_ms": turn.llm_ttft_ms,
            "tts_ttfb_ms": turn.tts_ttfb_ms,
            "guardrail_ms": turn.guardrail_ms,
            "total_ms": turn.total_ms,
            # which providers are serving right now (failover-aware)
            "stt_provider": stt_stack.active_label(),
            "llm_provider": llm_stack.active_label(),
            "tts_provider": tts_stack.active_label(),
        }
        asyncio.create_task(backend.post_turn_metrics(payload))

    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent) -> None:
        usage.collect(ev.metrics)
        m = ev.metrics
        if isinstance(m, metrics.EOUMetrics):
            _report(tracker.on_eou(m.speech_id, m.end_of_utterance_delay, m.transcription_delay))
        elif isinstance(m, metrics.LLMMetrics):
            _report(tracker.on_llm(m.speech_id, m.ttft))
        elif isinstance(m, metrics.TTSMetrics):
            _report(tracker.on_tts(m.speech_id, m.ttfb))

    async def _shutdown() -> None:
        logger.info("call %s latency summary: %s", call_id, tracker.summary())
        logger.info("call %s usage: %s", call_id, usage.get_summary())
        await backend.post_transcript(call_id, _history_turns(session))
        await backend.aclose()

    ctx.add_shutdown_callback(_shutdown)

    intake = IntakeAgent(
        backend=backend,
        call_id=call_id,
        config=config,
        on_guardrail=lambda sid, ms: _report(tracker.on_guardrail(sid, ms)),
        outbound=is_outbound,
    )
    # Warm the primary LLM's connection + prompt cache as early as possible, so
    # the caller's first real turn is a warm cache hit (~1.5s TTFT) instead of a
    # cold write (several seconds) that can trip the 5s failover timeout and stall
    # the caller ~16s (observed). Kicked off BEFORE session.start so it overlaps
    # room connect AND the ~8s greeting for the biggest possible head start.
    warmup = asyncio.create_task(_warm_llm_cache(llm_stack.instances[0], intake))
    await session.start(agent=intake, room=ctx.room)
    # Speak a fixed opening line directly through TTS instead of asking the LLM
    # to generate one. generate_reply() runs a full Claude call (big system
    # prompt + all tools) before any audio, so the caller heard several seconds
    # of silence and talked over it. say() starts speaking almost immediately.
    await session.say(greeting, allow_interruptions=True)
    # Don't leave the warmup task dangling if the greeting finishes first.
    if not warmup.done():
        warmup.add_done_callback(lambda t: t.exception())


def _start_platform_health_server() -> None:
    """Hosted platforms (Railway) healthcheck the service's $PORT. The
    LiveKit worker's own health server stays on its default port (8081),
    so when $PORT is set we answer 200 there from a zero-dependency daemon
    thread — it can never interfere with the voice pipeline."""
    port = os.getenv("PORT")
    if not port:
        return
    import http.server
    import threading

    class _Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — http.server API
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "agent"}')

        def log_message(self, *args: object) -> None:  # keep logs clean
            pass

    server = http.server.ThreadingHTTPServer(("0.0.0.0", int(port)), _Health)
    threading.Thread(target=server.serve_forever, daemon=True, name="health").start()
    logger.info("platform health server listening on :%s", port)


if __name__ == "__main__":
    _start_platform_health_server()
    # Keep one warmed job process ready so a new call doesn't pay the
    # ~1-2s process-spawn cost before the agent can join and greet.
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            num_idle_processes=1,
        )
    )
