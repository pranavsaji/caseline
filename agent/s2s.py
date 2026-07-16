"""Selective speech-to-speech (Phase 4): greeting segment only, evidence-gated.

The plan's position (guiding principle #5) stands: the qualification body of
a call stays on the cascading STT->LLM->TTS pipeline — auditable
transcripts, guardrail insertion points, and provider failover are
non-negotiable in legal intake. The only segment where S2S realism could
pay is the greeting, before any substantive exchange.

So S2S is not a flag someone flips on a hunch. :func:`plan_greeting`
requires all three, in order:

  1. ``CASELINE_S2S_GREETING=true``   — explicit operator intent;
  2. ``CASELINE_S2S_PROVIDER`` set    — e.g. ``openai:gpt-realtime``;
  3. a benchmark verdict file (written by ``scripts/s2s_benchmark.py``
     after live A/B trials) whose ``realism_win`` is true — measured
     evidence, not vibes.

Anything short of that yields the cascaded pipeline, with the reason
logged. The worker consults this at call start; the decision is per-process
config, deterministic, and testable without any provider account.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

VERDICT_PATH = Path(__file__).resolve().parent.parent / "benchmarks" / "s2s_verdict.json"

MODE_CASCADED = "cascaded"
MODE_S2S = "s2s"


@dataclass(frozen=True)
class GreetingPlan:
    mode: str  # cascaded | s2s
    provider: str | None
    reason: str


def load_verdict(path: Path | None = None) -> dict | None:
    path = path or VERDICT_PATH
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def plan_greeting(
    env: dict[str, str] | None = None, verdict_path: Path | None = None
) -> GreetingPlan:
    """Decide how the greeting segment is served. Cascaded is the default
    and the fallback for every unmet precondition."""
    env = env if env is not None else dict(os.environ)

    if env.get("CASELINE_S2S_GREETING", "").strip().lower() not in ("1", "true", "yes"):
        return GreetingPlan(
            mode=MODE_CASCADED,
            provider=None,
            reason="S2S greeting disabled (default): cascading pipeline serves the whole call",
        )
    provider = env.get("CASELINE_S2S_PROVIDER", "").strip()
    if not provider:
        return GreetingPlan(
            mode=MODE_CASCADED,
            provider=None,
            reason="CASELINE_S2S_GREETING is on but no CASELINE_S2S_PROVIDER is configured",
        )
    verdict = load_verdict(verdict_path)
    if not verdict:
        return GreetingPlan(
            mode=MODE_CASCADED,
            provider=None,
            reason=(
                "no S2S benchmark verdict on file — run scripts/s2s_benchmark.py; "
                "S2S ships only on measured evidence"
            ),
        )
    if not verdict.get("realism_win"):
        return GreetingPlan(
            mode=MODE_CASCADED,
            provider=None,
            reason=(
                "benchmark verdict does not justify S2S "
                f"(realism_win={verdict.get('realism_win')!r})"
            ),
        )
    return GreetingPlan(
        mode=MODE_S2S,
        provider=provider,
        reason=f"benchmarked realism win on file; greeting served by {provider}",
    )
