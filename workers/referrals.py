"""Referral consumer (Phase 4): mounts into the single outbox consumer loop.

Same shape as ``workers/omnichannel.OmniProcessor`` — one binary, one claim
protocol, no competing consumers. Owns the ``lead.qualified`` event type:
refer_out decisions get a referral proposal; everything else is a no-op.
"""

from __future__ import annotations

import logging

from api import referrals
from api.platform import events as platform_events
from api.platform.db import Database

logger = logging.getLogger("caseline.workers.referrals")


class ReferralProcessor:
    def __init__(self, db: Database):
        self.db = db

    def handlers(self) -> dict:
        return {"lead.qualified": self._handle_lead_qualified}

    def _handle_lead_qualified(self, event: platform_events.Event) -> None:
        if event.payload.get("decision") != "refer_out":
            return  # qualified/declined leads are not referral candidates
        referrals.propose_for_lead(self.db, event.firm_id, event.payload)
