"""Greeting-segment realism benchmark: cascaded pipeline vs speech-to-speech.

Phase 4 revisits S2S for the greeting only, *if realism benchmarks justify
it* (plan.md). This harness produces that evidence and writes the verdict
file ``agent/s2s.plan_greeting`` requires before it will ever pick S2S.

What it measures per trial:
  * cascaded: LLM first-token + TTS first-chunk for the greeting line via
    the exact providers the worker runs (agent/providers.py specs);
  * s2s: time-to-first-audio from the realtime provider for the same line.
Realism itself (voice naturalness) is a human judgment: the harness records
latency and writes ``realism_win: null`` — a human sets it to true/false
after listening to the saved comparisons. The gate stays honest: no keys,
no trials, no verdict, no S2S.

Run (needs live provider keys in .env):
    uv run python scripts/s2s_benchmark.py --trials 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

VERDICT_PATH = Path(__file__).resolve().parent.parent / "benchmarks" / "s2s_verdict.json"
GREETING = (
    "Hi, thanks for calling — I'm the intake assistant here at the firm. "
    "How can I help you today?"
)


async def time_cascaded_greeting() -> float:
    """LLM TTFT + TTS TTFB for the greeting on the production provider stack."""
    from agent import providers

    llm = providers.build_llm().instances[0]
    tts = providers.build_tts().instances[0]

    start = time.perf_counter()
    from livekit.agents.llm import ChatContext

    chat = ChatContext()
    chat.add_message(role="system", content="Speak this greeting naturally.")
    chat.add_message(role="user", content=GREETING)
    llm_first = None
    async with llm.chat(chat_ctx=chat) as stream:
        async for _chunk in stream:
            llm_first = time.perf_counter()
            break
    tts_first = None
    async with tts.synthesize(GREETING) as audio:
        async for _frame in audio:
            tts_first = time.perf_counter()
            break
    if llm_first is None or tts_first is None:
        raise RuntimeError("no first token/chunk received")
    return ((llm_first - start) + (tts_first - llm_first)) * 1000


async def time_s2s_greeting(provider_spec: str) -> float:
    """Time-to-first-audio for the greeting from a realtime S2S model."""
    provider, _, model = provider_spec.partition(":")
    if provider != "openai":
        raise ValueError(f"unsupported S2S provider {provider!r}")
    from livekit.plugins import openai as lk_openai

    rt = lk_openai.realtime.RealtimeModel(model=model or "gpt-realtime")
    start = time.perf_counter()
    session = rt.session()
    async with session:
        session.generate_reply(instructions=f"Say exactly: {GREETING}")
        async for ev in session:
            if getattr(ev, "type", "") in ("audio", "response.audio.delta"):
                return (time.perf_counter() - start) * 1000
    raise RuntimeError("no audio received from realtime session")


async def run(trials: int, provider_spec: str) -> dict:
    cascaded, s2s = [], []
    for i in range(trials):
        cascaded.append(await time_cascaded_greeting())
        s2s.append(await time_s2s_greeting(provider_spec))
        print(f"trial {i + 1}/{trials}: cascaded {cascaded[-1]:.0f} ms, s2s {s2s[-1]:.0f} ms")
    return {
        "trials": trials,
        "provider": provider_spec,
        "cascaded_ms": {"p50": statistics.median(cascaded), "values": cascaded},
        "s2s_ms": {"p50": statistics.median(s2s), "values": s2s},
        # Latency is measured; realism is judged. A human listens and flips
        # this to true/false — plan_greeting refuses S2S until then.
        "realism_win": None,
        "note": "set realism_win to true only after human listening review",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument(
        "--provider", default=os.getenv("CASELINE_S2S_PROVIDER", "openai:gpt-realtime")
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print(
            "S2S benchmark needs live provider keys (OPENAI_API_KEY plus the\n"
            "cascaded stack's keys). No keys found — nothing was run, no verdict\n"
            "was written, and agent/s2s.py keeps serving the cascaded pipeline.",
            file=sys.stderr,
        )
        return 1

    verdict = asyncio.run(run(args.trials, args.provider))
    VERDICT_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERDICT_PATH.write_text(json.dumps(verdict, indent=2))
    print(f"verdict written to {VERDICT_PATH} (realism_win pending human review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
