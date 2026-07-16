"""Per-firm agent configuration.

Replaces the Phase 0 hardcoded prompt. Everything a voice worker needs to
run a firm's calls — script, qualification rules, routing, business hours,
guardrails — lives in jsonb on the ``agents`` row, is validated into typed
models here, compiled into runtime instructions, and cached in the session
store so call start never waits on Postgres.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from api.platform.db import Database
from api.platform.session_state import SessionStore

logger = logging.getLogger("caseline.orchestration.config")

CONFIG_CACHE_TTL_SECONDS = 60

DEFAULT_SCRIPT_TEMPLATE = (
    "You are {agent_name}, the AI intake receptionist for {firm_name}, a "
    "{practice_area} law firm. Warm, concise, human — short spoken sentences, "
    "no lists, no jargon. {recording_disclosure}"
    "Greet the caller, find out if they have a potential case, and collect: "
    "incident date, injury type, whether they are receiving treatment, and "
    "insurance status. Convert any date the caller gives you to ISO format "
    "(YYYY-MM-DD) before calling tools. You do NOT give legal advice, quote "
    "fees, or predict outcomes — if asked, say an attorney will cover that in "
    "the consultation. Once you have the four facts, call qualify_lead. If "
    "qualified, offer to book a consultation and call schedule_consult with "
    "the caller's name, phone number, and chosen slot. If the decision is "
    "refer_out or decline, be kind, explain the firm may not be the right "
    "fit, and take a message with take_message. If the caller asks for a "
    "human or is upset, call transfer_to_human. If the caller is an insurance "
    "adjuster, existing client, or spam, be polite and take a message. Before "
    "ending any call, call write_to_cms with a short summary and the "
    "structured facts you collected. Never invent facts the caller did not "
    "state.{extra_instructions}"
)

RECORDING_DISCLOSURE_LINE = (
    "Early in the call, naturally mention that you are an AI assistant and "
    "the call may be recorded for quality purposes. "
)


class ScriptConfig(BaseModel):
    template: str = DEFAULT_SCRIPT_TEMPLATE
    greeting: str = "Greet the caller warmly, say you're with the firm's intake team, and ask how you can help."
    practice_area: str = "personal injury"
    recording_disclosure: bool = True
    extra_instructions: str = ""


class QualificationRules(BaseModel):
    statute_of_limitations_days: int = 730
    refer_out_injuries: list[str] = Field(
        default_factory=lambda: ["minor", "none", "no injury", "property damage only"]
    )


class RoutingRules(BaseModel):
    transfer_number: str | None = None
    after_hours_behavior: str = "take_message"  # take_message | voicemail
    notify_sms_number: str | None = None


class GuardrailSettings(BaseModel):
    extra_blocked_patterns: list[str] = Field(default_factory=list)
    deflection_line: str = (
        "That's exactly the kind of question our attorneys will answer in your "
        "consultation — I can't speak to it myself."
    )


class AgentConfig(BaseModel):
    firm_id: str
    agent_id: str
    firm_name: str
    agent_name: str
    role: str = "intaker"
    voice_id: str | None = None
    timezone: str = "America/Chicago"
    business_hours: dict[str, list[list[str]]] = Field(default_factory=dict)
    script: ScriptConfig = Field(default_factory=ScriptConfig)
    qualification: QualificationRules = Field(default_factory=QualificationRules)
    routing: RoutingRules = Field(default_factory=RoutingRules)
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)

    def instructions(self) -> str:
        """Compile the runtime system prompt from the firm's script config."""
        disclosure = RECORDING_DISCLOSURE_LINE if self.script.recording_disclosure else ""
        extra = f" {self.script.extra_instructions}" if self.script.extra_instructions else ""
        return self.script.template.format(
            agent_name=self.agent_name,
            firm_name=self.firm_name,
            practice_area=self.script.practice_area,
            recording_disclosure=disclosure,
            extra_instructions=extra,
        )

    def is_open(self, now: datetime | None = None) -> bool:
        """Business-hours check. Empty config means always open (24/7 intake
        is the product's whole point; hours only gate live transfer)."""
        if not self.business_hours:
            return True
        now = now.astimezone(ZoneInfo(self.timezone)) if now else datetime.now(ZoneInfo(self.timezone))
        day_key = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
        windows = self.business_hours.get(day_key, [])
        hhmm = now.strftime("%H:%M")
        return any(start <= hhmm < end for start, end in windows)


