"""Guardrail output filter: the safety pass between LLM and TTS.

Two layers, both deterministic and both microseconds per sentence:

  1. Regex screen (Phase 1): exact phrasings of the three unforgivables in
     legal intake — legal advice, fee quotes, outcome guarantees.
  2. Inline classifier (Phase 2): weighted lexical scorer that catches
     paraphrases the regexes miss. Runs only when layer 1 passes. Sits
     behind the ``GuardrailClassifier`` seam so a distilled ML model can
     replace it without touching this file. Budget <100 ms; measured in
     microseconds (perf-tested in tests/test_guardrails.py).

Everything here is pure and dependency-free so the voice worker can import
it without dragging in FastAPI or Postgres.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from api.orchestration.classifier import GuardrailClassifier, LexicalGuardrailClassifier

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
    """Compiled screen; construct once per call with the firm's extras.

    ``classifier=None`` disables layer 2 (regex-only, the Phase 1 behavior);
    the default is the inline lexical classifier."""

    extra_blocked_patterns: list[str] = field(default_factory=list)
    classifier: GuardrailClassifier | None = field(
        default_factory=LexicalGuardrailClassifier
    )

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
        if self.classifier is not None:
            verdict = self.classifier.classify(text)
            if verdict is not None:
                return GuardrailVerdict(
                    allowed=False,
                    category=verdict.category,
                    matched=f"classifier(score={verdict.score:g}): "
                    + ", ".join(verdict.features[:3]),
                )
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


_FUNC_OPEN = "<function"
_FUNC_CLOSERS = ("</function>", "<function>")
_MAX_CLOSER = max(len(c) for c in _FUNC_CLOSERS)


class FunctionCallStripper:
    """Delete emitted-as-text tool calls from a streamed response.

    Some models (notably llama-3.x) sometimes write a tool call as literal
    content — ``<function=qualify_lead>{...}</function>`` — instead of using the
    native tool-calling channel. That machinery must never be spoken or shown to
    the caller. This is a streaming filter: once it sees an opening ``<function``
    tag it suppresses everything until a closer (``</function>`` or the bare
    ``<function>`` some models emit), then resumes. It holds back only a short
    tail so a tag split across deltas is still caught. Note: this drops the
    *text*; it does not execute the call — the real fix is a model that tool-calls
    natively (see agent.providers). This is defense-in-depth against a leak."""

    def __init__(self) -> None:
        self._buf = ""
        self._suppressing = False

    @staticmethod
    def _first_closer(s: str) -> tuple[int, int] | None:
        best: tuple[int, int] | None = None
        for c in _FUNC_CLOSERS:
            i = s.find(c)
            if i != -1 and (best is None or i < best[0]):
                best = (i, len(c))
        return best

    @staticmethod
    def _open_tail(s: str) -> int:
        """Length of a suffix of s that is a proper prefix of ``<function``."""
        for k in range(min(len(s), len(_FUNC_OPEN)), 0, -1):
            if s.endswith(_FUNC_OPEN[:k]):
                return k
        return 0

    def feed(self, delta: str) -> str:
        self._buf += delta
        out: list[str] = []
        while self._buf:
            if self._suppressing:
                closer = self._first_closer(self._buf)
                if closer is None:
                    # No complete closer yet; keep only a tail that could be a
                    # partial one and drop the rest of the suppressed region.
                    if len(self._buf) > _MAX_CLOSER - 1:
                        self._buf = self._buf[-(_MAX_CLOSER - 1) :]
                    return "".join(out)
                self._buf = self._buf[closer[0] + closer[1] :]
                self._suppressing = False
            else:
                oi = self._buf.find(_FUNC_OPEN)
                if oi == -1:
                    keep = self._open_tail(self._buf)
                    if keep:
                        out.append(self._buf[:-keep])
                        self._buf = self._buf[-keep:]
                    else:
                        out.append(self._buf)
                        self._buf = ""
                    return "".join(out)
                out.append(self._buf[:oi])
                self._buf = self._buf[oi:]
                self._suppressing = True
        return "".join(out)

    def flush(self) -> str:
        """End of stream: drop a dangling suppressed region or partial tag."""
        if self._suppressing:
            self._buf = ""
            return ""
        out, self._buf = self._buf, ""
        if out.startswith(_FUNC_OPEN) or _FUNC_OPEN.startswith(out):
            return ""
        return out
