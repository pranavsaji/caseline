"""Pydantic schemas for the Phase 0 backend API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QualifyRequest(BaseModel):
    incident_date: str = Field(description="Incident date, ISO format (YYYY-MM-DD)")
    injury_type: str
    in_treatment: bool
    has_insurance: bool


class QualifyResponse(BaseModel):
    decision: str  # qualified | refer_out | decline
    reasons: list[str]


class ScheduleRequest(BaseModel):
    name: str
    phone: str
    slot_iso: str = Field(description="Requested consult slot, ISO 8601 datetime")


class ScheduleResponse(BaseModel):
    status: str
    consult_id: int


class CMSWriteRequest(BaseModel):
    call_id: str = Field(default="unknown", description="LiveKit room name / call id")
    summary: str
    structured: dict


class CMSWriteResponse(BaseModel):
    status: str
    record_id: int


class TurnMetrics(BaseModel):
    """Per-turn latency sample reported by the voice worker."""

    call_id: str
    speech_id: str
    eou_delay_ms: float = Field(description="End-of-utterance detection delay")
    llm_ttft_ms: float = Field(description="LLM time to first token")
    tts_ttfb_ms: float = Field(description="TTS time to first audio byte")
    total_ms: float = Field(description="eou + llm ttft + tts ttfb")


class CallLatencySummary(BaseModel):
    call_id: str
    turns: int
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None
    within_budget: bool | None = Field(
        default=None, description="True when p95 <= 800 ms (Phase 0 exit criterion)"
    )
