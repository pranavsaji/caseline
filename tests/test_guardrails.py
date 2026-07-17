"""Guardrail output filter: legal advice, fee quotes, outcome guarantees."""

import time

from api.orchestration.guardrails import (
    FunctionCallStripper,
    GuardrailScreen,
    StreamGuard,
)

SCREEN = GuardrailScreen()


def _strip(deltas: list[str]) -> str:
    s = FunctionCallStripper()
    return "".join(s.feed(d) for d in deltas) + s.flush()


def test_stripper_removes_emitted_tool_call_text():
    # A model that writes a tool call as content instead of calling it natively.
    out = _strip(['Sure, let me help. ', '<function=qualify_lead>{"injury":"x"}</function>', ' Done.'])
    assert "<function" not in out and "qualify_lead" not in out
    assert "Sure, let me help." in out and "Done." in out


def test_stripper_handles_tags_split_across_deltas():
    # Opening tag, JSON, and closer arrive in separate deltas.
    out = _strip(['Booking now. <func', 'tion=schedule_consult>{"slot":', '"2pm"}</func', 'tion> All set.'])
    assert "<function" not in out and "schedule_consult" not in out
    assert "Booking now." in out and "All set." in out


def test_stripper_handles_bare_function_closer_and_multiple_spans():
    out = _strip(['A <function=a>{}</function> B <function=end_call><function> C'])
    assert out.replace(" ", "") == "ABC".replace(" ", "") or ("A" in out and "B" in out and "C" in out)
    assert "<function" not in out


def test_stripper_leaves_normal_speech_untouched():
    text = "I understand. Could you tell me your name and what happened?"
    assert _strip([text]) == text
    # A dangling partial tag at end of stream is dropped, not leaked.
    assert "<function" not in _strip(["All good. <func"])


def test_legal_advice_is_blocked():
    for text in [
        "In my opinion you should sue the other driver right away.",
        "You definitely have a strong case here.",
        "You are entitled to compensation under Texas law.",
        "The other driver is clearly at fault, so don't worry.",
        "Don't talk to their insurance company before we do.",
    ]:
        verdict = SCREEN.screen(text)
        assert not verdict.allowed, text
        assert verdict.category == "legal_advice", text


def test_fee_quotes_are_blocked():
    for text in [
        "Our fee is thirty-three percent of the settlement.",
        "We take 33% if we win.",
        "No fee unless we win!",
        "The retainer is $5,000 to start.",
    ]:
        verdict = SCREEN.screen(text)
        assert not verdict.allowed, text
        assert verdict.category == "fee_quote", text


def test_outcome_guarantees_are_blocked():
    for text in [
        "I guarantee you'll be happy with the result.",
        "You will win this case.",
        "Your case is worth at least six figures.",
        "You could receive $100,000 or more.",
    ]:
        verdict = SCREEN.screen(text)
        assert not verdict.allowed, text
        assert verdict.category == "outcome_guarantee", text


def test_normal_intake_speech_passes():
    for text in [
        "I'm so sorry to hear about your accident. When did it happen?",
        "Are you currently receiving medical treatment for the injury?",
        "An attorney will cover fees and what your case might look like in the consultation.",
        "Great — I have you down for Tuesday at 2 PM with attorney Reyes.",
        "Was any insurance involved, either yours or the other driver's?",
    ]:
        assert SCREEN.screen(text).allowed, text


def test_firm_extra_blocklist():
    screen = GuardrailScreen(extra_blocked_patterns=[r"\bfree consultation\b"])
    assert not screen.screen("We offer a free consultation today!").allowed
    assert screen.screen("We offer a consultation today!").allowed


def test_stream_guard_releases_safe_sentences():
    guard = StreamGuard(SCREEN, "deflection.")
    out = []
    for delta in ["Hello there. ", "How can I ", "help you today? ", "Take care"]:
        released = guard.feed(delta)
        if released:
            out.append(released)
    tail = guard.flush()
    if tail:
        out.append(tail)
    assert guard.tripped is None
    assert "".join(out).replace("  ", " ").strip() == "Hello there. How can I help you today? Take care"


def test_stream_guard_trips_mid_stream_and_stops():
    guard = StreamGuard(SCREEN, "deflection.")
    released_before = guard.feed("Thanks for asking. You will win this case, I know it. ")
    assert guard.tripped is not None
    assert guard.tripped.category == "outcome_guarantee"
    assert released_before == "Thanks for asking."  # the safe sentence still speaks
    assert guard.feed("More text after the violation.") is None
    assert guard.flush() is None


def test_stream_guard_screens_the_final_partial_sentence():
    guard = StreamGuard(SCREEN, "deflection.")
    assert guard.feed("Sure — our fee is 40%") is None  # no sentence boundary yet
    assert guard.flush() is None  # flush screens the remainder
    assert guard.tripped is not None
    assert guard.tripped.category == "fee_quote"


def test_screen_is_fast_enough_for_the_hot_path():
    sentence = "I'm sorry to hear that — when did the incident happen exactly?"
    start = time.perf_counter()
    for _ in range(1000):
        SCREEN.screen(sentence)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 200, f"1000 screens took {elapsed_ms:.1f} ms"  # ~µs each
