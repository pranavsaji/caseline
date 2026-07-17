"""HTTP client for the Caseline backend tool endpoints.

Deliberately livekit-free so the agent<->backend contract is testable without
the voice stack (tests drive it against the FastAPI app in-process via
httpx.ASGITransport).

Two modes, one surface:
  * Phase 0 (no firm token): the original single-tenant prototype endpoints.
  * Phase 1 (CASELINE_FIRM_TOKEN set): the multi-tenant /v1 API — per-firm
    config, typed tools, transcripts. The worker code is identical either
    way; only the token decides.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("caseline.agent.backend")

DEFAULT_TIMEOUT = 5.0


class BackendClient:
    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        firm_token: str | None = None,
    ):
        base_url = base_url or os.getenv("CASELINE_BACKEND_URL", "http://localhost:8000")
        self._token = firm_token if firm_token is not None else os.getenv("CASELINE_FIRM_TOKEN", "")
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        self._client = client or httpx.AsyncClient(
            base_url=base_url, timeout=DEFAULT_TIMEOUT, headers=headers
        )
        if client is not None and self._token:
            client.headers["Authorization"] = f"Bearer {self._token}"

    @property
    def v1(self) -> bool:
        """True when running against the Phase 1 multi-tenant API."""
        return bool(self._token)

    async def _post(self, path: str, payload: dict) -> dict:
        r = await self._client.post(path, json=payload)
        r.raise_for_status()
        return r.json()

    # --- Phase 1: per-firm config ---

    async def get_agent_config(
        self, role: str = "intaker", from_number: str | None = None
    ) -> dict | None:
        """Fetch the firm's agent config; None means run on safe defaults.
        Config fetch must never take down a call at start. ``from_number``
        lets the backend resolve the per-state consent policy for the call."""
        if not self.v1:
            return None
        params: dict = {"role": role}
        if from_number:
            params["from_number"] = from_number
        try:
            r = await self._client.get("/v1/agent-config", params=params)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            logger.warning("agent config fetch failed, using defaults: %s", exc)
            return None

    # --- tools (both modes) ---

    async def qualify_lead(
        self,
        incident_date: str,
        injury_type: str,
        in_treatment: bool,
        has_insurance: bool,
        call_id: str | None = None,
    ) -> dict:
        if self.v1:
            return await self._post(
                "/v1/tools/qualify_lead",
                {
                    "call_id": call_id or "unknown",
                    "incident_date": incident_date,
                    "injury_type": injury_type,
                    "in_treatment": in_treatment,
                    "has_insurance": has_insurance,
                },
            )
        return await self._post(
            "/qualify",
            {
                "incident_date": incident_date,
                "injury_type": injury_type,
                "in_treatment": in_treatment,
                "has_insurance": has_insurance,
            },
        )

    async def get_available_slots(self) -> dict:
        """Real open consultation slots (v1 only)."""
        if not self.v1:
            return {"slots": []}
        r = await self._client.get("/v1/tools/available_slots")
        r.raise_for_status()
        return r.json()

    async def schedule_consult(
        self, name: str, phone: str, slot_iso: str, call_id: str | None = None
    ) -> dict:
        if self.v1:
            return await self._post(
                "/v1/tools/schedule_consult",
                {"call_id": call_id or "unknown", "name": name, "phone": phone, "slot_iso": slot_iso},
            )
        return await self._post(
            "/schedule", {"name": name, "phone": phone, "slot_iso": slot_iso}
        )

    async def write_to_cms(self, call_id: str, summary: str, structured: dict) -> dict:
        if self.v1:
            return await self._post(
                "/v1/calls/complete",
                {"call_id": call_id, "summary": summary, "structured": structured},
            )
        return await self._post(
            "/mock-cms", {"call_id": call_id, "summary": summary, "structured": structured}
        )

    # --- Phase 1-only tools ---

    async def lookup_caller(self, phone: str) -> dict:
        return await self._post("/v1/tools/lookup_caller", {"phone": phone})

    async def transfer_to_human(self, call_id: str, reason: str) -> dict:
        return await self._post(
            "/v1/tools/transfer_to_human", {"call_id": call_id, "reason": reason}
        )

    async def send_sms(self, call_id: str, to: str, body: str) -> dict:
        return await self._post("/v1/tools/send_sms", {"call_id": call_id, "to": to, "body": body})

    async def take_message(self, call_id: str, caller_name: str, phone: str, body: str) -> dict:
        return await self._post(
            "/v1/tools/take_message",
            {"call_id": call_id, "caller_name": caller_name, "phone": phone, "body": body},
        )

    async def post_transcript(
        self, call_id: str, turns: list[dict], summary: str | None = None
    ) -> None:
        """Best-effort transcript persistence at call end (v1 only)."""
        if not self.v1:
            return
        try:
            r = await self._client.post(
                f"/v1/calls/{call_id}/transcript", json={"turns": turns, "summary": summary}
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("failed to post transcript for %s: %s", call_id, exc)

    # --- metrics (both modes) ---

    async def post_turn_metrics(self, turn: dict) -> None:
        """Fire-and-forget from the worker's perspective: metrics must never
        break a live call, so failures are logged and swallowed."""
        path = "/v1/metrics/turn" if self.v1 else "/metrics/turn"
        try:
            r = await self._client.post(path, json=turn)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("failed to post turn metrics: %s", exc)

    async def call_latency_summary(self, call_id: str) -> dict:
        path = f"/v1/metrics/calls/{call_id}" if self.v1 else f"/metrics/calls/{call_id}"
        r = await self._client.get(path)
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self._client.aclose()
