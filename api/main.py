"""Caseline Phase 0 backend: tool endpoints + mock CMS + latency metrics.

App-factory pattern so tests can spin up an isolated instance against a
temporary database. `app` at module level is what uvicorn serves:

    uvicorn api.main:app --reload
"""

from __future__ import annotations

import logging
import os

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


def create_app(db_path: str | None = None) -> FastAPI:
    load_dotenv()
    app = FastAPI(title="Caseline Phase 0 Backend", version="0.1.0")
    app.state.store = Store(db_path or os.getenv("CASELINE_DB", "caseline.db"))

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
