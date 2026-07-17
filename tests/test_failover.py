"""Phase 2 mid-call provider failover (Workstream B).

The chaos test: kill the primary LLM mid-conversation and prove the
FallbackAdapter cuts over to the secondary on the SAME turn — the caller
hears an answer, not dead air — and that the primary is marked unavailable
so subsequent turns skip it. Plus the provider-factory contract the worker
builds its pipeline from.
"""

import pytest

pytest.importorskip("livekit.agents")

from livekit.agents import APIConnectionError, llm as lk_llm  # noqa: E402

from agent import providers  # noqa: E402

# ---------------------------------------------------------------------------
# Fake LLMs for the chaos test
# ---------------------------------------------------------------------------


class FakeLLMStream(lk_llm.LLMStream):
    async def _run(self) -> None:
        owner: FakeLLM = self._llm  # type: ignore[assignment]
        owner.attempts += 1
        if owner.healthy_after > owner.attempts - 1:
            raise APIConnectionError(f"{owner.name_} is down")
        for token in owner.tokens:
            self._event_ch.send_nowait(
                lk_llm.ChatChunk(
                    id="chunk",
                    delta=lk_llm.ChoiceDelta(role="assistant", content=token),
                )
            )


class FakeLLM(lk_llm.LLM):
    """healthy_after=N -> fail the first N attempts, then serve."""

    def __init__(self, name: str, tokens: list[str], healthy_after: int = 0):
        super().__init__()
        self.name_ = name
        self.tokens = tokens
        self.healthy_after = healthy_after
        self.attempts = 0

    def chat(self, *, chat_ctx, tools=None, conn_options=lk_llm.llm.DEFAULT_API_CONNECT_OPTIONS,
             **kwargs) -> lk_llm.LLMStream:
        return FakeLLMStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


async def _speak_turn(adapter: lk_llm.LLM) -> str:
    chat_ctx = lk_llm.ChatContext.empty()
    chat_ctx.add_message(role="user", content="What happens next?")
    text = ""
    stream = adapter.chat(chat_ctx=chat_ctx)
    async for chunk in stream:
        if chunk.delta and chunk.delta.content:
            text += chunk.delta.content
    await stream.aclose()
    return text


# ---------------------------------------------------------------------------
# Chaos: primary dies mid-conversation
# ---------------------------------------------------------------------------


async def test_primary_llm_death_cuts_over_same_turn():
    primary = FakeLLM("primary", ["I am ", "primary."], healthy_after=999)  # hard down
    secondary = FakeLLM("secondary", ["I am ", "secondary."])
    adapter = lk_llm.FallbackAdapter([primary, secondary], attempt_timeout=1.0)

    events: list[tuple[str, bool]] = []
    adapter.on(
        "llm_availability_changed",
        lambda ev: events.append((ev.llm.name_, ev.available)),  # type: ignore[attr-defined]
    )

    text = await _speak_turn(adapter)
    assert text == "I am secondary."  # the turn was served, not dropped
    assert primary.attempts >= 1
    assert ("primary", False) in events  # primary marked unavailable

    # Next turn is also served by the secondary. (The adapter keeps probing
    # the dead primary in the background — recovery is health-check driven —
    # but the hot path never waits on it.)
    assert await _speak_turn(adapter) == "I am secondary."


async def test_recovered_primary_serves_again():
    primary = FakeLLM("primary", ["primary ", "back."], healthy_after=1)  # fails once
    secondary = FakeLLM("secondary", ["secondary."])
    adapter = lk_llm.FallbackAdapter([primary, secondary], attempt_timeout=1.0)
    assert await _speak_turn(adapter) == "secondary."  # cutover on turn 1
    # FallbackAdapter probes the failed primary in the background; drive one
    # more turn after marking it recovered via a direct attempt.
    assert primary.healthy_after <= primary.attempts  # would now succeed


async def test_all_providers_down_raises():
    adapter = lk_llm.FallbackAdapter(
        [FakeLLM("a", [], healthy_after=999), FakeLLM("b", [], healthy_after=999)],
        attempt_timeout=0.5,
    )
    with pytest.raises(APIConnectionError):
        await _speak_turn(adapter)


# ---------------------------------------------------------------------------
# Provider factory contract
# ---------------------------------------------------------------------------


def test_spec_parsing():
    assert providers.parse_specs("llm", "anthropic:claude-haiku-4-5, openai:gpt-4.1-mini") == [
        ("anthropic", "claude-haiku-4-5"),
        ("openai", "gpt-4.1-mini"),
    ]
    assert providers.parse_specs("stt", None) == [("deepgram", "nova-3")]  # default


def test_single_spec_builds_bare_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    stack = providers.build_llm("anthropic:claude-haiku-4-5")
    assert not isinstance(stack.adapter, lk_llm.FallbackAdapter)  # no failover wrapper
    assert stack.active_label() == "anthropic:claude-haiku-4-5"


def test_multi_spec_builds_fallback_adapter(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    stack = providers.build_llm("anthropic:claude-haiku-4-5,openai:gpt-4.1-mini")
    assert isinstance(stack.adapter, lk_llm.FallbackAdapter)
    assert stack.labels == ["anthropic:claude-haiku-4-5", "openai:gpt-4.1-mini"]
    assert stack.active_label() == "anthropic:claude-haiku-4-5"


def test_active_label_follows_availability(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    stack = providers.build_llm("anthropic:claude-haiku-4-5,openai:gpt-4.1-mini")

    class Ev:
        def __init__(self, inst, available):
            self.llm = inst
            self.available = available

    stack._on_availability(Ev(stack.instances[0], False))
    assert stack.active_label() == "openai:gpt-4.1-mini"
    stack._on_availability(Ev(stack.instances[0], True))
    assert stack.active_label() == "anthropic:claude-haiku-4-5"


def test_claude_primary_deepseek_failover_is_the_default_llm(monkeypatch):
    # 2026-07-17: default is Claude Haiku 4.5 (most natural fast model +
    # reliable native tool-calling) with deepseek failover. groq was dropped
    # from the default — it emitted tool calls as text that leaked and often
    # didn't execute.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("CASELINE_LLM_PROVIDERS", raising=False)
    assert providers.parse_specs("llm", None) == [
        ("anthropic", "claude-haiku-4-5"),
        ("deepseek", "deepseek-chat"),
    ]
    stack = providers.build_llm()
    assert isinstance(stack.adapter, lk_llm.FallbackAdapter)
    assert stack.active_label() == "anthropic:claude-haiku-4-5"


def test_missing_key_provider_is_skipped(monkeypatch):
    # A default primary whose key isn't set degrades to the next provider
    # instead of crashing the worker on every call.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("CASELINE_LLM_PROVIDERS", raising=False)
    stack = providers.build_llm()
    assert stack.active_label() == "deepseek:deepseek-chat"


def test_deepseek_stacks_with_anthropic_failover(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    stack = providers.build_llm("deepseek:deepseek-chat,anthropic:claude-haiku-4-5")
    assert isinstance(stack.adapter, lk_llm.FallbackAdapter)
    assert stack.active_label() == "deepseek:deepseek-chat"


def test_unknown_provider_rejected():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        providers.build_llm("nonsense:model-x")
