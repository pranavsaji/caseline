"""Phase 1 v1 API: multi-tenant, token-authed, RLS-scoped.

Route groups:
  /v1/admin/*   — platform onboarding (X-Admin-Token)
  /v1/*         — firm-scoped (Bearer token -> firm_id -> RLS context)

Every tenant query runs through ``db.firm(firm_id)``; there is no code path
from these routes to another firm's rows — the database enforces it, not
this file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from api import tools
from api.compliance.consent import consent_policy
from api.compliance.outbound import help_reply, is_help, is_opt_out, opt_out_confirmation
from api.compliance.redaction import redact_turns
from api.orchestration.config import (
    GuardrailSettings,
    QualificationRules,
    ScriptConfig,
    load_agent_config,
    update_agent_config,
)
from api.orchestration.threads import ThreadEngine, preview_conversation
from api.platform import alerts as platform_alerts
from api.platform import auth
from api.platform import events as platform_events
from api.platform.schemas import (
    AgentConfigUpdate,
    AssignVoiceRequest,
    CallOutcomeRequest,
    CompleteCallRequest,
    CreateFirmRequest,
    CreateFirmResponse,
    CreateTokenRequest,
    CreateTokenResponse,
    DialRequest,
    InboundSMSRequest,
    LeadReviewRequest,
    LeadWebhookRequest,
    LookupCallerRequest,
    PreviewRequest,
    ReferralPartnerCreate,
    ReferralSendRequest,
    ReferralStatusRequest,
    SendSMSRequest,
    TakeMessageRequest,
    ThreadMessageRequest,
    ToolQualifyRequest,
    ToolScheduleRequest,
    TrackerEnrollRequest,
    TranscriptRequest,
    TransferRequest,
    TurnMetricsV1,
    VoiceProfileCreate,
)

logger = logging.getLogger("caseline.api.v1")

router = APIRouter(prefix="/v1")


def _platform(request: Request):
    return request.app.state.platform


def _thread_engine(request: Request) -> ThreadEngine:
    p = _platform(request)
    return ThreadEngine(p.db, p.session_store, p.sms, p.email)


def _tool_ctx(request: Request, firm: auth.AuthedFirm) -> tools.ToolContext:
    p = _platform(request)
    config = load_agent_config(p.db, p.session_store, firm.firm_id)
    if config is None:
        raise HTTPException(status_code=409, detail="Firm has no configured agent")
    return tools.ToolContext(
        db=p.db, store=p.session_store, sms=p.sms, firm_id=firm.firm_id, config=config
    )


# ---------------------------------------------------------------------------
# Admin: onboarding
# ---------------------------------------------------------------------------


@router.post("/admin/firms", response_model=CreateFirmResponse, dependencies=[Depends(auth.require_admin)])
def create_firm(req: CreateFirmRequest, request: Request) -> CreateFirmResponse:
    p = _platform(request)
    credentials_enc = p.cipher.encrypt(req.cms_credentials) if req.cms_credentials else None
    with p.db.admin() as conn:
        firm = conn.execute(
            "INSERT INTO firms (name, timezone, business_hours, cms_provider, cms_credentials_enc)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (
                req.name,
                req.timezone,
                json.dumps(req.business_hours),
                req.cms_provider,
                credentials_enc,
            ),
        ).fetchone()
        agent = conn.execute(
            "INSERT INTO agents (firm_id, name, role, script_config, routing_rules)"
            " VALUES (%s, %s, 'intaker', %s, %s) RETURNING id",
            (
                firm["id"],
                req.agent_name,
                json.dumps({"practice_area": req.practice_area}),
                json.dumps({"transfer_number": req.transfer_number}),
            ),
        ).fetchone()
    token = auth.issue_token(p.db, str(firm["id"]))
    logger.info("firm onboarded: %s (%s)", req.name, firm["id"])
    return CreateFirmResponse(firm_id=str(firm["id"]), agent_id=str(agent["id"]), token=token)


@router.post(
    "/admin/firms/{firm_id}/tokens",
    response_model=CreateTokenResponse,
    dependencies=[Depends(auth.require_admin)],
)
def create_token(firm_id: str, req: CreateTokenRequest, request: Request) -> CreateTokenResponse:
    return CreateTokenResponse(
        token=auth.issue_token(_platform(request).db, firm_id, req.name, scopes=req.scopes)
    )


# ---------------------------------------------------------------------------
# Agent config
# ---------------------------------------------------------------------------


@router.get("/agent-config")
def get_agent_config(
    request: Request,
    role: str = "intaker",
    from_number: str | None = None,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> dict:
    p = _platform(request)
    config = load_agent_config(p.db, p.session_store, firm.firm_id, role)
    if config is None:
        raise HTTPException(status_code=404, detail=f"No {role} agent configured")
    # Per-state consent (Phase 2): when two-party rules may govern the call,
    # the recording disclosure is mandatory — firm config cannot disable it.
    policy = consent_policy(from_number, firm_state=config.script.firm_state)
    if policy.disclosure_required and not config.script.recording_disclosure:
        config = config.model_copy(deep=True)
        config.script.recording_disclosure = True
    return {
        **config.model_dump(),
        "instructions": config.instructions(),
        "consent": {
            "caller_state": policy.caller_state,
            "two_party": policy.two_party,
            "disclosure_required": policy.disclosure_required,
        },
    }


@router.put("/agents/{agent_id}/config")
def put_agent_config(
    agent_id: str,
    req: AgentConfigUpdate,
    request: Request,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> dict:
    p = _platform(request)
    try:
        updated = update_agent_config(
            p.db,
            p.session_store,
            firm.firm_id,
            agent_id,
            script_config=req.script_config,
            routing_rules=req.routing_rules,
            qualification_rules=req.qualification_rules,
            guardrails=req.guardrails,
            voice_id=req.voice_id,
        )
    except ValueError as exc:  # pydantic validation of a bad config
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Typed tools
# ---------------------------------------------------------------------------


@router.post("/tools/lookup_caller")
def tool_lookup_caller(
    req: LookupCallerRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    return tools.lookup_caller(_tool_ctx(request, firm), req.phone)


@router.post("/tools/qualify_lead")
def tool_qualify_lead(
    req: ToolQualifyRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    return tools.qualify_lead(
        _tool_ctx(request, firm),
        call_id=req.call_id,
        incident_date=req.incident_date,
        injury_type=req.injury_type,
        in_treatment=req.in_treatment,
        has_insurance=req.has_insurance,
    )


@router.get("/tools/available_slots")
def tool_available_slots(
    request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    return tools.available_slots(_tool_ctx(request, firm))


@router.post("/tools/schedule_consult")
def tool_schedule_consult(
    req: ToolScheduleRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    try:
        return tools.schedule_consult(
            _tool_ctx(request, firm),
            call_id=req.call_id,
            name=req.name,
            phone=req.phone,
            slot_iso=req.slot_iso,
            idempotency_key=req.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid slot_iso: {exc}") from exc


@router.post("/tools/transfer_to_human")
def tool_transfer_to_human(
    req: TransferRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    return tools.transfer_to_human(_tool_ctx(request, firm), req.call_id, req.reason)


@router.post("/tools/send_sms")
def tool_send_sms(
    req: SendSMSRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    return tools.send_sms(_tool_ctx(request, firm), req.call_id, req.to, req.body)


@router.post("/tools/take_message")
def tool_take_message(
    req: TakeMessageRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    return tools.take_message(
        _tool_ctx(request, firm), req.call_id, req.caller_name, req.phone, req.body
    )


# ---------------------------------------------------------------------------
# Calls, transcripts, metrics
# ---------------------------------------------------------------------------


@router.post("/calls/complete")
def complete_call(
    req: CompleteCallRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    return tools.complete_call(
        _tool_ctx(request, firm),
        call_id=req.call_id,
        summary=req.summary,
        structured=req.structured,
        outcome=req.outcome,
        caller_type=req.caller_type,
        from_number=req.from_number,
        consent_state=req.consent_state,
        two_party_consent=req.two_party_consent,
    )


@router.post("/calls/{call_id}/transcript")
def post_transcript(
    call_id: str,
    req: TranscriptRequest,
    request: Request,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> dict:
    p = _platform(request)
    ctx = _tool_ctx(request, firm)
    turns = [t.model_dump() for t in req.turns]
    with p.db.firm(firm.firm_id) as conn:
        conn.execute(
            "INSERT INTO calls (id, firm_id, agent_id) VALUES (%s, %s, %s)"
            " ON CONFLICT (firm_id, id) DO NOTHING",
            (call_id, firm.firm_id, ctx.config.agent_id),
        )
        # Redacted copy is computed at write time so the default read path
        # never has to touch raw turns (Phase 2 redaction pipeline).
        conn.execute(
            "INSERT INTO transcripts (firm_id, call_id, turns, turns_redacted, summary)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (firm_id, call_id) DO UPDATE SET turns = EXCLUDED.turns,"
            " turns_redacted = EXCLUDED.turns_redacted,"
            " summary = COALESCE(EXCLUDED.summary, transcripts.summary)",
            (firm.firm_id, call_id, json.dumps(turns), json.dumps(redact_turns(turns)), req.summary),
        )
        if req.recording_uri:
            conn.execute(
                "UPDATE calls SET recording_uri = %s WHERE id = %s",
                (req.recording_uri, call_id),
            )
        # Roll turn latency up onto the call row (the dashboard's per-call SLO view).
        conn.execute(
            "UPDATE calls SET latency_p50_ms = s.p50, latency_p95_ms = s.p95"
            " FROM (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY total_ms) AS p50,"
            "              percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms) AS p95"
            "       FROM turn_metrics WHERE call_id = %s) s"
            " WHERE calls.id = %s AND s.p50 IS NOT NULL",
            (call_id, call_id),
        )
    return {"status": "saved", "turns": len(turns)}


@router.post("/metrics/turn")
def post_turn_metrics(
    req: TurnMetricsV1, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        conn.execute(
            "INSERT INTO turn_metrics"
            " (firm_id, call_id, speech_id, eou_delay_ms, stt_ms, llm_ttft_ms, tts_ttfb_ms,"
            "  guardrail_ms, total_ms, stt_provider, llm_provider, tts_provider)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                firm.firm_id,
                req.call_id,
                req.speech_id,
                req.eou_delay_ms,
                req.stt_ms,
                req.llm_ttft_ms,
                req.tts_ttfb_ms,
                req.guardrail_ms,
                req.total_ms,
                req.stt_provider,
                req.llm_provider,
                req.tts_provider,
            ),
        )
    return {"status": "recorded"}


@router.get("/metrics/calls/{call_id}")
def call_latency_summary(
    call_id: str, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        row = conn.execute(
            "SELECT count(*) AS turns,"
            "       percentile_cont(0.5) WITHIN GROUP (ORDER BY total_ms) AS p50,"
            "       percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms) AS p95,"
            "       max(total_ms) AS max_ms"
            " FROM turn_metrics WHERE call_id = %s",
            (call_id,),
        ).fetchone()
    if not row or row["turns"] == 0:
        return {"call_id": call_id, "turns": 0, "p50_ms": None, "p95_ms": None,
                "max_ms": None, "within_budget": None}
    return {
        "call_id": call_id,
        "turns": row["turns"],
        "p50_ms": round(row["p50"], 1),
        "p95_ms": round(row["p95"], 1),
        "max_ms": round(row["max_ms"], 1),
        "within_budget": row["p95"] <= 800.0,
    }


# ---------------------------------------------------------------------------
# Dashboard reads
# ---------------------------------------------------------------------------


_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def _normalize_e164(raw: str) -> str | None:
    """Best-effort coercion of a loosely typed number to E.164.

    Accepts already-E.164 input, and forgives common US/NANP formats that
    operators paste from a screen: spaces, dashes, parens, a leading "1", or a
    bare 10-digit number (assumed US, gets +1). Returns None if it can't be
    confidently normalized so the caller can 422.
    """
    s = raw.strip()
    if not s:
        return None
    if s.startswith("+"):
        digits = re.sub(r"\D", "", s)
        candidate = "+" + digits
    else:
        digits = re.sub(r"\D", "", s)
        if len(digits) == 10:
            candidate = "+1" + digits
        elif len(digits) == 11 and digits.startswith("1"):
            candidate = "+" + digits
        else:
            candidate = "+" + digits
    return candidate if _E164.match(candidate) else None


@router.post("/calls/dial")
def dial_call(
    req: DialRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Operator-initiated outbound call from the dashboard.

    Reuses the same transport as the Digital Lead Chaser: create a LiveKit
    room, record a `calls` row, emit `call.outbound_requested`, and hand the
    dial to the configured dialer. The agent worker joins the room and runs
    the firm's intake brain exactly like an inbound call. When no SIP
    outbound trunk is configured (`CASELINE_SIP_OUTBOUND_TRUNK_ID` unset),
    `make_dialer()` returns the `LoggingDialer`, so the attempt is recorded
    but not placed — `placed` is false and no telephony charge occurs.
    """
    to_number = _normalize_e164(req.to_number)
    if to_number is None:
        raise HTTPException(status_code=422, detail="to_number must be E.164, e.g. +14155550123")
    p = _platform(request)
    import uuid

    room = f"outbound-manual-{uuid.uuid4().hex[:12]}"
    with p.db.firm(firm.firm_id) as conn:
        agent_id = req.agent_id
        if agent_id is None:
            config = load_agent_config(p.db, p.session_store, firm.firm_id)
            agent_id = config.agent_id if config else None
        conn.execute(
            "INSERT INTO calls (id, firm_id, agent_id, direction, to_number)"
            " VALUES (%s, %s, %s, 'out', %s) ON CONFLICT (firm_id, id) DO NOTHING",
            (room, firm.firm_id, agent_id, to_number),
        )
        platform_events.emit(
            conn,
            firm.firm_id,
            "call.outbound_requested",
            {"call_id": room, "to": to_number, "purpose": req.purpose,
             "dialer": p.dialer.name, "manual": True},
        )
    provider_id = p.dialer.dial(
        to_number, room, metadata={"firm_id": firm.firm_id, "purpose": req.purpose, "manual": True}
    )
    placed = p.dialer.name != "logging"
    return {
        "call_id": room,
        "room": room,
        "to_number": to_number,
        "dialer": p.dialer.name,
        "provider_id": provider_id,
        "placed": placed,
        "note": None if placed
        else "Recorded as dry-run: no SIP outbound trunk configured (set CASELINE_SIP_OUTBOUND_TRUNK_ID to place real calls).",
    }


