"""Pydantic request/response models for the Phase 1 v1 API."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


# --- dashboard operator accounts (human sign up / log in) ---


class DashboardCredentials(BaseModel):
    email: str
    password: str


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
    scopes: list[str] = Field(
        default_factory=list,
        description="Extra grants, e.g. 'transcripts:raw' for unredacted transcript access",
    )


class CreateTokenResponse(BaseModel):
    token: str


# --- agent config ---


class AgentConfigUpdate(BaseModel):
    script_config: dict | None = None
    routing_rules: dict | None = None
    qualification_rules: dict | None = None
    guardrails: dict | None = None
    voice_id: str | None = None
    llm_config: dict | None = None


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
    # Consent bookkeeping (Phase 2): which policy governed the call.
    consent_state: str | None = None
    two_party_consent: bool | None = None


class TranscriptTurn(BaseModel):
    role: str
    text: str
    ts: str | None = None


class TranscriptRequest(BaseModel):
    turns: list[TranscriptTurn]
    summary: str | None = None
    recording_uri: str | None = None


# --- Phase 3: omnichannel ---


class LeadWebhookRequest(BaseModel):
    """Webform / ad-platform lead submission (the Digital Lead Chaser input)."""

    name: str
    phone: str | None = None
    email: str | None = None
    source: str = "web"  # web | ad
    practice_area: str | None = None
    details: dict = Field(default_factory=dict)
    # TCPA prior express consent, as captured by the form (checkbox + record
    # of what the person agreed to). Without it there is no automated chase.
    sms_consent: bool = False
    consent_source: str | None = None
    preferred_channel: str | None = None  # sms | voice | email


class InboundSMSRequest(BaseModel):
    from_number: str
    body: str
    to_number: str | None = None


class TrackerEnrollRequest(BaseModel):
    name: str
    phone: str
    matter_description: str | None = None
    cadence_days: int = Field(default=14, ge=1, le=90)


class ThreadMessageRequest(BaseModel):
    """Staff-authored outbound message on an open thread. Screened by the same
    guardrail as every automated send before it reaches the client."""

    body: str = Field(min_length=1, max_length=1000)


class CallOutcomeRequest(BaseModel):
    """Manual disposition override on a call — the human correction of what the
    agent recorded (or a disposition for a call the agent never classified)."""

    outcome: str = Field(min_length=1, max_length=60)
    note: str | None = Field(default=None, max_length=500)


class DialRequest(BaseModel):
    """Operator-initiated outbound call. Unlike the automated Digital Lead
    Chaser (which requires prior express consent under TCPA), this is a
    human-triggered call from the dashboard — e.g. a firm calling a partner
    firm or ringing a test number to hear the agent. The endpoint still
    format-checks the number and records the attempt as a `calls` row."""

    to_number: str = Field(description="E.164 destination, e.g. +14155550123")
    agent_id: str | None = Field(
        default=None, description="Agent whose brain runs the call; defaults to the firm's intake agent"
    )
    purpose: str | None = Field(default=None, max_length=200)


class PreviewRequest(BaseModel):
    """Config-studio test-call preview: caller messages + optional unsaved
    config overrides, simulated through the same brain with zero side effects."""

    messages: list[str] = Field(min_length=1, max_length=30)
    contact_name: str = "Preview Caller"
    script_config: dict | None = None
    qualification_rules: dict | None = None
    guardrails: dict | None = None


# --- Phase 4: differentiation ---


class VoiceProfileCreate(BaseModel):
    """Branded/cloned voice request. Consent is structural: the API refuses
    without it and the schema CHECK refuses again.

    The audio sample arrives one of two ways: ``sample_uri`` (a pre-hosted
    http(s) URL) or ``sample_data`` (an inline ``data:audio/…;base64,…`` URI
    from an in-browser recording or file upload). Exactly one is required."""

    name: str
    sample_uri: str | None = None
    sample_data: str | None = None
    consent_confirmed: bool = False
    description: str | None = None

    @model_validator(mode="after")
    def _require_a_sample(self) -> "VoiceProfileCreate":
        if not self.sample_uri and not self.sample_data:
            raise ValueError("provide sample_uri (http(s) URL) or sample_data (uploaded/recorded audio)")
        return self


class AssignVoiceRequest(BaseModel):
    """Point the agent at a voice. Either a ready cloned profile
    (``voice_profile_id``) or a provider preset/library voice id
    (``voice_id``, a UUID). Exactly one is required."""

    voice_profile_id: str | None = None
    voice_id: str | None = None

    @model_validator(mode="after")
    def _require_one(self) -> "AssignVoiceRequest":
        if not self.voice_profile_id and not self.voice_id:
            raise ValueError("provide voice_profile_id (cloned) or voice_id (preset)")
        return self


class LeadReviewRequest(BaseModel):
    """Attorney verdict on a lead — the qualification-tuning signal."""

    verdict: str  # accepted | rejected
    reviewer: str | None = None
    reason: str | None = None


class ReferralPartnerCreate(BaseModel):
    name: str
    practice_areas: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    contact_email: str | None = None
    contact_phone: str | None = None
    notes: str | None = None


class ReferralSendRequest(BaseModel):
    """Human send action: client PII leaves the system only here, and only
    with the client's consent recorded."""

    client_consent: bool = False


class ReferralStatusRequest(BaseModel):
    status: str  # accepted | declined


class TurnMetricsV1(BaseModel):
    call_id: str
    speech_id: str
    eou_delay_ms: float
    llm_ttft_ms: float
    tts_ttfb_ms: float
    total_ms: float
    # Supplementary per-stage timings (nullable; not part of total_ms):
    #  - stt_ms: STT-finalization slice of the EOU delay (transcription delay).
    #  - guardrail_ms: regex guardrail screening time between LLM and TTS.
    stt_ms: float | None = None
    guardrail_ms: float | None = None
    # Which providers actually served the turn (failover makes this dynamic);
    # lets latency dashboards slice by provider (Phase 2 Workstream D).
    stt_provider: str | None = None
    llm_provider: str | None = None
    tts_provider: str | None = None
