"""Caseline Phase 0 voice worker: LiveKit Agents intake receptionist.

Pipeline (cascading, per architecture doc §3.2):
  Deepgram Nova-3 STT -> Claude Haiku 4.5 -> Cartesia Sonic-3 TTS
  Silero VAD + multilingual semantic turn detector
  preemptive_generation=True, min_endpointing_delay=0.4s

Run (backend must be up on CASELINE_BACKEND_URL):
  python -m agent.agent console   # local mic/speaker smoke test, no telephony
  python -m agent.agent dev       # connect to LiveKit, take real calls
"""

from __future__ import annotations

import asyncio
import logging
import os

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
    metrics,
)
from livekit.plugins import anthropic, cartesia, deepgram, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from agent.backend_client import BackendClient
from agent.latency import TurnLatencyTracker, TurnSample

load_dotenv()
logger = logging.getLogger("caseline.agent")

INSTRUCTIONS = (
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


class IntakeAgent(Agent):
    def __init__(self, backend: BackendClient, call_id: str):
        super().__init__(instructions=INSTRUCTIONS)
        self._backend = backend
        self._call_id = call_id

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
            incident_date, injury_type, in_treatment, has_insurance
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
        result = await self._backend.schedule_consult(name, phone, slot_iso)
        logger.info("schedule_consult -> %s", result)
        return result["status"]

    @function_tool
    async def write_to_cms(self, summary: str, structured: dict) -> str:
        """Write the intake record to the firm's case management system. Call this
        once before the call ends.

        Args:
            summary: Two-to-three sentence summary of the call and its outcome.
            structured: The structured facts collected (incident_date, injury_type,
                in_treatment, has_insurance, caller name/phone, decision, and
                consult slot if booked).
        """
        result = await self._backend.write_to_cms(self._call_id, summary, structured)
        logger.info("write_to_cms -> %s", result)
        return result["status"]


def prewarm(proc: JobProcess) -> None:
    # Pre-load VAD so it never costs a caller their first-turn latency.
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    call_id = ctx.room.name
    backend = BackendClient()
    tracker = TurnLatencyTracker(call_id=call_id)
    usage = metrics.UsageCollector()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=anthropic.LLM(model="claude-haiku-4-5"),
        tts=cartesia.TTS(
            model="sonic-3",
            voice=os.getenv("CARTESIA_VOICE_ID") or None,
        ),
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
            "llm_ttft_ms": turn.llm_ttft_ms,
            "tts_ttfb_ms": turn.tts_ttfb_ms,
            "total_ms": turn.total_ms,
        }
        asyncio.create_task(backend.post_turn_metrics(payload))

    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent) -> None:
        usage.collect(ev.metrics)
        m = ev.metrics
        if isinstance(m, metrics.EOUMetrics):
            _report(tracker.on_eou(m.speech_id, m.end_of_utterance_delay))
        elif isinstance(m, metrics.LLMMetrics):
            _report(tracker.on_llm(m.speech_id, m.ttft))
        elif isinstance(m, metrics.TTSMetrics):
            _report(tracker.on_tts(m.speech_id, m.ttfb))

    async def _shutdown() -> None:
        logger.info("call %s latency summary: %s", call_id, tracker.summary())
        logger.info("call %s usage: %s", call_id, usage.get_summary())
        await backend.aclose()

    ctx.add_shutdown_callback(_shutdown)

    await session.start(agent=IntakeAgent(backend=backend, call_id=call_id), room=ctx.room)
    await session.generate_reply(
        instructions="Greet the caller warmly, say you're with the firm's intake team, "
        "and ask how you can help."
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
