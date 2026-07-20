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
  CASELINE_TTS_PROVIDERS=cartesia:sonic-3.5[,openai:tts-1]

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
    # conversationalist of the fast tier and a reliable native tool-caller —
    # with DeepSeek V4 Flash as failover (fast, cheap, solid at tools; the old
    # deepseek-chat alias EOLs 2026-07-24). Both are the low-latency "flash/mini"
    # tier, not the flagships — the right speed/cost/quality balance for live
    # calls. groq's llama-3.3-70b was dropped: it leaked tool calls as literal
    # text ("<function=...>"). FunctionCallStripper still guards every model.
    # Keys via ANTHROPIC_API_KEY / DEEPSEEK_API_KEY.
    "llm": "anthropic:claude-haiku-4-5,deepseek:deepseek-v4-flash",
    "tts": "cartesia:sonic-3.5",
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


# The LLM provider catalog. Every entry is (env key, default model, connector).
# The connector tells _build_llm how to construct the client:
#   * "anthropic" / "openai" -> the native LiveKit plugin
#   * "with_*"                -> the openai plugin's built-in helper for that
#                               vendor (reads its own standard env var)
#   * a URL string           -> an OpenAI-compatible endpoint at that base_url,
#                               authed with the env key above
# Adding a provider is just a row here plus its key in .env — no other code.
# Aliases (e.g. "gemini" -> google, "grok" -> xai) are folded in below.
# Defaults verified current as of 2026-07-17. Retired IDs replaced: gemini
# 2.0->flash-latest, deepseek-chat->v4-flash (old alias EOL 2026-07-24), groq
# llama-3.3 (deprecated)->gpt-oss-20b, grok-3-mini (retired)->grok-4.1-fast,
# cerebras llama-3.3-70b (retired)->gpt-oss-120b.
_LLM_REGISTRY: dict[str, tuple[str, str, str]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "claude-haiku-4-5", "anthropic"),
    "openai": ("OPENAI_API_KEY", "gpt-5.4-mini", "openai"),
    "google": (
        "GEMINI_API_KEY",
        "gemini-flash-latest",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    "deepseek": ("DEEPSEEK_API_KEY", "deepseek-v4-flash", "with_deepseek"),
    "groq": ("GROQ_API_KEY", "openai/gpt-oss-20b", "https://api.groq.com/openai/v1"),
    "xai": ("XAI_API_KEY", "grok-4.1-fast", "with_x_ai"),
    "mistral": ("MISTRAL_API_KEY", "mistral-small-latest", "https://api.mistral.ai/v1"),
    "together": (
        "TOGETHER_API_KEY",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "with_together",
    ),
    "fireworks": (
        "FIREWORKS_API_KEY",
        "accounts/fireworks/models/gpt-oss-120b",
        "with_fireworks",
    ),
    "openrouter": ("OPENROUTER_API_KEY", "openai/gpt-5.4-mini", "with_openrouter"),
    "perplexity": ("PERPLEXITY_API_KEY", "sonar", "with_perplexity"),
    "cerebras": ("CEREBRAS_API_KEY", "gpt-oss-120b", "with_cerebras"),
    "ollama": ("", "llama3.1", "with_ollama"),
}
# Friendly aliases callers may type in a spec or the UI.
_LLM_ALIASES = {"gemini": "google", "grok": "xai", "x-ai": "xai"}

# Human labels + curated model suggestions for the config UI. Not exhaustive —
# the UI also accepts a free-text model id — kept next to _LLM_REGISTRY so all
# provider knowledge lives in one file.
_LLM_LABELS = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI",
    "google": "Google Gemini",
    "deepseek": "DeepSeek",
    "groq": "Groq",
    "xai": "xAI (Grok)",
    "mistral": "Mistral",
    "together": "Together AI",
    "fireworks": "Fireworks",
    "openrouter": "OpenRouter",
    "perplexity": "Perplexity",
    "cerebras": "Cerebras",
    "ollama": "Ollama (local)",
}
_LLM_MODEL_SUGGESTIONS = {
    "anthropic": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8"],
    # GPT-5.4 mini/nano are the fast, cost-optimized voice-agent picks;
    # gpt-5.4 / gpt-5.5 sit above them, gpt-4.1* remain for legacy pins.
    "openai": [
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.4",
        "gpt-5.5",
        "gpt-4.1-mini",
        "gpt-4.1",
    ],
    "google": [
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash",
        "gemini-3.1-pro",
    ],
    "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro"],
    "groq": ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b"],
    "xai": ["grok-4.1-fast", "grok-4.5", "grok-4.3"],
    "mistral": ["mistral-small-latest", "mistral-large-latest", "magistral-medium-latest"],
    "together": ["meta-llama/Llama-3.3-70B-Instruct-Turbo", "Qwen/Qwen3.5-9B"],
    "fireworks": [
        "accounts/fireworks/models/gpt-oss-120b",
        "accounts/fireworks/models/deepseek-v3p2",
    ],
    "openrouter": [
        "openai/gpt-5.4-mini",
        "anthropic/claude-haiku-4-5",
        "google/gemini-3.5-flash",
        "deepseek/deepseek-v4-flash",
    ],
    "perplexity": ["sonar", "sonar-pro", "sonar-reasoning"],
    "cerebras": ["gpt-oss-120b", "zai-glm-4.7", "llama-4-scout"],
    "ollama": ["llama3.1", "qwen2.5"],
}


