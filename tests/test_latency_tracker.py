"""TurnLatencyTracker tests: turn stitching by speech_id and p50/p95 math."""

from agent.latency import TurnLatencyTracker


def test_turn_completes_only_when_all_stages_report():
    tracker = TurnLatencyTracker(call_id="c1")
    assert tracker.on_eou("s1", 0.15) is None
    assert tracker.on_llm("s1", 0.20) is None
    turn = tracker.on_tts("s1", 0.08)
    assert turn is not None
    assert turn.total_ms == 430.0
    assert tracker.completed == [turn]


def test_stage_order_does_not_matter():
    tracker = TurnLatencyTracker(call_id="c1")
    tracker.on_tts("s1", 0.08)
    tracker.on_eou("s1", 0.15)
    turn = tracker.on_llm("s1", 0.20)
    assert turn is not None and turn.complete


def test_interleaved_turns_are_kept_separate():
    # Barge-in / preemptive generation can interleave metrics from two turns.
    tracker = TurnLatencyTracker(call_id="c1")
    tracker.on_eou("s1", 0.10)
    tracker.on_eou("s2", 0.30)
    tracker.on_llm("s2", 0.25)
    tracker.on_llm("s1", 0.20)
    t1 = tracker.on_tts("s1", 0.05)
    t2 = tracker.on_tts("s2", 0.10)
    assert t1.speech_id == "s1" and t1.total_ms == 350.0
    assert t2.speech_id == "s2" and t2.total_ms == 650.0


def test_summary_percentiles_and_budget():
    tracker = TurnLatencyTracker(call_id="c1")
    for i, total_s in enumerate([0.4] * 19 + [1.3]):
        sid = f"s{i}"
        tracker.on_eou(sid, total_s / 2)
        tracker.on_llm(sid, total_s / 4)
        tracker.on_tts(sid, total_s / 4)
    summary = tracker.summary()
    assert summary["turns"] == 20
    assert summary["p50_ms"] == 400.0
    assert summary["p95_ms"] <= 800.0
    assert summary["within_budget"] is True
    assert summary["max_ms"] == 1300.0


def test_summary_empty_call():
    assert TurnLatencyTracker(call_id="c1").summary() == {"call_id": "c1", "turns": 0}
