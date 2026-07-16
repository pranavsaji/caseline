"""Per-turn latency tracking for the voice worker.

Phase 0 exit criteria demand per-stage numbers (EOU delay, LLM TTFT, TTS TTFB)
per turn, p50/p95 per call. LiveKit Agents emits these as metrics events keyed
by speech_id; this module stitches the three stages of a turn back together
and reports each completed turn.

Turn latency (caller stops speaking -> first agent audio) is approximated as:
    end_of_utterance_delay + llm_ttft + tts_ttfb
which is the standard LiveKit formulation. Livekit-free by design (plain
dataclasses) so it is unit-testable without the voice stack.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field

logger = logging.getLogger("caseline.agent.latency")

TURN_BUDGET_MS = 800.0  # Phase 0 hard ceiling (p95)


@dataclass
class TurnSample:
    speech_id: str
    eou_delay_ms: float | None = None
    llm_ttft_ms: float | None = None
    tts_ttfb_ms: float | None = None

    @property
    def complete(self) -> bool:
        return None not in (self.eou_delay_ms, self.llm_ttft_ms, self.tts_ttfb_ms)

    @property
    def total_ms(self) -> float:
        return (self.eou_delay_ms or 0) + (self.llm_ttft_ms or 0) + (self.tts_ttfb_ms or 0)


@dataclass
class TurnLatencyTracker:
    """Aggregates stage metrics by speech_id; returns a finished TurnSample
    once all three stages of that turn have reported."""

    call_id: str
    _pending: dict[str, TurnSample] = field(default_factory=dict)
    completed: list[TurnSample] = field(default_factory=list)

    def _sample(self, speech_id: str) -> TurnSample:
        return self._pending.setdefault(speech_id, TurnSample(speech_id=speech_id))

    def _maybe_complete(self, speech_id: str) -> TurnSample | None:
        sample = self._pending.get(speech_id)
        if sample is None or not sample.complete:
            return None
        del self._pending[speech_id]
        self.completed.append(sample)
        logger.info(
            "turn %s: eou=%.0fms llm_ttft=%.0fms tts_ttfb=%.0fms total=%.0fms%s",
            sample.speech_id,
            sample.eou_delay_ms,
            sample.llm_ttft_ms,
            sample.tts_ttfb_ms,
            sample.total_ms,
            "" if sample.total_ms <= TURN_BUDGET_MS else "  ** OVER BUDGET **",
        )
        return sample

    def on_eou(self, speech_id: str, delay_s: float) -> TurnSample | None:
        self._sample(speech_id).eou_delay_ms = delay_s * 1000
        return self._maybe_complete(speech_id)

    def on_llm(self, speech_id: str, ttft_s: float) -> TurnSample | None:
        self._sample(speech_id).llm_ttft_ms = ttft_s * 1000
        return self._maybe_complete(speech_id)

    def on_tts(self, speech_id: str, ttfb_s: float) -> TurnSample | None:
        self._sample(speech_id).tts_ttfb_ms = ttfb_s * 1000
        return self._maybe_complete(speech_id)

    def summary(self) -> dict:
        totals = sorted(t.total_ms for t in self.completed)
        if not totals:
            return {"call_id": self.call_id, "turns": 0}
        if len(totals) == 1:
            p50, p95 = totals[0], totals[0]
        else:
            q = statistics.quantiles(totals, n=100, method="inclusive")
            p50, p95 = q[49], q[94]
        return {
            "call_id": self.call_id,
            "turns": len(totals),
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "max_ms": round(totals[-1], 1),
            "within_budget": p95 <= TURN_BUDGET_MS,
        }
