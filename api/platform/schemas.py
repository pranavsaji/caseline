"""Pydantic request/response models for the Phase 1 v1 API."""

from __future__ import annotations

from pydantic import BaseModel, Field


# --- admin / onboarding ---


class CreateFirmRequest(BaseModel):
    name: str
    timezone: str = "America/Chicago"
    business_hours: dict[str, list[list[str]]] = Field(default_factory=dict)
    cms_provider: str = "mock"
    cms_credentials: dict | None = None
    practice_area: str = "personal injury"
    agent_name: str = "Caseline"
    transfer_number: str | None = None


class CreateFirmResponse(BaseModel):
    firm_id: str
    agent_id: str
    token: str = Field(description="Service token — shown exactly once, store it now")


class CreateTokenRequest(BaseModel):
    name: str = "default"


class CreateTokenResponse(BaseModel):
    token: str


# --- agent config ---


class AgentConfigUpdate(BaseModel):
    script_config: dict | None = None
    routing_rules: dict | None = None
    qualification_rules: dict | None = None
    guardrails: dict | None = None
    voice_id: str | None = None


# --- tools ---


class LookupCallerRequest(BaseModel):
    phone: str


class ToolQualifyRequest(BaseModel):
    call_id: str
    incident_date: str
    injury_type: str
    in_treatment: bool
    has_insurance: bool


class ToolScheduleRequest(BaseModel):
    call_id: str
    name: str
    phone: str
    slot_iso: str
    idempotency_key: str | None = None


class TransferRequest(BaseModel):
    call_id: str
    reason: str


class SendSMSRequest(BaseModel):
    call_id: str
    to: str
    body: str


class TakeMessageRequest(BaseModel):
    call_id: str
    caller_name: str
    phone: str
    body: str


# --- calls / transcripts ---


class CompleteCallRequest(BaseModel):
    call_id: str
    summary: str
    structured: dict
    outcome: str | None = None
    caller_type: str | None = None
    from_number: str | None = None


class TranscriptTurn(BaseModel):
    role: str
    text: str
    ts: str | None = None


class TranscriptRequest(BaseModel):
    turns: list[TranscriptTurn]
    summary: str | None = None
    recording_uri: str | None = None


class TurnMetricsV1(BaseModel):
    call_id: str
    speech_id: str
    eou_delay_ms: float
    llm_ttft_ms: float
    tts_ttfb_ms: float
    total_ms: float
