"""Phase 2 inline guardrail classifier: catches paraphrased violations the
regex screen misses, stays inside the <100 ms hot-path budget (measured in
microseconds), and never blocks routine intake speech."""

import time

from api.orchestration.classifier import LexicalGuardrailClassifier
from api.orchestration.guardrails import GuardrailScreen

classifier = LexicalGuardrailClassifier()

# Paraphrases that dodge the Phase 1 regexes but must still trip.
VIOLATIONS = [
    ("In my opinion the other driver bears full responsibility, so a lawsuit makes sense.",
     "legal_advice"),
    ("Honestly, you'd want to reject that settlement offer and file a claim instead.",
     "legal_advice"),
    ("Our contingency arrangement means we keep 33 percent of whatever we collect.",
     "fee_quote"),
    ("Typically the retainer runs $5,000 upfront for a case like yours.", "fee_quote"),
    ("I can assure you, with injuries like these you'll definitely receive a large payout.",
     "outcome_guarantee"),
    ("Between us, your claim is worth at least six figures.", "outcome_guarantee"),
]

# Routine intake speech that must NEVER trip.
SAFE = [
    "Can you tell me the date of the incident and what injuries you had?",
    "I'm so sorry to hear about your accident — are you receiving treatment now?",
    "An attorney will discuss fees and next steps in your consultation.",
    "The consultation is free and there's no obligation.",
    "Let me book you for Tuesday at 10am with attorney Reyes.",
    "Do you know whether the other driver had insurance?",
    "Our office is at the corner of Fifth and Main, and parking is free.",
    "I'll send you a text confirming your appointment.",
]


def test_paraphrased_violations_trip_the_classifier():
    for text, expected_category in VIOLATIONS:
        verdict = classifier.classify(text)
        assert verdict is not None, f"should have tripped: {text!r}"
        assert verdict.category == expected_category, (text, verdict)


def test_routine_intake_speech_passes():
    for text in SAFE:
        verdict = classifier.classify(text)
        assert verdict is None, f"false positive on {text!r}: {verdict}"


def test_verdict_is_auditable():
    verdict = classifier.classify(VIOLATIONS[0][0])
    assert verdict.score >= 3.0
    assert verdict.features  # names the cues that fired


def test_classifier_layers_into_guardrail_screen():
    screen = GuardrailScreen()
    verdict = screen.screen(VIOLATIONS[0][0])
    assert not verdict.allowed
    assert verdict.category == "legal_advice"
    assert "classifier" in verdict.matched


def test_regex_layer_still_first():
    """Exact phrasings keep tripping via the regex layer (cheaper, clearer)."""
    screen = GuardrailScreen()
    verdict = screen.screen("You definitely have a strong case here.")
    assert not verdict.allowed
    assert "classifier" not in (verdict.matched or "")


def test_hot_path_budget_p95_under_5ms():
    """Plan budget is <100 ms; assert 20x headroom on full sentences."""
    screen = GuardrailScreen()
    sentences = [t for t, _ in VIOLATIONS] + SAFE
    timings = []
    for i in range(300):
        s = sentences[i % len(sentences)]
        t0 = time.perf_counter()
        screen.screen(s)
        timings.append(time.perf_counter() - t0)
    timings.sort()
    p95 = timings[int(len(timings) * 0.95)]
    assert p95 < 0.005, f"p95 {p95 * 1000:.3f} ms exceeds 5 ms"
