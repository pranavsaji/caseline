"""Guardrail output filter: the safety pass between LLM and TTS.

Phase 1 scope (plan.md Workstream B): prompt constraints plus a fast
regex/keyword screen that blocks the three unforgivables in legal intake —
legal advice, fee quotes, and outcome guarantees — before they are ever
spoken. The sub-100 ms inline ML classifier is Phase 2; this screen is the
insertion point it will slot into.

Everything here is pure and dependency-free so the voice worker can import
it without dragging in FastAPI or Postgres, and so it costs microseconds on
the hot path (there is a latency budget line item for it: ~0 ms measurable).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Category -> patterns. Compiled once at import; matched per sentence.
_BLOCKED: dict[str, list[str]] = {
    "legal_advice": [
        r"\byou (?:should|need to|must|ought to) (?:sue|file|accept|reject|sign|refuse|demand)\b",
        r"\byou (?:definitely |certainly |clearly )?have a (?:strong|great|winning|solid|good) (?:case|claim)\b",
        r"\b(?:my|our) legal (?:advice|opinion)\b",
        r"\byou(?:'re| are) (?:legally )?entitled to\b",
        r"\bthe(?:y| other (?:party|driver|side))(?: is| are) (?:clearly |definitely )?(?:liable|at fault)\b",
        r"\bdon'?t (?:talk|speak) to the(?:ir)? insurance\b",
        r"\bstatute of limitations (?:has|hasn'?t) (?:expired|run|passed)\b",
    ],
    "fee_quote": [
        r"\b(?:our|the) (?:fee|fees|rate|retainer) (?:is|are|would be|starts? at)\b",
        r"\bwe (?:charge|take|keep|bill) (?:a |an |about |around )?(?:\$?\d|\d{1,2}\s?(?:%|percent))",
        r"\bcontingency (?:fee|percentage) (?:is|of) \d",
        r"\bno fee unless we win\b",
        r"\$\s?\d[\d,]*(?:\.\d+)?\s*(?:fee|retainer|charge|cost)\b",
    ],
    "outcome_guarantee": [
        r"\b(?:I|we) (?:guarantee|promise|assure you)\b",
        r"\byou (?:will|are going to) (?:win|receive|get|be awarded)\b",
        r"\bwe (?:always|never lose|will) win\b",
        r"\byour case is worth\b",
        r"\byou (?:could|will|should) (?:get|receive|recover) \$\s?\d",
        r"\bguaranteed (?:settlement|outcome|result|compensation|win)\b",
    ],
}

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class GuardrailVerdict:
    allowed: bool
    category: str | None = None
    matched: str | None = None


@dataclass
class GuardrailScreen:
    """Compiled screen; construct once per call with the firm's extras."""

    extra_blocked_patterns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._compiled: list[tuple[str, re.Pattern[str]]] = [
            (category, re.compile(pattern, re.IGNORECASE))
            for category, patterns in _BLOCKED.items()
            for pattern in patterns
        ] + [
            ("firm_blocklist", re.compile(pattern, re.IGNORECASE))
            for pattern in self.extra_blocked_patterns
        ]

    def screen(self, text: str) -> GuardrailVerdict:
        for category, pattern in self._compiled:
            m = pattern.search(text)
            if m:
                return GuardrailVerdict(allowed=False, category=category, matched=m.group(0))
        return GuardrailVerdict(allowed=True)


class StreamGuard:
    """Incremental screen for a streamed LLM response.

    Feed text deltas as they arrive; it releases text sentence-by-sentence.
    The moment a sentence trips the screen, the stream is tripped: nothing
    further is released and the caller should speak the deflection line
    instead. Buffering at sentence granularity keeps added latency at one
    sentence boundary — well inside the turn budget."""

    def __init__(self, screen: GuardrailScreen, deflection_line: str):
        self._screen = screen
        self.deflection_line = deflection_line
        self._buffer = ""
        self.tripped: GuardrailVerdict | None = None

    def _release(self, text: str) -> str | None:
        verdict = self._screen.screen(text)
        if not verdict.allowed:
            self.tripped = verdict
            self._buffer = ""
            return None
        return text

    def feed(self, delta: str) -> str | None:
        """Feed a delta; returns text safe to speak now (or None)."""
        if self.tripped:
            return None
        self._buffer += delta
        parts = _SENTENCE_END.split(self._buffer)
        if len(parts) <= 1:
            return None
        complete, self._buffer = parts[:-1], parts[-1]
        out: list[str] = []
        for sentence in complete:
            released = self._release(sentence)
            if released is None:
                return " ".join(out) if out else None
            out.append(released)
        return " ".join(out) + " "

    def flush(self) -> str | None:
        """End of stream: screen and release whatever remains buffered."""
        if self.tripped or not self._buffer.strip():
            return None
        remaining, self._buffer = self._buffer, ""
        return self._release(remaining)