def _is_configured(provider: str, key_env: str) -> bool:
    """Whether this provider can actually serve a call from this environment.

    For hosted providers that means their API key is set. Ollama is the
    exception: it needs no key, so a naive "no key required -> ready" check
    marks it usable everywhere — including production, where there is no Ollama
    server in the container and selecting it silently breaks every call. It
    counts as configured only when explicitly pointed at a reachable server.
    """
    if provider == "ollama":
        return bool(os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST"))
    return bool(key_env) and bool(os.getenv(key_env))


def llm_catalog() -> list[dict]:
    """Provider catalog for the config UI: label, what it requires, whether that
    requirement is satisfied in this process's env, and default + suggested
    models. Safe to call from the API (no livekit import)."""
    catalog = []
    for provider, (key_env, default_model, _connector) in _LLM_REGISTRY.items():
        catalog.append(
            {
                "provider": provider,
                "label": _LLM_LABELS.get(provider, provider),
                "env_key": key_env or None,
                # What the operator has to set for this provider to work — shown
                # in the UI so "not configured" is actionable rather than a dead end.
                "requires": key_env or ("OLLAMA_BASE_URL" if provider == "ollama" else None),
                "configured": _is_configured(provider, key_env),
                "default_model": default_model,
                "models": _LLM_MODEL_SUGGESTIONS.get(provider, [default_model]),
            }
        )
    return catalog


def _llm_entry(provider: str) -> tuple[str, str, str] | None:
    provider = _LLM_ALIASES.get(provider, provider)
    return _LLM_REGISTRY.get(provider)


def _build_llm(provider: str, model: str) -> object:
    provider = _LLM_ALIASES.get(provider.lower(), provider.lower())
    entry = _LLM_REGISTRY.get(provider)
    if entry is None:
        raise ValueError(f"Unknown LLM provider {provider!r}")
    key_env, default_model, connector = entry
    model = model or default_model

    if connector == "anthropic":
        from livekit.plugins import anthropic

        # Prompt caching is the single biggest per-turn latency lever here: the
        # system prompt (five concatenated blocks) and all nine tool schemas are
        # a large, *stable* prefix that Claude would otherwise re-process on every
        # turn. caching="ephemeral" marks that prefix cached, so every turn after
        # the first reads it from cache instead of re-encoding it — a big cut to
        # LLM TTFT with zero change to the model or its output. Spoken replies are
        # short, so cap max_tokens to bound worst-case generation too.
        return anthropic.LLM(model=model, caching="ephemeral", max_tokens=1024)

    from livekit.plugins import openai

    if connector == "openai":
        return openai.LLM(model=model)
    if connector.startswith("http"):
        # OpenAI-compatible endpoint (Gemini, Groq, Mistral, …): a base_url plus
        # the vendor's key. Covers any provider that exposes an /v1/chat shim.
        return openai.LLM(model=model, base_url=connector, api_key=os.getenv(key_env))
    # An openai-plugin helper (with_deepseek, with_x_ai, with_together, …). Each
    # reads its own standard env var and points at the right base_url.
    return getattr(openai.LLM, connector)(model=model)


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
            # Cartesia's current model. sonic-2 is being sunset (2026-10-20) and a
            # bare "sonic-3" is not a distinct model id, so pin the latest explicitly.
            model=model or "sonic-3.5",
            voice=voice,
            http_session=_cartesia_http_session(),
        )
        # TTS TTFB (time to first audio) is bounded by how much text the adapter
        # buffers before it synthesizes: the bytes path returns audio for a whole
        # segment at once, so a long first sentence means a long silence. Flush
        # the first speakable chunk sooner (shorter min sentence length) so the
        # caller hears the opening words while the rest is still synthesizing —
        # this trims first-audio latency without touching the model or voice.
        from livekit.agents import tokenize

        fast_tokenizer = tokenize.basic.SentenceTokenizer(min_sentence_len=8)
        return lk_tts.StreamAdapter(tts=base, sentence_tokenizer=fast_tokenizer)
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
    # A spec whose key is absent is skipped so a not-yet-configured primary
    # (e.g. anthropic before the key is added) degrades to the next provider
    # instead of crashing the worker on every call. Provider->key mapping and
    # aliases come from _LLM_REGISTRY (single source of truth).
    specs = parse_specs("llm", raw)
    usable = []
    for p, m in specs:
        entry = _llm_entry(p)
        key_env = entry[0] if entry else None
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
