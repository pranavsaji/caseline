"""Per-firm agent config: load, compile, cache invalidation, validation."""

from datetime import datetime
from zoneinfo import ZoneInfo

from api.orchestration.config import AgentConfig


def test_agent_config_endpoint_compiles_firm_instructions(v1_client, firm):
    r = v1_client.get("/v1/agent-config", headers=firm["headers"])
    assert r.status_code == 200
    config = r.json()
    assert config["firm_name"] == "Bluebonnet Injury Law"
    instructions = config["instructions"]
    assert "Bluebonnet Injury Law" in instructions
    assert "personal injury" in instructions
    assert "AI assistant" in instructions  # recording/AI disclosure line
    assert "legal advice" in instructions
    assert config["routing"]["transfer_number"] == "+15125550199"


def test_config_update_reaches_next_call_via_cache_invalidation(v1_client, firm):
    # Prime the cache.
    before = v1_client.get("/v1/agent-config", headers=firm["headers"]).json()
    assert before["qualification"]["statute_of_limitations_days"] == 730

    r = v1_client.put(
        f"/v1/agents/{firm['agent_id']}/config",
        json={"qualification_rules": {"statute_of_limitations_days": 365}},
        headers=firm["headers"],
    )
    assert r.status_code == 200

    after = v1_client.get("/v1/agent-config", headers=firm["headers"]).json()
    assert after["qualification"]["statute_of_limitations_days"] == 365
    # untouched sections keep defaults
    assert after["script"]["practice_area"] == "personal injury"


def test_llm_choice_from_studio_reaches_the_agent(v1_client, firm):
    # The full model-picker path: Studio PUTs llm_config, and the /v1/agent-config
    # the voice worker fetches on every call must report that exact spec under
    # `llm.providers` — the value agent.py hands to build_llm(). Empty by default
    # (worker env fallback); non-empty once chosen.
    before = v1_client.get("/v1/agent-config", headers=firm["headers"]).json()
    assert before["llm"]["providers"] == ""  # default -> worker CASELINE_LLM_PROVIDERS

    r = v1_client.put(
        f"/v1/agents/{firm['agent_id']}/config",
        json={"llm_config": {"providers": "anthropic:claude-haiku-4-5"}},
        headers=firm["headers"],
    )
    assert r.status_code == 200

    after = v1_client.get("/v1/agent-config", headers=firm["headers"]).json()
    assert after["llm"]["providers"] == "anthropic:claude-haiku-4-5"


def test_invalid_config_is_rejected_before_persisting(v1_client, firm):
    r = v1_client.put(
        f"/v1/agents/{firm['agent_id']}/config",
        json={"qualification_rules": {"statute_of_limitations_days": "soon"}},
        headers=firm["headers"],
    )
    assert r.status_code == 422
    # and the stored config is unchanged
    config = v1_client.get("/v1/agent-config", headers=firm["headers"]).json()
    assert config["qualification"]["statute_of_limitations_days"] == 730


def test_cannot_edit_another_firms_agent(v1_client, firm, second_firm):
    r = v1_client.put(
        f"/v1/agents/{firm['agent_id']}/config",
        json={"script_config": {"practice_area": "hijacked"}},
        headers=second_firm["headers"],
    )
    assert r.status_code == 404  # RLS: firm B cannot even see firm A's agent


def test_business_hours_gate():
    config = AgentConfig(
        firm_id="f",
        agent_id="a",
        firm_name="F",
        agent_name="A",
        timezone="America/Chicago",
        business_hours={"mon": [["09:00", "17:00"]], "tue": [["09:00", "12:00"]]},
    )
    tz = ZoneInfo("America/Chicago")
    monday_10am = datetime(2026, 7, 13, 10, 0, tzinfo=tz)
    monday_8pm = datetime(2026, 7, 13, 20, 0, tzinfo=tz)
    sunday = datetime(2026, 7, 12, 10, 0, tzinfo=tz)
    assert config.is_open(monday_10am) is True
    assert config.is_open(monday_8pm) is False
    assert config.is_open(sunday) is False


def test_empty_business_hours_means_always_open():
    config = AgentConfig(firm_id="f", agent_id="a", firm_name="F", agent_name="A")
    assert config.is_open() is True
