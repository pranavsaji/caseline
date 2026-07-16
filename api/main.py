"""Caseline backend: Phase 0 prototype endpoints + Phase 1 multi-tenant v1 API.

App-factory pattern so tests can spin up an isolated instance against a
temporary database. `app` at module level is what uvicorn serves:

    uvicorn api.main:app --reload

The Phase 1 platform (Postgres + RLS, auth, events, /v1/*) mounts when
CASELINE_DATABASE_URL is configured; the Phase 0 endpoints stay available so
the single-tenant prototype path keeps working without Postgres.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from fastapi import FastAPI, Request

from api import qualification
from api.schemas import (
    CallLatencySummary,
    CMSWriteRequest,
    CMSWriteResponse,
    QualifyRequest,
    QualifyResponse,
    ScheduleRequest,
    ScheduleResponse,
    TurnMetrics,
)
from api.storage import Store

logger = logging.getLogger("caseline.api")


@dataclass
class PlatformContext:
    """Everything the v1 routes need, built once per app."""

    db: object
    session_store: object
    sms: object
    cipher: object
    rate_limiter: object
    admin_token: str | None
    email: object = None  # EmailProvider (Phase 3); LoggingEmailProvider default
    dialer: object = None  # OutboundDialer (Phase 3); LoggingDialer default

    def __post_init__(self) -> None:
        if self.email is None:
            from api.messaging import LoggingEmailProvider

            self.email = LoggingEmailProvider()
        if self.dialer is None:
            from api.telephony import LoggingDialer

            self.dialer = LoggingDialer()


def _build_platform(database_url: str, admin_token: str | None) -> PlatformContext:
    from api.messaging import make_email_provider, make_sms_provider
    from api.platform.auth import RateLimiter
    from api.platform.db import Database
    from api.platform.secrets import make_cipher
    from api.platform.session_state import make_session_store
    from api.telephony import make_dialer

    # Pool sizing is a throughput knob: 50 concurrent calls need more than
    # the dev default of 4 connections or tool calls queue on the pool
    # (measured: qualify_lead p95 went 799ms -> ~100ms at pool 20 under a
    # 50-call load test).
    db = Database(database_url, pool_size=int(os.getenv("CASELINE_DB_POOL_SIZE", "4")))
    db.migrate()
    return PlatformContext(
        db=db,
        session_store=make_session_store(),
        sms=make_sms_provider(),
        cipher=make_cipher(),
        rate_limiter=RateLimiter(
            limit=int(os.getenv("CASELINE_RATE_LIMIT_PER_MINUTE", "300"))
        ),
        admin_token=admin_token,
        email=make_email_provider(),
        dialer=make_dialer(),
    )


def create_app(
    db_path: str | None = None,
    database_url: str | None = None,
    admin_token: str | None = None,
    platform: PlatformContext | None = None,
) -> FastAPI:
    load_dotenv()
    # PII never reaches log sinks un-redacted (Phase 2 compliance pipeline).
    from api.compliance.redaction import install_log_redaction

    install_log_redaction()
    app = FastAPI(title="Caseline Backend", version="0.3.0")
    app.state.store = Store(db_path or os.getenv("CASELINE_DB", "caseline.db"))

    database_url = database_url or os.getenv("CASELINE_DATABASE_URL")
    admin_token = admin_token or os.getenv("CASELINE_ADMIN_TOKEN")
    owns_platform = False
    if platform is None and database_url:
        platform = _build_platform(database_url, admin_token)
        owns_platform = True
    if platform is not None:
        from api.routes_v1 import router as v1_router

        app.state.platform = platform
        app.include_router(v1_router)

        if owns_platform:

            @app.on_event("shutdown")
            def _close_platform() -> None:
                platform.db.close()

    def store(request: Request) -> Store:
        return request.app.state.store

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/qualify", response_model=QualifyResponse)
    def qualify(req: QualifyRequest) -> QualifyResponse:
        result = qualification.qualify(
            incident_date=req.incident_date,
            injury_type=req.injury_type,
            in_treatment=req.in_treatment,
            has_insurance=req.has_insurance,
        )
        logger.info("qualify decision=%s reasons=%s", result.decision, result.reasons)
        return QualifyResponse(decision=result.decision, reasons=result.reasons)

    @app.post("/schedule", response_model=ScheduleResponse)
    def schedule(req: ScheduleRequest, request: Request) -> ScheduleResponse:
        consult_id = store(request).save_consult(req.name, req.phone, req.slot_iso)
        logger.info("consult booked id=%s name=%s slot=%s", consult_id, req.name, req.slot_iso)
        return ScheduleResponse(status="booked", consult_id=consult_id)

    @app.post("/mock-cms", response_model=CMSWriteResponse)
    def mock_cms(req: CMSWriteRequest, request: Request) -> CMSWriteResponse:
        record_id = store(request).save_cms_record(req.call_id, req.summary, req.structured)
        logger.info("CMS WRITE id=%s call=%s summary=%s", record_id, req.call_id, req.summary)
        return CMSWriteResponse(status="saved", record_id=record_id)

    @app.get("/mock-cms")
    def list_cms(request: Request) -> list[dict]:
        return store(request).list_cms_records()

    @app.get("/consults")
    def list_consults(request: Request) -> list[dict]:
        return store(request).list_consults()

    @app.post("/metrics/turn")
    def record_turn(req: TurnMetrics, request: Request) -> dict:
        store(request).save_turn_metrics(
            call_id=req.call_id,
            speech_id=req.speech_id,
            eou_delay_ms=req.eou_delay_ms,
            llm_ttft_ms=req.llm_ttft_ms,
            tts_ttfb_ms=req.tts_ttfb_ms,
            total_ms=req.total_ms,
        )
        return {"status": "recorded"}

    @app.get("/metrics/calls/{call_id}", response_model=CallLatencySummary)
    def call_summary(call_id: str, request: Request) -> CallLatencySummary:
        return CallLatencySummary(**store(request).call_latency_summary(call_id))

    return app


app = create_app()
