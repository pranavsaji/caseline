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
    WorkerOptions,
    cli,
    function_tool,
    get_job_context,
    metrics,
)
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from agent import providers
from agent.backend_client import BackendClient
from agent.latency import TurnLatencyTracker, TurnSample
from api.orchestration.guardrails import GuardrailScreen, StreamGuard

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


CLOSING_INSTRUCTION = (
    "ENDING THE CALL: when the caller confirms they have nothing more, wrap up "
    "in this order — make sure you've called write_to_cms, give a short warm "
    "goodbye (one sentence), and then call end_call to hang up. Do not stay on "
    "the line after saying goodbye, and never call end_call before you've said "
    "it."
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
    ):
        config = config or {}
        instructions = config.get("instructions") or DEFAULT_INSTRUCTIONS
        # The model has no inherent sense of "now" and will otherwise guess the
        # year (it once stamped a same-day accident as 2024, which tripped the
        # statute-of-limitations gate and wrongly declined the lead). Anchor it
        # to the real current date in the firm's timezone so it can resolve
        # "today" / "a few hours ago" / "last week" into a correct ISO date.
        instructions = f"{instructions}\n\n{_current_time_line(config.get('timezone'))}"
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
        # Time only the guardrail's own work (regex screen per chunk), not the
        # LLM wait, so guardrail_ms reflects the overhead the safety pass adds.
        guard_secs = 0.0

        def _feed(text: str):
            nonlocal guard_secs
            t0 = time.perf_counter()
            out = guard.feed(text)
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
        remaining = guard.flush()
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
    async def schedule_consult(self, name: str, phone: str, slot_iso: str) -> str:
        """Book a consultation for a qualified lead.

        Args:
            name: Caller's full name.
            phone: Caller's phone number.
            slot_iso: Chosen consultation slot as an ISO 8601 datetime.
        """
        result = await self._backend.schedule_consult(
            name, phone, slot_iso, call_id=self._call_id
        )
        logger.info("schedule_consult -> %s", result)
        return result["status"]

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
        if not self._backend.v1:
            return "sms unavailable"
        result = await self._backend.send_sms(self._call_id, to, body)
        logger.info("send_sms -> %s", result)
        return result["status"]

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
    async def end_call(self) -> str:
        """Hang up and end the call. Call this once the conversation is truly
        finished — after you have written to the CMS, said a brief goodbye, and
        the caller has nothing more. Say your closing line BEFORE calling this;
        it waits for that line to finish playing, then disconnects both sides."""
        logger.info("end_call requested for %s", self._call_id)
        # Let the closing line finish before dropping the connection, otherwise
        # the caller hears the goodbye get cut off.
        try:
            speech = self.session.current_speech
            if speech is not None:
                await speech.wait_for_playout()
        except Exception:  # never let a teardown detail keep the call alive
            logger.debug("end_call: could not await final speech", exc_info=True)
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


def prewarm(proc: JobProcess) -> None:
    # Pre-load VAD so it never costs a caller their first-turn latency.
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    call_id = ctx.room.name
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
    greeting = ((config or {}).get("script") or {}).get("greeting") or DEFAULT_GREETING

    # Phase 4: selective S2S is evidence-gated (agent/s2s.py). Until a live
    # benchmark verdict justifies it, the greeting rides the cascaded
    # pipeline like every other turn — this logs which path is serving.
    from agent.s2s import plan_greeting

    greeting_plan = plan_greeting()
    logger.info("greeting mode: %s (%s)", greeting_plan.mode, greeting_plan.reason)

    # Phase 2: each stage is a failover stack (primary + optional fallbacks
    # behind a health-check driven FallbackAdapter — mid-call cutover).
    stt_stack = providers.build_stt()
    llm_stack = providers.build_llm()
    tts_stack = providers.build_tts(voice_id)

    session = AgentSession(
        stt=stt_stack.adapter,
        llm=llm_stack.adapter,
        tts=tts_stack.adapter,
        vad=ctx.proc.userdata["vad"],
        turn_detection=MultilingualModel(),
        preemptive_generation=True,  # fire LLM on STT partials
        min_endpointing_delay=0.4,  # tuned turn-taking (architecture doc §9)
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

    await session.start(
        agent=IntakeAgent(
            backend=backend,
            call_id=call_id,
            config=config,
            on_guardrail=lambda sid, ms: _report(tracker.on_guardrail(sid, ms)),
        ),
        room=ctx.room,
    )
    await session.generate_reply(instructions=greeting)


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
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