@router.post("/calls/web-session")
def web_session(
    request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Browser voice test: talk to the intake agent live over WebRTC, no phone.

    Mints a LiveKit access token for a browser participant to join a fresh
    room. The same agent worker that answers phone calls auto-dispatches to
    the room and runs the firm's intake brain — identical STT/LLM/TTS pipeline,
    guardrails, and tools — with the caller's mic/speaker in place of the SIP
    leg. No SIP outbound trunk, no telephony charge, no phone number involved.
    Requires LIVEKIT_URL/API_KEY/API_SECRET and the agent worker running.
    """
    url = os.getenv("LIVEKIT_URL")
    key = os.getenv("LIVEKIT_API_KEY")
    secret = os.getenv("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        raise HTTPException(
            status_code=503,
            detail="LiveKit not configured (set LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET).",
        )
    from livekit import api as lk_api

    room = f"web-manual-{uuid.uuid4().hex[:12]}"
    identity = f"web-tester-{uuid.uuid4().hex[:6]}"
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        agent_id = load_agent_config(p.db, p.session_store, firm.firm_id)
        agent_id = agent_id.agent_id if agent_id else None
        conn.execute(
            "INSERT INTO calls (id, firm_id, agent_id, direction)"
            " VALUES (%s, %s, %s, 'in') ON CONFLICT (firm_id, id) DO NOTHING",
            (room, firm.firm_id, agent_id),
        )
        platform_events.emit(
            conn, firm.firm_id, "call.web_requested", {"call_id": room, "manual": True}
        )
    token = (
        lk_api.AccessToken(key, secret)
        .with_identity(identity)
        .with_name("Web Tester")
        .with_grants(lk_api.VideoGrants(room_join=True, room=room, can_publish=True,
                                        can_subscribe=True, can_publish_data=True))
        .to_jwt()
    )
    return {"room": room, "url": url, "token": token, "identity": identity}


@router.get("/calls")
def list_calls(
    request: Request, limit: int = 50, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> list[dict]:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT id, direction, from_number, started_at, ended_at, outcome, caller_type,"
            "       summary, latency_p50_ms, latency_p95_ms, recording_uri"
            " FROM calls ORDER BY started_at DESC LIMIT %s",
            (min(limit, 200),),
        ).fetchall()
    return [{**r, "started_at": str(r["started_at"]), "ended_at": str(r["ended_at"] or "")} for r in rows]


@router.get("/calls/{call_id}")
def get_call(
    call_id: str, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    p = _platform(request)
    # Raw (unredacted) transcript access is an explicit grant, not a default.
    raw_allowed = firm.has_scope("transcripts:raw")
    with p.db.firm(firm.firm_id) as conn:
        call = conn.execute("SELECT * FROM calls WHERE id = %s", (call_id,)).fetchone()
        if call is None:
            raise HTTPException(status_code=404, detail="Call not found")
        transcript = conn.execute(
            "SELECT turns, turns_redacted, summary FROM transcripts WHERE call_id = %s",
            (call_id,),
        ).fetchone()
        metrics = conn.execute(
            "SELECT speech_id, eou_delay_ms, stt_ms, llm_ttft_ms, tts_ttfb_ms, guardrail_ms,"
            "       total_ms, stt_provider, llm_provider, tts_provider"
            " FROM turn_metrics WHERE call_id = %s ORDER BY id",
            (call_id,),
        ).fetchall()
    turns: list = []
    if transcript:
        if raw_allowed:
            turns = transcript["turns"]
        else:
            # turns_redacted is NULL only for pre-Phase-2 rows; redact on read.
            turns = transcript["turns_redacted"] or redact_turns(transcript["turns"])
    return {
        **{k: str(v) if k in ("started_at", "ended_at") else v for k, v in call.items()},
        "firm_id": str(call["firm_id"]),
        "agent_id": str(call["agent_id"]) if call["agent_id"] else None,
        "transcript": turns,
        "transcript_redacted": not raw_allowed,
        "turn_metrics": metrics,
    }


@router.post("/calls/{call_id}/outcome")
def set_call_outcome(
    call_id: str,
    req: CallOutcomeRequest,
    request: Request,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> dict:
    """Manual disposition override. The agent classifies every call, but a human
    can correct it here — the outcome the analytics funnel and CMS notes read."""
    outcome = req.outcome.strip()
    if not outcome:
        raise HTTPException(status_code=422, detail="outcome must not be blank")
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        row = conn.execute(
            "UPDATE calls SET outcome = %s WHERE id = %s RETURNING id",
            (outcome, call_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Call not found")
        platform_events.emit(
            conn,
            firm.firm_id,
            "call.outcome_overridden",
            {"call_id": call_id, "outcome": outcome, "note": req.note},
        )
    return {"status": "updated", "call_id": call_id, "outcome": outcome}


@router.get("/leads")
def list_leads(
    request: Request, limit: int = 50, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> list[dict]:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT l.id, l.source, l.status, l.practice_area, l.qualification, l.call_id,"
            "       l.external_cms_id, l.created_at, c.name AS contact_name, c.phone AS contact_phone"
            " FROM leads l LEFT JOIN contacts c ON c.id = l.contact_id"
            " ORDER BY l.created_at DESC LIMIT %s",
            (min(limit, 200),),
        ).fetchall()
    return [{**r, "id": str(r["id"]), "created_at": str(r["created_at"])} for r in rows]


@router.get("/consults")
def list_consults(
    request: Request, limit: int = 50, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> list[dict]:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT id, name, phone, slot_at, created_at FROM consults"
            " ORDER BY slot_at DESC LIMIT %s",
            (min(limit, 200),),
        ).fetchall()
    return [
        {**r, "id": str(r["id"]), "slot_at": str(r["slot_at"]), "created_at": str(r["created_at"])}
        for r in rows
    ]


@router.get("/messages")
def list_messages(
    request: Request, limit: int = 50, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> list[dict]:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT id, channel, thread_id, direction, body, ts FROM messages"
            " ORDER BY ts DESC LIMIT %s",
            (min(limit, 200),),
        ).fetchall()
    return [{**r, "id": str(r["id"]), "ts": str(r["ts"])} for r in rows]


# ---------------------------------------------------------------------------
# Analytics (Phase 2 Workstream D) — aggregates only, no PII in responses
# ---------------------------------------------------------------------------


@router.get("/analytics/latency")
def analytics_latency(
    request: Request, days: int = 7, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Per-day and per-provider p50/p95 turn latency for the firm."""
    days = min(max(days, 1), 90)
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        by_day = conn.execute(
            "SELECT date_trunc('day', created_at)::date::text AS day, count(*) AS turns,"
            "       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY total_ms)::numeric, 1)::float AS p50_ms,"
            "       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms)::numeric, 1)::float AS p95_ms"
            " FROM turn_metrics WHERE created_at > now() - make_interval(days => %s)"
            " GROUP BY 1 ORDER BY 1",
            (days,),
        ).fetchall()
        by_provider = conn.execute(
            "SELECT coalesce(llm_provider, 'unknown') AS llm_provider,"
            "       coalesce(tts_provider, 'unknown') AS tts_provider,"
            "       count(*) AS turns,"
            "       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY llm_ttft_ms)::numeric, 1)::float AS llm_ttft_p95_ms,"
            "       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY tts_ttfb_ms)::numeric, 1)::float AS tts_ttfb_p95_ms,"
            "       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms)::numeric, 1)::float AS total_p95_ms"
            " FROM turn_metrics WHERE created_at > now() - make_interval(days => %s)"
            " GROUP BY 1, 2 ORDER BY turns DESC",
            (days,),
        ).fetchall()
    return {
        "days": days,
        "slo_ms": platform_alerts.LATENCY_SLO_MS,
        "by_day": by_day,
        "by_provider": by_provider,
    }


@router.get("/analytics/outcomes")
def analytics_outcomes(
    request: Request, days: int = 30, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Call-outcome funnel: qualification, booking, transfer, abandonment."""
    days = min(max(days, 1), 365)
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        calls = conn.execute(
            "SELECT count(*) AS total,"
            "       count(*) FILTER (WHERE outcome IS NULL AND ended_at IS NULL) AS abandoned"
            " FROM calls WHERE started_at > now() - make_interval(days => %s)",
            (days,),
        ).fetchone()
        outcomes = conn.execute(
            "SELECT coalesce(outcome, 'unknown') AS outcome, count(*) AS n"
            " FROM calls WHERE started_at > now() - make_interval(days => %s)"
            " GROUP BY 1 ORDER BY n DESC",
            (days,),
        ).fetchall()
        leads = conn.execute(
            "SELECT count(*) AS total,"
            "       count(*) FILTER (WHERE status = 'qualified') AS qualified"
            " FROM leads WHERE created_at > now() - make_interval(days => %s)",
            (days,),
        ).fetchone()
        consults = conn.execute(
            "SELECT count(*) AS n FROM consults"
            " WHERE created_at > now() - make_interval(days => %s)",
            (days,),
        ).fetchone()["n"]
        transfers = conn.execute(
            "SELECT count(*) AS n FROM events"
            " WHERE type = 'call.transfer_requested'"
            "   AND created_at > now() - make_interval(days => %s)",
            (days,),
        ).fetchone()["n"]

    def rate(part: int, whole: int) -> float | None:
        return round(part / whole, 3) if whole else None

    return {
        "days": days,
        "calls": calls["total"],
        "outcomes": outcomes,
        "leads": leads["total"],
        "qualified_leads": leads["qualified"],
        "consults_booked": consults,
        "transfers": transfers,
        "qualification_rate": rate(leads["qualified"], leads["total"]),
        "booking_rate": rate(consults, leads["qualified"]),
        "transfer_rate": rate(transfers, calls["total"]),
        "abandonment_rate": rate(calls["abandoned"], calls["total"]),
    }


# ---------------------------------------------------------------------------
# Platform ops (admin): queue health, DLQ replay, alerts (Phase 2)
# ---------------------------------------------------------------------------


@router.get("/admin/ops/overview", dependencies=[Depends(auth.require_admin)])
def ops_overview(request: Request) -> dict:
    p = _platform(request)
    with p.db.admin() as conn:
        stats = platform_events.queue_stats(conn)
    return {"queue": stats}


@router.get("/admin/ops/alerts", dependencies=[Depends(auth.require_admin)])
def ops_alerts(request: Request) -> dict:
    firing = platform_alerts.evaluate(_platform(request).db)
    return {"alerts": platform_alerts.to_dicts(firing), "firing": len(firing)}


@router.get("/admin/events/dead", dependencies=[Depends(auth.require_admin)])
def dead_events(request: Request, limit: int = 100) -> list[dict]:
    p = _platform(request)
    with p.db.admin() as conn:
        rows = platform_events.list_dead(conn, limit=min(limit, 500))
    return [
        {**r, "firm_id": str(r["firm_id"]), "created_at": str(r["created_at"])} for r in rows
    ]


@router.post("/admin/events/{event_id}/replay", dependencies=[Depends(auth.require_admin)])
def replay_event(event_id: int, request: Request) -> dict:
    p = _platform(request)
    with p.db.admin() as conn:
        replayed = platform_events.replay_dead(conn, event_id)
    if not replayed:
        raise HTTPException(status_code=409, detail="Event is not dead-lettered")
    return {"status": "requeued", "event_id": event_id}


# ---------------------------------------------------------------------------
# Phase 3 — omnichannel: lead webhook (Digital Lead Chaser), inbound SMS,
# threads, treatment tracker, config-studio preview
# ---------------------------------------------------------------------------


@router.post("/hooks/leads")
def lead_webhook(
    req: LeadWebhookRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Webform/ad-lead ingest: contact + lead + ``lead.created`` in one
    transaction. The chaser (event consumer) makes first contact within
    seconds — this endpoint never blocks on any outbound transport."""
    if req.source not in ("web", "ad"):
        raise HTTPException(status_code=422, detail="source must be 'web' or 'ad'")
    if not req.phone and not req.email:
        raise HTTPException(status_code=422, detail="lead needs a phone or an email")
    p = _platform(request)
    config = load_agent_config(p.db, p.session_store, firm.firm_id)
    with p.db.firm(firm.firm_id) as conn:
        contact = None
        if req.phone:
            contact = conn.execute(
                "SELECT id, sms_opt_out_at FROM contacts WHERE phone = %s LIMIT 1", (req.phone,)
            ).fetchone()
        if contact is None and req.email:
            contact = conn.execute(
                "SELECT id, sms_opt_out_at FROM contacts WHERE email = %s LIMIT 1", (req.email,)
            ).fetchone()
        if contact is None:
            contact = conn.execute(
                "INSERT INTO contacts (firm_id, name, phone, email) VALUES (%s, %s, %s, %s)"
                " RETURNING id, sms_opt_out_at",
                (firm.firm_id, req.name, req.phone, req.email),
            ).fetchone()
        # Consent is recorded but never resurrected: once someone opts out,
        # only they can opt back in — a fresh form submit does not override STOP.
        if req.sms_consent and contact["sms_opt_out_at"] is None:
            conn.execute(
                "UPDATE contacts SET sms_consent = true, sms_consent_source = %s WHERE id = %s",
                (req.consent_source or f"{req.source} form", contact["id"]),
            )
        effective_consent = bool(req.sms_consent and contact["sms_opt_out_at"] is None)
        lead = conn.execute(
            "INSERT INTO leads (firm_id, source, contact_id, status, practice_area, details)"
            " VALUES (%s, %s, %s, 'new', %s, %s) RETURNING id, created_at",
            (
                firm.firm_id,
                req.source,
                contact["id"],
                req.practice_area or (config.script.practice_area if config else None),
                json.dumps(req.details),
            ),
        ).fetchone()
        platform_events.emit(
            conn,
            firm.firm_id,
            "lead.created",
            {
                "lead_id": str(lead["id"]),
                "contact_id": str(contact["id"]),
                "name": req.name,
                "phone": req.phone,
                "email": req.email,
                "source": req.source,
                "preferred_channel": req.preferred_channel,
                "sms_consent": effective_consent,
            },
        )
    return {"status": "accepted", "lead_id": str(lead["id"]), "contact_id": str(contact["id"])}


@router.post("/hooks/sms")
def sms_webhook(
    req: InboundSMSRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Inbound SMS ingest. Opt-out/help keywords are honored inline and
    unconditionally (CTIA); everything else becomes a ``message.received``
    event the thread engine consumes asynchronously."""
    p = _platform(request)
    config = load_agent_config(p.db, p.session_store, firm.firm_id)
    firm_name = config.firm_name if config else "This firm"

    if is_opt_out(req.body):
        with p.db.firm(firm.firm_id) as conn:
            conn.execute(
                "UPDATE contacts SET sms_consent = false, sms_opt_out_at = now() WHERE phone = %s",
                (req.from_number,),
            )
            threads = conn.execute(
                "UPDATE threads SET status = 'closed', closed_reason = 'opted_out', updated_at = now()"
                " WHERE channel = 'sms' AND address = %s AND status = 'open' RETURNING id",
                (req.from_number,),
            ).fetchall()
            for t in threads:
                conn.execute(
                    "UPDATE followups SET status = 'canceled', done_at = now()"
                    " WHERE thread_id = %s AND status = 'pending'",
                    (t["id"],),
                )
            conn.execute(
                "INSERT INTO messages (firm_id, channel, thread_id, direction, body)"
                " VALUES (%s, 'sms', %s, 'in', %s)",
                (firm.firm_id, req.from_number, req.body),
            )
            platform_events.emit(
                conn, firm.firm_id, "message.optout", {"address": req.from_number}
            )
        # The CTIA-required confirmation is the one message allowed after STOP.
        p.sms.send(req.from_number, opt_out_confirmation(firm_name))
        return {"status": "opted_out"}

    if is_help(req.body):
        p.sms.send(req.from_number, help_reply(firm_name))
        return {"status": "help_sent"}

    with p.db.firm(firm.firm_id) as conn:
        platform_events.emit(
            conn,
            firm.firm_id,
            "message.received",
            {"channel": "sms", "address": req.from_number, "body": req.body},
        )
    return {"status": "queued"}


@router.get("/threads")
def list_threads(
    request: Request, limit: int = 50, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> list[dict]:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT id, channel, address, goal, status, closed_reason, lead_id,"
            "       created_at, updated_at, last_inbound_at, last_outbound_at"
            " FROM threads ORDER BY updated_at DESC LIMIT %s",
            (min(limit, 200),),
        ).fetchall()
    return [
        {
            **r,
            "id": str(r["id"]),
            "lead_id": str(r["lead_id"]) if r["lead_id"] else None,
            **{
                k: str(r[k] or "")
                for k in ("created_at", "updated_at", "last_inbound_at", "last_outbound_at")
            },
        }
        for r in rows
    ]


@router.get("/threads/{thread_id}")
def get_thread(
    thread_id: str, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        thread = conn.execute("SELECT * FROM threads WHERE id = %s", (thread_id,)).fetchone()
        if thread is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        messages = conn.execute(
            "SELECT direction, body, ts FROM messages WHERE thread_id = %s ORDER BY ts",
            (thread_id,),
        ).fetchall()
    return {
        **{k: str(v) if v is not None else None for k, v in thread.items()},
        "state": thread["state"],
        "messages": [{**m, "ts": str(m["ts"])} for m in messages],
    }


@router.post("/threads/{thread_id}/message")
def send_thread_message(
    thread_id: str,
    req: ThreadMessageRequest,
    request: Request,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> dict:
    """Send a staff-authored follow-up on an open thread — the manual override
    of the automated chaser. Guardrail-screened like every other outbound send;
    disarms the pending no-reply nudge so the client isn't double-contacted."""
    engine = _thread_engine(request)
    try:
        return engine.send_manual_message(firm.firm_id, thread_id, req.body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Thread not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/tracker/enroll")
def tracker_enroll(
    req: TrackerEnrollRequest, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Enroll a signed client in the treatment tracker (Phase 3). Consent for
    these check-ins is part of the representation agreement; STOP still wins."""
    p = _platform(request)
    engine = _thread_engine(request)
    with p.db.firm(firm.firm_id) as conn:
        opted_out = conn.execute(
            "SELECT 1 FROM contacts WHERE phone = %s AND sms_opt_out_at IS NOT NULL",
            (req.phone,),
        ).fetchone()
    if opted_out:
        raise HTTPException(status_code=409, detail="Contact has opted out of SMS")
    try:
        thread_id = engine.enroll_tracker(
            firm.firm_id,
            name=req.name,
            phone=req.phone,
            matter_description=req.matter_description,
            cadence_days=req.cadence_days,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with p.db.firm(firm.firm_id) as conn:
        conn.execute(
            "UPDATE contacts SET sms_consent = true, sms_consent_source = 'client agreement'"
            " WHERE phone = %s AND sms_opt_out_at IS NULL",
            (req.phone,),
        )
    return {"status": "enrolled", "thread_id": thread_id}


# ---------------------------------------------------------------------------
# Config studio v1 (Phase 3): agent listing + test-call preview
# ---------------------------------------------------------------------------


@router.get("/agents")
def list_agents(
    request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> list[dict]:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT id, name, role, voice_id, updated_at FROM agents ORDER BY created_at"
        ).fetchall()
    return [{**r, "id": str(r["id"]), "updated_at": str(r["updated_at"])} for r in rows]


@router.post("/agents/{agent_id}/preview")
def preview_test_call(
    agent_id: str,
    req: PreviewRequest,
    request: Request,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> dict:
    """Test-call preview: run caller messages through the same brain the live
    channels use — including unsaved config overrides — with no side effects.
    This is how a firm verifies a script/rule edit before it meets a caller."""
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        agent = conn.execute("SELECT role FROM agents WHERE id = %s", (agent_id,)).fetchone()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    config = load_agent_config(p.db, p.session_store, firm.firm_id, agent["role"])
    if config is None:
        raise HTTPException(status_code=409, detail="Agent has no loadable config")
    try:
        updates: dict = {}
        if req.script_config is not None:
            updates["script"] = ScriptConfig.model_validate(req.script_config)
        if req.qualification_rules is not None:
            updates["qualification"] = QualificationRules.model_validate(req.qualification_rules)
        if req.guardrails is not None:
            updates["guardrails"] = GuardrailSettings.model_validate(req.guardrails)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updates:
        config = config.model_copy(update=updates)
    return preview_conversation(config, req.messages, contact_name=req.contact_name)


@router.get("/analytics/chaser")
def analytics_chaser(
    request: Request, days: int = 30, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Speed-to-lead funnel: how fast chased leads get their first contact.
    The Phase 3 exit criterion is p95 under 60 s from webform submit."""
    days = min(max(days, 1), 365)
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        row = conn.execute(
            "SELECT count(*) AS total,"
            "       count(first_contact_at) AS contacted,"
            "       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY"
            "         extract(epoch FROM first_contact_at - created_at))::numeric, 1)::float AS p50_seconds,"
            "       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY"
            "         extract(epoch FROM first_contact_at - created_at))::numeric, 1)::float AS p95_seconds,"
            "       count(*) FILTER (WHERE first_contact_at - created_at <= interval '60 seconds')"
            "         AS contacted_under_60s"
            " FROM leads WHERE source IN ('web', 'ad')"
            "   AND created_at > now() - make_interval(days => %s)",
            (days,),
        ).fetchone()
    total = row["total"]
    return {
        "days": days,
        "slo_seconds": 60,
        "web_ad_leads": total,
        "contacted": row["contacted"],
        "contact_rate": round(row["contacted"] / total, 3) if total else None,
        "first_contact_p50_seconds": row["p50_seconds"],
        "first_contact_p95_seconds": row["p95_seconds"],
        "under_60s_rate": round(row["contacted_under_60s"] / row["contacted"], 3)
        if row["contacted"]
        else None,
    }


@router.get("/admin/ops/onboarding", dependencies=[Depends(auth.require_admin)])
def ops_onboarding(request: Request) -> dict:
    """Time-to-first-live-call per firm — the onboarding-speed metric the
    config studio exists to drive down (Phase 3 exit: under a day)."""
    p = _platform(request)
    with p.db.admin() as conn:
        rows = conn.execute(
            "SELECT f.id, f.name, f.created_at, min(c.started_at) AS first_call_at,"
            "       extract(epoch FROM min(c.started_at) - f.created_at)::float"
            "         AS time_to_first_call_seconds"
            " FROM firms f LEFT JOIN calls c ON c.firm_id = f.id"
            " GROUP BY f.id, f.name, f.created_at ORDER BY f.created_at"
        ).fetchall()
    return {
        "firms": [
            {
                **r,
                "id": str(r["id"]),
                "created_at": str(r["created_at"]),
                "first_call_at": str(r["first_call_at"]) if r["first_call_at"] else None,
            }
            for r in rows
        ]
    }


@router.get("/events")
def list_events(
    request: Request,
    status: str | None = None,
    limit: int = 100,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> list[dict]:
    p = _platform(request)
    where = "WHERE status = %s" if status else ""
    params: tuple = (status, min(limit, 500)) if status else (min(limit, 500),)
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            f"SELECT id, type, status, attempts, created_at, processed_at, last_error"
            f" FROM events {where} ORDER BY id DESC LIMIT %s",
            params,
        ).fetchall()
    return [
        {**r, "created_at": str(r["created_at"]), "processed_at": str(r["processed_at"] or "")}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Phase 4 — differentiation: voice cloning, qualification tuning, smart
# referrals, benchmark analytics
# ---------------------------------------------------------------------------


@router.post("/voice-profiles")
def create_voice_profile(
    req: VoiceProfileCreate, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Create a branded voice for the firm. The clone provider runs off the
    hot path (this is an onboarding action, not a call action); the profile
    only becomes assignable once the provider returns a voice id."""
    from api.voice import VoiceCloneError, _decode_data_uri

    if not req.consent_confirmed:
        raise HTTPException(
            status_code=422,
            detail="Voice cloning requires the voice owner's recorded consent"
            " (consent_confirmed=true)",
        )
    # Inline audio (browser recording / file upload) arrives as a base64 data
    # URI. Decode it to bytes here and persist only a compact marker as
    # sample_uri — never the megabyte-scale blob (it ships back on every list).
    audio: bytes | None = None
    audio_mime: str | None = None
    stored_uri = req.sample_uri
    if req.sample_data:
        try:
            audio = _decode_data_uri(req.sample_data)
        except VoiceCloneError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        audio_mime = req.sample_data[5:].split(";", 1)[0] or None
        stored_uri = f"inline:{audio_mime or 'audio'}:{len(audio)}b"
    p = _platform(request)
    cloner = p.voice_cloner
    with p.db.firm(firm.firm_id) as conn:
        row = conn.execute(
            "INSERT INTO voice_profiles (firm_id, name, provider, sample_uri, consent_confirmed)"
            " VALUES (%s, %s, %s, %s, true) RETURNING id",
            (firm.firm_id, req.name, cloner.name, stored_uri),
        ).fetchone()
    profile_id = str(row["id"])
    try:
        voice_id = cloner.create_voice(
            req.name, stored_uri, req.description, audio=audio, audio_mime=audio_mime
        )
    except VoiceCloneError as exc:
        with p.db.firm(firm.firm_id) as conn:
            conn.execute(
                "UPDATE voice_profiles SET status = 'failed', error = %s, updated_at = now()"
                " WHERE id = %s",
                (str(exc)[:2000], profile_id),
            )
        raise HTTPException(status_code=502, detail=f"Voice clone failed: {exc}") from exc
    with p.db.firm(firm.firm_id) as conn:
        conn.execute(
            "UPDATE voice_profiles SET status = 'ready', provider_voice_id = %s,"
            " updated_at = now() WHERE id = %s",
            (voice_id, profile_id),
        )
        platform_events.emit(
            conn,
            firm.firm_id,
            "voice.profile_ready",
            {"voice_profile_id": profile_id, "provider": cloner.name, "name": req.name},
        )
    return {"voice_profile_id": profile_id, "status": "ready", "provider_voice_id": voice_id}


@router.get("/voice-profiles")
def list_voice_profiles(
    request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> list[dict]:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT id, name, provider, provider_voice_id, status, sample_uri, error, created_at"
            " FROM voice_profiles ORDER BY created_at DESC"
        ).fetchall()
    return [{**r, "id": str(r["id"]), "created_at": str(r["created_at"])} for r in rows]


@router.post("/agents/{agent_id}/voice")
def assign_agent_voice(
    agent_id: str,
    req: AssignVoiceRequest,
    request: Request,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> dict:
    """Point an agent at a ready voice profile. Goes through
    update_agent_config so the config cache invalidates and the very next
    call speaks in the firm's voice."""
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        profile = conn.execute(
            "SELECT status, provider_voice_id FROM voice_profiles WHERE id = %s",
            (req.voice_profile_id,),
        ).fetchone()
    if profile is None:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    if profile["status"] != "ready" or not profile["provider_voice_id"]:
        raise HTTPException(
            status_code=409,
            detail=f"Voice profile is {profile['status']}; only ready voices reach callers",
        )
    updated = update_agent_config(
        p.db, p.session_store, firm.firm_id, agent_id, voice_id=profile["provider_voice_id"]
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "assigned", "voice_id": profile["provider_voice_id"]}


@router.post("/leads/{lead_id}/review")
def review_lead(
    lead_id: str,
    req: LeadReviewRequest,
    request: Request,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> dict:
    """Record the attorney's accept/reject verdict on a lead — the training
    signal for qualification tuning. Re-reviewing overwrites the verdict."""
    if req.verdict not in ("accepted", "rejected"):
        raise HTTPException(status_code=422, detail="verdict must be 'accepted' or 'rejected'")
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        lead = conn.execute("SELECT id FROM leads WHERE id = %s", (lead_id,)).fetchone()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        conn.execute(
            "INSERT INTO lead_reviews (firm_id, lead_id, verdict, reviewer, reason)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (firm_id, lead_id) DO UPDATE SET verdict = EXCLUDED.verdict,"
            " reviewer = EXCLUDED.reviewer, reason = EXCLUDED.reason, updated_at = now()",
            (firm.firm_id, lead_id, req.verdict, req.reviewer, req.reason),
        )
        platform_events.emit(
            conn,
            firm.firm_id,
            "lead.reviewed",
            {"lead_id": lead_id, "verdict": req.verdict, "reviewer": req.reviewer},
        )
    return {"status": "recorded", "lead_id": lead_id, "verdict": req.verdict}


@router.get("/tuning/suggestions")
def tuning_suggestions(
    request: Request, days: int = 90, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Compare attorney verdicts against engine decisions and propose rule
    edits. Suggestions are advisory: a human applies proposed_rules through
    the same validated config PUT every other edit uses."""
    from api import tuning

    days = min(max(days, 1), 365)
    p = _platform(request)
    config = load_agent_config(p.db, p.session_store, firm.firm_id)
    if config is None:
        raise HTTPException(status_code=409, detail="Firm has no configured agent")
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT r.verdict, l.qualification, l.created_at"
            " FROM lead_reviews r JOIN leads l ON l.id = r.lead_id"
            " WHERE r.created_at > now() - make_interval(days => %s)"
            "   AND l.qualification IS NOT NULL",
            (days,),
        ).fetchall()
    samples = [
        tuning.sample_from_row(r["verdict"], r["qualification"], r["created_at"].date())
        for r in rows
    ]
    report = tuning.analyze_reviews(samples, config.qualification)
    return {
        "days": days,
        "reviews": report.reviews,
        "agreement_rate": report.agreement_rate,
        "matrix": report.matrix,
        "suggestions": [
            {"kind": s.kind, "detail": s.detail, "evidence": s.evidence}
            for s in report.suggestions
        ],
        "current_rules": config.qualification.model_dump(),
        "proposed_rules": report.proposed_rules,
    }


@router.post("/tuning/apply")
def apply_tuning(
    request: Request, days: int = 90, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Apply the engine's proposed qualification rules to the live intake agent.
    Proposed rules are recomputed server-side (never trusting a client payload)
    and pushed through the same validated config path every other edit uses, so
    the change reaches the next call in seconds."""
    from api import tuning

    days = min(max(days, 1), 365)
    p = _platform(request)
    config = load_agent_config(p.db, p.session_store, firm.firm_id)
    if config is None:
        raise HTTPException(status_code=409, detail="Firm has no configured agent")
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT r.verdict, l.qualification, l.created_at"
            " FROM lead_reviews r JOIN leads l ON l.id = r.lead_id"
            " WHERE r.created_at > now() - make_interval(days => %s)"
            "   AND l.qualification IS NOT NULL",
            (days,),
        ).fetchall()
    samples = [
        tuning.sample_from_row(r["verdict"], r["qualification"], r["created_at"].date())
        for r in rows
    ]
    report = tuning.analyze_reviews(samples, config.qualification)
    if not report.proposed_rules:
        raise HTTPException(status_code=409, detail="No proposed rule changes to apply")
    try:
        updated = update_agent_config(
            p.db,
            p.session_store,
            firm.firm_id,
            config.agent_id,
            qualification_rules=report.proposed_rules,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Intake agent not found")
    with p.db.firm(firm.firm_id) as conn:
        platform_events.emit(
            conn,
            firm.firm_id,
            "tuning.applied",
            {"agent_id": config.agent_id, "reviews": report.reviews},
        )
    return {
        "status": "applied",
        "agent_id": config.agent_id,
        "applied_rules": report.proposed_rules,
    }


@router.post("/referral-partners")
def create_referral_partner(
    req: ReferralPartnerCreate, request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """Register a partner firm. Registering partners is the opt-in switch for
    smart referrals — no partners, no proposals."""
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        row = conn.execute(
            "INSERT INTO referral_partners"
            " (firm_id, name, practice_areas, states, contact_email, contact_phone, notes)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                firm.firm_id,
                req.name,
                req.practice_areas,
                [s.upper() for s in req.states],
                req.contact_email,
                req.contact_phone,
                req.notes,
            ),
        ).fetchone()
    return {"partner_id": str(row["id"]), "status": "created"}


@router.get("/referral-partners")
def list_referral_partners(
    request: Request, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> list[dict]:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT id, name, practice_areas, states, contact_email, contact_phone,"
            "       active, notes, created_at"
            " FROM referral_partners ORDER BY created_at"
        ).fetchall()
    return [{**r, "id": str(r["id"]), "created_at": str(r["created_at"])} for r in rows]


@router.get("/referrals")
def list_referrals(
    request: Request, limit: int = 50, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> list[dict]:
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        rows = conn.execute(
            "SELECT rf.id, rf.lead_id, rf.status, rf.match_reasons, rf.client_consent,"
            "       rf.sent_at, rf.created_at, rp.name AS partner_name,"
            "       c.name AS contact_name, l.practice_area"
            " FROM referrals rf"
            " JOIN referral_partners rp ON rp.id = rf.partner_id"
            " JOIN leads l ON l.id = rf.lead_id"
            " LEFT JOIN contacts c ON c.id = l.contact_id"
            " ORDER BY rf.created_at DESC LIMIT %s",
            (min(limit, 200),),
        ).fetchall()
    return [
        {
            **r,
            "id": str(r["id"]),
            "lead_id": str(r["lead_id"]),
            "sent_at": str(r["sent_at"]) if r["sent_at"] else None,
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


@router.post("/referrals/{referral_id}/send")
def send_referral(
    referral_id: str,
    req: ReferralSendRequest,
    request: Request,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> dict:
    """Human send action. Client case facts leave the system only here, and
    only with the client's consent recorded — the AI proposes, a person
    shares."""
    from api.referrals import build_packet, packet_email_body

    if not req.client_consent:
        raise HTTPException(
            status_code=422,
            detail="Sending a referral requires the client's recorded consent"
            " (client_consent=true)",
        )
    p = _platform(request)
    config = load_agent_config(p.db, p.session_store, firm.firm_id)
    firm_name = config.firm_name if config else "A partner firm"
    with p.db.firm(firm.firm_id) as conn:
        referral = conn.execute(
            "SELECT rf.id, rf.lead_id, rf.status, rf.match_reasons,"
            "       rp.name AS partner_name, rp.contact_email"
            " FROM referrals rf JOIN referral_partners rp ON rp.id = rf.partner_id"
            " WHERE rf.id = %s",
            (referral_id,),
        ).fetchone()
        if referral is None:
            raise HTTPException(status_code=404, detail="Referral not found")
        if referral["status"] != "proposed":
            raise HTTPException(
                status_code=409, detail=f"Referral is already {referral['status']}"
            )
        packet = build_packet(conn, firm.firm_id, referral["lead_id"])
        conn.execute(
            "UPDATE referrals SET status = 'sent', client_consent = true, packet = %s,"
            " sent_at = now(), updated_at = now() WHERE id = %s",
            (json.dumps(packet), referral_id),
        )
        platform_events.emit(
            conn,
            firm.firm_id,
            "referral.sent",
            {"referral_id": referral_id, "lead_id": str(referral["lead_id"])},
        )
    if referral["contact_email"]:
        p.email.send(
            referral["contact_email"],
            f"Case referral from {firm_name}",
            packet_email_body(firm_name, packet, referral["match_reasons"] or []),
        )
    return {"status": "sent", "referral_id": referral_id}


@router.post("/referrals/{referral_id}/status")
def update_referral_status(
    referral_id: str,
    req: ReferralStatusRequest,
    request: Request,
    firm: auth.AuthedFirm = Depends(auth.require_firm),
) -> dict:
    """Track the partner's answer so the firm sees which partners convert."""
    if req.status not in ("accepted", "declined"):
        raise HTTPException(status_code=422, detail="status must be 'accepted' or 'declined'")
    p = _platform(request)
    with p.db.firm(firm.firm_id) as conn:
        row = conn.execute(
            "UPDATE referrals SET status = %s, updated_at = now()"
            " WHERE id = %s AND status = 'sent' RETURNING lead_id",
            (req.status, referral_id),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=409, detail="Referral not found or not in 'sent' state"
            )
        platform_events.emit(
            conn,
            firm.firm_id,
            "referral.resolved",
            {"referral_id": referral_id, "lead_id": str(row["lead_id"]), "status": req.status},
        )
    return {"status": req.status, "referral_id": referral_id}


@router.get("/analytics/benchmarks")
def analytics_benchmarks(
    request: Request, days: int = 30, firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    """The firm's intake funnel against an anonymized peer cohort. Cohort
    stats are k-anonymity gated and carry no peer identifiers — the
    cross-firm aggregation happens platform-side by design (this is the
    analytics product), but only aggregates ever leave it."""
    from api import benchmarks

    days = min(max(days, 1), 365)
    p = _platform(request)
    funnels = benchmarks.collect_funnels(p.db, days)
    return benchmarks.benchmark_report(funnels, firm.firm_id, days)
