"""Provider factory + mid-call failover for the voice worker.

Phase 2 Workstream B: every pipeline stage (STT/LLM/TTS) is built from a
comma-separated spec list — ``provider:model`` — where the first entry is
the primary and the rest are fallbacks, wrapped in LiveKit's health-check
driven ``FallbackAdapter``. Cutover happens mid-call: a primary that times
out or errors is marked unavailable, the next provider serves the same
turn, and the primary is probed in the background until it recovers.

Env (single-entry lists mean "no failover", the Phase 0/1 behavior):

  CASELINE_STT_PROVIDERS=deepgram:nova-3[,openai:whisper-1]
  CASELINE_LLM_PROVIDERS=groq:llama-3.3-70b-versatile[,deepseek:deepseek-chat]
  CASELINE_TTS_PROVIDERS=cartesia:sonic-3[,openai:tts-1]

Provider names appear here and in config only (cross-phase rule). The
``ProviderStack`` tracks which instance is currently serving so turn metrics
can be sliced by the provider that actually handled the turn.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger("caseline.agent.providers")

# A transcript with no letters or digits ("...", "?", " ") makes Cartesia's TTS
# bytes endpoint 400 ("empty or contains only punctuation"). Used to skip such
# segments so one stray punctuation sentence can't mute a whole turn.
_HAS_SPEECH = re.compile(r"[^\W_]", re.UNICODE)

# Cartesia voice ids are UUIDs; anything else (a mock/placeholder or a
# half-provisioned per-firm voice) 400s every turn — validate before use.
_CARTESIA_VOICE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

# Cartesia "Daniel - Modern Assistant" — a safe, always-available default so a
# missing CARTESIA_VOICE_ID never mutes the agent (see _build_tts).
DEFAULT_CARTESIA_VOICE = "47c38ca4-5f35-497b-b1a3-415245fb35e1"

# Cartesia's streaming TTS websocket does not survive on LiveKit's shared
# http_session() inside the worker subprocess — the handshake connects but the
# stream yields zero audio frames, so every turn goes silent ("no audio frames
# were pushed"). A dedicated aiohttp session (which the plugin accepts via
# http_session=) is reliable; verified against a plain session returning full
# audio where the shared one produced none. Created lazily inside the running
# job loop and reused for the process's lifetime.
_cartesia_session = None


def _cartesia_http_session():
    """A dedicated aiohttp session for Cartesia TTS (see note above)."""
    global _cartesia_session
    import aiohttp

    if _cartesia_session is None or _cartesia_session.closed:
        _cartesia_session = aiohttp.ClientSession()
    return _cartesia_session

DEFAULTS = {
    "stt": "deepgram:nova-3",
    # 2026-07-17: voice LLM default is Claude Haiku 4.5 — the most natural
    # conversationalist of the fast models and a reliable native tool-caller —
    # with deepseek as failover (also solid at tools). groq's llama-3.3-70b was
    # dropped from the default: it frequently emitted tool calls as literal text
    # ("<function=...>") that leaked to callers and often didn't execute.
    # FunctionCallStripper still guards every model against that leak. Keys via
    # ANTHROPIC_API_KEY / DEEPSEEK_API_KEY.
    "llm": "anthropic:claude-haiku-4-5,deepseek:deepseek-chat",
    "tts": "cartesia:sonic-3",
}

_AVAILABILITY_EVENTS = (
    "llm_availability_changed",
    "stt_availability_changed",
    "tts_availability_changed",
)


def parse_specs(kind: str, raw: str | None = None) -> list[tuple[str, str]]:
    """``"deepgram:nova-3, openai:whisper-1"`` -> [(provider, model), ...]."""
    raw = raw or os.getenv(f"CASELINE_{kind.upper()}_PROVIDERS") or DEFAULTS[kind]
    specs: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        provider, _, model = part.partition(":")
        specs.append((provider.strip().lower(), model.strip()))
    if not specs:
        raise ValueError(f"no {kind} providers configured")
    return specs


@dataclass
class ProviderStack:
    """A pipeline stage: the adapter to hand to AgentSession plus the
    bookkeeping to know which provider is serving right now."""

    kind: str
    adapter: object
    labels: list[str]
    instances: list[object]
    _available: list[bool] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._available = [True] * len(self.instances)
        if len(self.instances) > 1:
            for event in _AVAILABILITY_EVENTS:
                try:
                    self.adapter.on(event, self._on_availability)  # type: ignore[attr-defined]
                    break
                except Exception:  # noqa: BLE001 — event name differs per modality
                    continue

    def _on_availability(self, ev: object) -> None:
        instance = getattr(ev, self.kind, None)
        available = getattr(ev, "available", True)
        for i, inst in enumerate(self.instances):
            if inst is instance:
                self._available[i] = available
                logger.warning(
                    "%s provider %s is now %s; serving from %s",
                    self.kind, self.labels[i],
                    "available" if available else "UNAVAILABLE",
                    self.active_label(),
                )
                return

    def active_label(self) -> str:
        """The provider currently first in line to serve."""
        for label, ok in zip(self.labels, self._available):
            if ok:
                return label
        return self.labels[0]


# --- per-provider constructors (import-lazy: only configured plugins load) ---


def _build_stt(provider: str, model: str) -> object:
    if provider == "deepgram":
        from livekit.plugins import deepgram

        return deepgram.STT(model=model or "nova-3")
    if provider == "openai":
        from livekit.plugins import openai

        return openai.STT(model=model or "whisper-1")
    raise ValueError(f"Unknown STT provider {provider!r}")


def _build_llm(provider: str, model: str) -> object:
    if provider == "deepseek":
        from livekit.plugins import openai

        # OpenAI-compatible endpoint; auths via DEEPSEEK_API_KEY.
        return openai.LLM.with_deepseek(model=model or "deepseek-chat")
    if provider == "anthropic":
        from livekit.plugins import anthropic

        return anthropic.LLM(model=model or "claude-haiku-4-5")
    if provider == "openai":
        from livekit.plugins import openai

        return openai.LLM(model=model or "gpt-4.1-mini")
    if provider == "groq":
        from livekit.plugins import openai

        # OpenAI-compatible endpoint (the installed plugin version has no
        # with_groq helper); auths via GROQ_API_KEY.
        return openai.LLM(
            model=model or "llama-3.3-70b-versatile",
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("GROQ_API_KEY"),
        )
    raise ValueError(f"Unknown LLM provider {provider!r}")


def _build_tts(provider: str, model: str, voice_id: str | None) -> object:
    if provider == "cartesia":
        from livekit.plugins import cartesia

        # Cartesia REQUIRES a voice id — with voice=None it pushes no audio
        # frames and the whole turn goes silent (retries then errors). Fall back
        # to a stable default voice so a missing CARTESIA_VOICE_ID can never mute
        # the agent; a real per-firm/cloned voice still overrides via voice_id.
        voice = voice_id or os.getenv("CARTESIA_DEFAULT_VOICE_ID") or DEFAULT_CARTESIA_VOICE
        # A Cartesia voice id is a UUID. A non-UUID value (e.g. a leftover
        # "mock-voice-…" from a cloning test, or a half-provisioned per-firm
        # voice) makes Cartesia 400 every turn and mutes the agent — the same
        # failure a missing id would cause, so treat it the same and fall back.
        if not _CARTESIA_VOICE_RE.match(voice):
            logger.warning(
                "cartesia voice_id %r is not a valid voice id; using default voice", voice
            )
            voice = DEFAULT_CARTESIA_VOICE
        # Cartesia's streaming websocket returns `done` with zero audio frames
        # when the AgentSession feeds it token-by-token (verified: every turn
        # goes silent with "no audio frames were pushed", while the one-shot
        # bytes endpoint returns full audio). A StreamAdapter buffers text into
        # sentences and calls the reliable bytes `synthesize()` path instead —
        # near-real-time (per sentence), never silent.
        #
        # The catch: sentence splitting can hand a sentence that is only
        # punctuation (a stray "." / "?"), and Cartesia's bytes endpoint 400s on
        # any transcript with no letters/digits ("empty or contains only
        # punctuation"), which fails the whole turn. StreamAdapter already skips
        # whitespace-only segments but not punctuation-only ones, so guard the
        # synthesize path to emit an empty segment for speechless text.
        from livekit.agents import tts as lk_tts, utils as lk_utils
        from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
        from livekit.plugins.cartesia import tts as cartesia_tts

        class _GuardedChunkedStream(cartesia_tts.ChunkedStream):
            async def _run(self, output_emitter) -> None:
                if not _HAS_SPEECH.search(self._input_text or ""):
                    output_emitter.initialize(
                        request_id=lk_utils.shortuuid(),
                        sample_rate=self._opts.sample_rate,
                        num_channels=1,
                        mime_type="audio/pcm",
                    )
                    output_emitter.flush()
                    return
                await super()._run(output_emitter)

        class _GuardedCartesiaTTS(cartesia.TTS):
            def synthesize(self, text, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
                return _GuardedChunkedStream(
                    tts=self, input_text=text, conn_options=conn_options
                )

        base = _GuardedCartesiaTTS(
            model=model or "sonic-3",
            voice=voice,
            http_session=_cartesia_http_session(),
        )
        return lk_tts.StreamAdapter(tts=base)
    if provider == "openai":
        from livekit.plugins import openai

        kwargs = {"model": model or "tts-1"}
        if voice_id:
            kwargs["voice"] = voice_id
        return openai.TTS(**kwargs)
    raise ValueError(f"Unknown TTS provider {provider!r}")


def _stack(kind: str, instances: list[object], labels: list[str]) -> ProviderStack:
    if len(instances) == 1:
        return ProviderStack(kind=kind, adapter=instances[0], labels=labels, instances=instances)
    if kind == "llm":
        from livekit.agents import llm as lk_llm

        adapter = lk_llm.FallbackAdapter(instances)
    elif kind == "stt":
        from livekit.agents import stt as lk_stt

        adapter = lk_stt.FallbackAdapter(instances)
    else:
        from livekit.agents import tts as lk_tts

        adapter = lk_tts.FallbackAdapter(instances)
    logger.info("%s failover enabled: %s", kind, " -> ".join(labels))
    return ProviderStack(kind=kind, adapter=adapter, labels=labels, instances=instances)


def build_stt(raw: str | None = None) -> ProviderStack:
    specs = parse_specs("stt", raw)
    return _stack(
        "stt",
        [_build_stt(p, m) for p, m in specs],
        [f"{p}:{m}" for p, m in specs],
    )


# The env var each LLM provider needs; a spec whose key is absent is skipped so
# a not-yet-configured primary (e.g. anthropic before the key is added) degrades
# to the next provider instead of crashing the worker on every call.
_LLM_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
}


def build_llm(raw: str | None = None) -> ProviderStack:
    specs = parse_specs("llm", raw)
    usable = []
    for p, m in specs:
        key_env = _LLM_KEY_ENV.get(p)
        if key_env and not os.getenv(key_env):
            logger.warning("llm provider %s skipped: %s not set", p, key_env)
            continue
        usable.append((p, m))
    if not usable:  # nothing configured — keep the original list so the error is loud
        usable = specs
    return _stack(
        "llm",
        [_build_llm(p, m) for p, m in usable],
        [f"{p}:{m}" for p, m in usable],
    )


def build_tts(voice_id: str | None = None, raw: str | None = None) -> ProviderStack:
    specs = parse_specs("tts", raw)
    return _stack(
        "tts",
        [_build_tts(p, m, voice_id) for p, m in specs],
        [f"{p}:{m}" for p, m in specs],
    )
