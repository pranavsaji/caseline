"""Phase 4 — selective speech-to-speech: the greeting is served by S2S only
behind explicit opt-in, a configured provider, and a measured benchmark
verdict. Everything short of that is the cascaded pipeline, with a reason."""

import json

from agent.s2s import MODE_CASCADED, MODE_S2S, plan_greeting


def test_default_is_cascaded():
    plan = plan_greeting(env={})
    assert plan.mode == MODE_CASCADED
    assert "default" in plan.reason


def test_flag_without_provider_stays_cascaded():
    plan = plan_greeting(env={"CASELINE_S2S_GREETING": "true"})
    assert plan.mode == MODE_CASCADED
    assert "CASELINE_S2S_PROVIDER" in plan.reason


def test_flag_and_provider_without_benchmark_stays_cascaded(tmp_path):
    plan = plan_greeting(
        env={"CASELINE_S2S_GREETING": "true", "CASELINE_S2S_PROVIDER": "openai:gpt-realtime"},
        verdict_path=tmp_path / "missing.json",
    )
    assert plan.mode == MODE_CASCADED
    assert "benchmark" in plan.reason


def test_benchmark_loss_stays_cascaded(tmp_path):
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps({"realism_win": False, "trials": 10}))
    plan = plan_greeting(
        env={"CASELINE_S2S_GREETING": "true", "CASELINE_S2S_PROVIDER": "openai:gpt-realtime"},
        verdict_path=verdict,
    )
    assert plan.mode == MODE_CASCADED


def test_pending_human_review_stays_cascaded(tmp_path):
    # The harness writes realism_win: null until a human listens and judges.
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps({"realism_win": None, "trials": 10}))
    plan = plan_greeting(
        env={"CASELINE_S2S_GREETING": "true", "CASELINE_S2S_PROVIDER": "openai:gpt-realtime"},
        verdict_path=verdict,
    )
    assert plan.mode == MODE_CASCADED


def test_all_three_gates_met_serves_s2s_greeting(tmp_path):
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps({"realism_win": True, "trials": 10}))
    plan = plan_greeting(
        env={"CASELINE_S2S_GREETING": "true", "CASELINE_S2S_PROVIDER": "openai:gpt-realtime"},
        verdict_path=verdict,
    )
    assert plan.mode == MODE_S2S
    assert plan.provider == "openai:gpt-realtime"


def test_corrupt_verdict_file_fails_safe(tmp_path):
    verdict = tmp_path / "verdict.json"
    verdict.write_text("{not json")
    plan = plan_greeting(
        env={"CASELINE_S2S_GREETING": "true", "CASELINE_S2S_PROVIDER": "openai:gpt-realtime"},
        verdict_path=verdict,
    )
    assert plan.mode == MODE_CASCADED
