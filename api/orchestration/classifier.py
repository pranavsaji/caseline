"""Inline guardrail classifier (Phase 2 Workstream C).

The Phase 1 regex screen only blocks exact phrasings; this layer scores a
sentence on weighted lexical features per violation category, so paraphrases
("in my view the other driver bears responsibility, a lawsuit makes sense")
trip the guard without a literal pattern hit.

Design constraints, in priority order:
  1. Hot path: must run per sentence between LLM and TTS. Budget <100 ms;
     this implementation measures in microseconds (perf-tested).
  2. Deterministic and auditable: every trip names the category, the score,
     and the features that fired — a compliance reviewer can replay it.
  3. Swappable: ``GuardrailClassifier`` is a Protocol; a distilled ML model
     can replace the lexical scorer behind the same seam without touching
     the streaming filter.

Scoring: features are (regex, weight); a category trips when its summed
weight for one sentence reaches THRESHOLD. Single weak cues ("fee", "case")
never trip alone — violations need a load-bearing cue or a combination.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

THRESHOLD = 3.0

# weight >= 3.0: unambiguous violation on its own.
# weight 1.0-2.0: contributing cue; needs company to trip.
_FEATURES: dict[str, list[tuple[str, float]]] = {
    "legal_advice": [
        (r"\byou (?:should|need to|must|ought to|'d want to)\b", 1.5),
        (r"\b(?:sue|lawsuit|file (?:a )?(?:suit|claim|charges))\b", 1.5),
        (r"\b(?:liable|liability|at fault|negligen\w+|bears? (?:the )?responsib\w+)\b", 2.0),
        (r"\bmy (?:advice|opinion|recommendation)\b", 2.0),
        (r"\b(?:strong|solid|winning|great|good|clear-cut) (?:case|claim)\b", 3.0),
        (r"\bentitled to (?:compensation|damages|recover)\b", 3.0),
        (r"\b(?:accept|reject|sign|refuse)\b.{0,30}\b(?:offer|settlement|release)\b", 2.0),
        (r"\bstatute of limitations\b", 1.5),
        (r"\b(?:don'?t|do not|avoid) (?:talk|speak|give a statement)\b.{0,40}\binsurance\b", 3.0),
        (r"\blegal(?:ly)?\b", 1.0),
        (r"\bmakes sense\b", 1.0),
    ],
    "fee_quote": [
        (r"\b(?:fee|fees|retainer|rate)\b", 1.5),
        (r"\bcontingency\b", 1.5),
        (r"(?:\$\s?\d[\d,]*|\d{1,2}\s?(?:%|percent))", 2.0),
        (r"\bwe (?:charge|take|keep|bill|collect)\b", 2.0),
        (r"\b(?:costs? you|out of pocket|upfront)\b", 1.5),
        (r"\bno fee unless\b", 3.0),
        (r"\bfree(?: of charge)?\b", -2.0),  # "the consultation is free" is fine
    ],
    "outcome_guarantee": [
        (r"\b(?:guarantee[ds]?|promise[ds]?|assure[ds]?)\b", 2.5),
        (r"\byou (?:will|'ll|are going to) (?:win|prevail|receive|get|recover|be awarded)\b", 3.0),
        (r"\b(?:definitely|certainly|no doubt|for sure)\b", 1.5),
        (r"\b(?:win|winning|victory|payout|settlement|compensation)\b", 1.0),
        (r"\b(?:case|claim) is worth\b", 3.0),
        (r"\balways win\b|\bnever lost?\b", 3.0),
    ],
}


@dataclass(frozen=True)
class ClassifierVerdict:
    category: str
    score: float
    features: tuple[str, ...]  # the feature patterns that fired, for audit


class GuardrailClassifier(Protocol):
    """The seam a future ML classifier implements."""

    def classify(self, text: str) -> ClassifierVerdict | None: ...


class LexicalGuardrailClassifier:
    """Weighted-feature scorer. Compile once; classify per sentence."""

    def __init__(self, threshold: float = THRESHOLD):
        self._threshold = threshold
        self._compiled: dict[str, list[tuple[re.Pattern[str], float, str]]] = {
            category: [(re.compile(p, re.IGNORECASE), w, p) for p, w in feats]
            for category, feats in _FEATURES.items()
        }

    def classify(self, text: str) -> ClassifierVerdict | None:
        best: ClassifierVerdict | None = None
        for category, feats in self._compiled.items():
            score = 0.0
            fired: list[str] = []
            for pattern, weight, raw in feats:
                if pattern.search(text):
                    score += weight
                    if weight > 0:
                        fired.append(raw)
            if score >= self._threshold and (best is None or score > best.score):
                best = ClassifierVerdict(category=category, score=score, features=tuple(fired))
        return best
