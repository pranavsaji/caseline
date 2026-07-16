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
from api.compliance.consent import consent_policy
from api.compliance.redaction import redact_turns
from api.orchestration.config import load_agent_config, update_agent_config
from api.platform import alerts as platform_alerts
from api.platform import auth
from api.platform import events as platform_events
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
            " (firm_id, call_id, speech_id, eou_delay_ms, llm_ttft_ms, tts_ttfb_ms, total_ms,"
            "  stt_provider, llm_provider, tts_provider)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                firm.firm_id,
                req.call_id,
                req.speech_id,
                req.eou_delay_ms,
                req.llm_ttft_ms,
                req.tts_ttfb_ms,
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
            "SELECT speech_id, eou_delay_ms, llm_ttft_ms, tts_ttfb_ms, total_ms,"
            "       stt_provider, llm_provider, tts_provider"
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
