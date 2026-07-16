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

from fastapi import APIRouter, Depends, HTTPException, Request

from api import tools
from api.orchestration.config import load_agent_config, update_agent_config
from api.platform import auth
from api.platform.schemas import (
    AgentConfigUpdate,
    CompleteCallRequest,
    CreateFirmRequest,
    CreateFirmResponse,
    CreateTokenRequest,
    CreateTokenResponse,
    LookupCallerRequest,
    SendSMSRequest,
    TakeMessageRequest,
    ToolQualifyRequest,
    ToolScheduleRequest,
    TranscriptRequest,
    TransferRequest,
    TurnMetricsV1,
)

logger = logging.getLogger("caseline.api.v1")

router = APIRouter(prefix="/v1")


def _platform(request: Request):
    return request.app.state.platform


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
    return CreateTokenResponse(token=auth.issue_token(_platform(request).db, firm_id, req.name))


# ---------------------------------------------------------------------------
# Agent config
# ---------------------------------------------------------------------------


@router.get("/agent-config")
def get_agent_config(
    request: Request, role: str = "intaker", firm: auth.AuthedFirm = Depends(auth.require_firm)
) -> dict:
    p = _platform(request)
    config = load_agent_config(p.db, p.session_store, firm.firm_id, role)
    if config is None:
        raise HTTPException(status_code=404, detail=f"No {role} agent configured")
    return {**config.model_dump(), "instructions": config.instructions()}


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
        conn.execute(
            "INSERT INTO transcripts (firm_id, call_id, turns, summary)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (firm_id, call_id) DO UPDATE SET turns = EXCLUDED.turns,"
            " summary = COALESCE(EXCLUDED.summary, transcripts.summary)",
            (firm.firm_id, call_id, json.dumps(turns), req.summary),
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
            " (firm_id, call_id, speech_id, eou_delay_ms, llm_ttft_ms, tts_ttfb_ms, total_ms)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                firm.firm_id,
                req.call_id,
                req.speech_id,
                req.eou_delay_ms,
                req.llm_ttft_ms,
                req.tts_ttfb_ms,
                req.total_ms,
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
    with p.db.firm(firm.firm_id) as conn:
        call = conn.execute("SELECT * FROM calls WHERE id = %s", (call_id,)).fetchone()
        if call is None:
            raise HTTPException(status_code=404, detail="Call not found")
        transcript = conn.execute(
            "SELECT turns, summary FROM transcripts WHERE call_id = %s", (call_id,)
        ).fetchone()
        metrics = conn.execute(
            "SELECT speech_id, eou_delay_ms, llm_ttft_ms, tts_ttfb_ms, total_ms"
            " FROM turn_metrics WHERE call_id = %s ORDER BY id",
            (call_id,),
        ).fetchall()
    return {
        **{k: str(v) if k in ("started_at", "ended_at") else v for k, v in call.items()},
        "firm_id": str(call["firm_id"]),
        "agent_id": str(call["agent_id"]) if call["agent_id"] else None,
        "transcript": transcript["turns"] if transcript else [],
        "turn_metrics": metrics,
    }


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