def _cache_key(firm_id: str, role: str) -> str:
    return f"agent_config:{firm_id}:{role}"


def load_agent_config(
    db: Database, store: SessionStore, firm_id: str, role: str = "intaker"
) -> AgentConfig | None:
    """Load (cached) the firm's agent config for a role. Cache TTL is short
    and writes invalidate explicitly, so config edits reach the next call in
    seconds without a worker restart."""
    cached = store.get(_cache_key(firm_id, role))
    if cached:
        return AgentConfig.model_validate(cached)
    with db.firm(firm_id) as conn:
        row = conn.execute(
            "SELECT a.id AS agent_id, a.name AS agent_name, a.role, a.voice_id,"
            "       a.script_config, a.routing_rules, a.qualification_rules, a.guardrails,"
            "       f.name AS firm_name, f.timezone, f.business_hours"
            " FROM agents a JOIN firms f ON f.id = a.firm_id"
            " WHERE a.firm_id = %s AND a.role = %s ORDER BY a.created_at LIMIT 1",
            (firm_id, role),
        ).fetchone()
    if row is None:
        return None
    config = AgentConfig(
        firm_id=firm_id,
        agent_id=str(row["agent_id"]),
        firm_name=row["firm_name"],
        agent_name=row["agent_name"],
        role=row["role"],
        voice_id=row["voice_id"],
        timezone=row["timezone"],
        business_hours=row["business_hours"] or {},
        script=ScriptConfig.model_validate(row["script_config"] or {}),
        qualification=QualificationRules.model_validate(row["qualification_rules"] or {}),
        routing=RoutingRules.model_validate(row["routing_rules"] or {}),
        guardrails=GuardrailSettings.model_validate(row["guardrails"] or {}),
    )
    store.set(_cache_key(firm_id, role), config.model_dump(), ttl_seconds=CONFIG_CACHE_TTL_SECONDS)
    return config


def invalidate_agent_config(store: SessionStore, firm_id: str, role: str = "intaker") -> None:
    store.delete(_cache_key(firm_id, role))


def update_agent_config(
    db: Database,
    store: SessionStore,
    firm_id: str,
    agent_id: str,
    *,
    script_config: dict | None = None,
    routing_rules: dict | None = None,
    qualification_rules: dict | None = None,
    guardrails: dict | None = None,
    voice_id: str | None = None,
) -> bool:
    """Validated partial update of an agent's jsonb config. Returns False if
    the agent does not belong to the firm (RLS makes it invisible)."""
    # Validate before persisting — a bad config must never reach a live call.
    if script_config is not None:
        ScriptConfig.model_validate(script_config)
    if routing_rules is not None:
        RoutingRules.model_validate(routing_rules)
    if qualification_rules is not None:
        QualificationRules.model_validate(qualification_rules)
    if guardrails is not None:
        GuardrailSettings.model_validate(guardrails)

    sets, params = ["updated_at = now()"], []
    for column, value in (
        ("script_config", script_config),
        ("routing_rules", routing_rules),
        ("qualification_rules", qualification_rules),
        ("guardrails", guardrails),
    ):
        if value is not None:
            sets.append(f"{column} = %s")
            params.append(json.dumps(value))
    if voice_id is not None:
        sets.append("voice_id = %s")
        params.append(voice_id)

    with db.firm(firm_id) as conn:
        row = conn.execute(
            f"UPDATE agents SET {', '.join(sets)} WHERE id = %s RETURNING role",
            (*params, agent_id),
        ).fetchone()
    if row is None:
        return False
    invalidate_agent_config(store, firm_id, row["role"])
    return True
