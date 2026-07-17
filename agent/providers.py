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
from dataclasses import dataclass, field

logger = logging.getLogger("caseline.agent.providers")

DEFAULTS = {
    "stt": "deepgram:nova-3",
    # 2026-07-16: voice LLM default is groq (measured median TTFT 376 ms —
    # fits the 800 ms turn SLO; deepseek's 748 ms did not) with deepseek as
    # failover. Both are OpenAI-compatible endpoints, keys via
    # GROQ_API_KEY / DEEPSEEK_API_KEY. Re-verify on real calls — turn metrics
    # slice latency by provider; anthropic stays one env entry away.
    "llm": "groq:llama-3.3-70b-versatile,deepseek:deepseek-chat",
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

        return cartesia.TTS(model=model or "sonic-3", voice=voice_id)
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


def build_llm(raw: str | None = None) -> ProviderStack:
    specs = parse_specs("llm", raw)
    return _stack(
        "llm",
        [_build_llm(p, m) for p, m in specs],
        [f"{p}:{m}" for p, m in specs],
    )


def build_tts(voice_id: str | None = None, raw: str | None = None) -> ProviderStack:
    specs = parse_specs("tts", raw)
    return _stack(
        "tts",
        [_build_tts(p, m, voice_id) for p, m in specs],
        [f"{p}:{m}" for p, m in specs],
    )
