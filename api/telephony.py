"""Outbound dialing behind one interface (Phase 3 Digital Lead Chaser).

Outbound calls reuse the existing SIP layer: LiveKit creates a room, the
agent worker joins it, and a SIP participant dials the lead. Locally (and in
tests) ``LoggingDialer`` records the intent; ``LiveKitSIPDialer`` is the real
transport, constructed only when LiveKit credentials + an outbound trunk are
configured. Swapping is config, not a rewrite (guiding principle #3).
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger("caseline.telephony")


class OutboundDialer(ABC):
    name: str

    @abstractmethod
    def dial(self, to_number: str, room_name: str, metadata: dict | None = None) -> str:
        """Place an outbound call; returns a provider call/participant id."""


class LoggingDialer(OutboundDialer):
    name = "logging"

    def __init__(self) -> None:
        self.dialed: list[dict] = []  # inspectable by tests and local dev

    def dial(self, to_number: str, room_name: str, metadata: dict | None = None) -> str:
        call_id = f"log-dial-{len(self.dialed) + 1}"
        self.dialed.append(
            {"id": call_id, "to": to_number, "room": room_name, "metadata": metadata or {}}
        )
        logger.info("DIAL (logged, not placed) to=%s room=%s", to_number, room_name)
        return call_id


class LiveKitSIPDialer(OutboundDialer):
    """Dials via a LiveKit SIP outbound trunk. Import-lazy: only constructed
    when LIVEKIT_* + CASELINE_SIP_OUTBOUND_TRUNK_ID are configured."""

    name = "livekit"

    def __init__(self, url: str, api_key: str, api_secret: str, trunk_id: str):
        self._url, self._key, self._secret = url, api_key, api_secret
        self._trunk_id = trunk_id

    def dial(self, to_number: str, room_name: str, metadata: dict | None = None) -> str:
        import asyncio
        import json

        from livekit import api  # type: ignore[import-not-found]

        async def _place() -> str:
            lk = api.LiveKitAPI(self._url, self._key, self._secret)
            try:
                participant = await lk.sip.create_sip_participant(
                    api.CreateSIPParticipantRequest(
                        sip_trunk_id=self._trunk_id,
                        sip_call_to=to_number,
                        room_name=room_name,
                        participant_identity=f"phone-{to_number}",
                        participant_metadata=json.dumps(metadata or {}),
                    )
                )
                return participant.participant_id
            finally:
                await lk.aclose()

        return asyncio.run(_place())


def make_dialer() -> OutboundDialer:
    url = os.getenv("LIVEKIT_URL")
    key = os.getenv("LIVEKIT_API_KEY")
    secret = os.getenv("LIVEKIT_API_SECRET")
    trunk = os.getenv("CASELINE_SIP_OUTBOUND_TRUNK_ID")
    if url and key and secret and trunk:
        return LiveKitSIPDialer(url, key, secret, trunk)
    return LoggingDialer()
