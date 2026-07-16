"""HTTP client for the Caseline backend tool endpoints.

Deliberately livekit-free so the agent<->backend contract is testable without
the voice stack (tests drive it against the FastAPI app in-process via
httpx.ASGITransport).
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("caseline.agent.backend")

DEFAULT_TIMEOUT = 5.0


class BackendClient:
    def __init__(self, base_url: str | None = None, client: httpx.AsyncClient | None = None):
        base_url = base_url or os.getenv("CASELINE_BACKEND_URL", "http://localhost:8000")
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=DEFAULT_TIMEOUT)

    async def qualify_lead(
        self, incident_date: str, injury_type: str, in_treatment: bool, has_insurance: bool
    ) -> dict:
        r = await self._client.post(
            "/qualify",
            json={
                "incident_date": incident_date,
                "injury_type": injury_type,
                "in_treatment": in_treatment,
                "has_insurance": has_insurance,
            },
        )
        r.raise_for_status()
        return r.json()

    async def schedule_consult(self, name: str, phone: str, slot_iso: str) -> dict:
        r = await self._client.post(
            "/schedule", json={"name": name, "phone": phone, "slot_iso": slot_iso}
        )
        r.raise_for_status()
        return r.json()

    async def write_to_cms(self, call_id: str, summary: str, structured: dict) -> dict:
        r = await self._client.post(
            "/mock-cms", json={"call_id": call_id, "summary": summary, "structured": structured}
        )
        r.raise_for_status()
        return r.json()

    async def post_turn_metrics(self, turn: dict) -> None:
        """Fire-and-forget from the worker's perspective: metrics must never
        break a live call, so failures are logged and swallowed."""
        try:
            r = await self._client.post("/metrics/turn", json=turn)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("failed to post turn metrics: %s", exc)

    async def call_latency_summary(self, call_id: str) -> dict:
        r = await self._client.get(f"/metrics/calls/{call_id}")
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self._client.aclose()
