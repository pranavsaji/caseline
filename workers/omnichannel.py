"""Omnichannel consumer (Phase 3): the Digital Lead Chaser + thread advancer.

Registers handlers into the single outbox consumer loop (workers/cms_sync.py
builds one ``EventProcessor`` with these attached — one binary, one claim
protocol, no competing consumers):

  * ``lead.created``     — speed-to-lead: first outbound contact within
    seconds of a webform/ad submission, gated by the TCPA outbound policy
    (consent required; quiet hours defer, never drop).
  * ``message.received`` — advance the open SMS/email thread one turn
    through the same brain the voice worker runs.

It also ticks the ``followups`` scheduler: chaser nudges, deferred chaser
starts, deferred outbound dials, and treatment-tracker check-ins. Followups
are claimed FOR UPDATE SKIP LOCKED and marked done *before* execution:
at-most-once semantics, chosen deliberately — a missed nudge is an
inconvenience, a double-texted client is a compliance problem.
"""

from __future__ import annotations

import json
import logging

from api.compliance.outbound import outbound_policy
from api.messaging import EmailProvider, SMSProvider
from api.orchestration.config import load_agent_config
from api.orchestration.threads import ThreadEngine
from api.platform import events as platform_events
from api.platform.db import Database
from api.platform.session_state import SessionStore
from api.telephony import OutboundDialer

logger = logging.getLogger("caseline.workers.omnichannel")


class OmniProcessor:
    def __init__(
        self,
        db: Database,
        store: SessionStore,
        sms: SMSProvider,
        email: EmailProvider,
        dialer: OutboundDialer,
    ):
        self.db = db
        self.store = store
        self.dialer = dialer
        self.engine = ThreadEngine(db, store, sms, email)

    def handlers(self) -> dict:
        """Event handlers to register into the outbox consumer."""
        return {
            "lead.created": self._handle_lead_created,
            "message.received": self._handle_message_received,
        }

    # --- chaser kickoff ---

    def _handle_lead_created(self, event: platform_events.Event) -> None:
        payload = event.payload
        firm_id = event.firm_id
        config = load_agent_config(self.db, self.store, firm_id)
        if config is None:
            raise RuntimeError(f"firm {firm_id} has no configured agent")
        phone = payload.get("phone")
        email_address = payload.get("email")
        preferred = payload.get("preferred_channel") or ("sms" if phone else "email")
        consent = bool(payload.get("sms_consent"))

        if preferred in ("sms", "voice") and phone:
            policy = outbound_policy(phone, consent=consent, firm_timezone=config.timezone)
            if not policy.allowed and policy.defer_until is None:
                # No consent: automated outbound is illegal, full stop. Surface
                # it for a human to follow up instead of silently dropping.
                with self.db.firm(firm_id) as conn:
                    platform_events.emit(
                        conn,
                        firm_id,
                        "lead.chase_blocked",
                        {"lead_id": payload.get("lead_id"), "reason": policy.reason},
                    )
                logger.info("lead %s not chased: %s", payload.get("lead_id"), policy.reason)
                return
            if preferred == "voice":
                if policy.allowed:
                    self._dial_lead(firm_id, payload)
                else:
                    self._defer(firm_id, "chaser.dial", policy.defer_until, payload)
                return
            if policy.allowed:
                self.engine.start_intake_thread(
                    firm_id,
                    channel="sms",
                    address=phone,
                    contact_id=payload.get("contact_id"),
                    lead_id=payload.get("lead_id"),
                    name=payload.get("name"),
                    source=payload.get("source", "web"),
                )
            else:
                self._defer(
                    firm_id,
                    "chaser.start",
                    policy.defer_until,
                    {
                        "channel": "sms",
                        "address": phone,
                        "contact_id": payload.get("contact_id"),
                        "lead_id": payload.get("lead_id"),
                        "name": payload.get("name"),
                        "source": payload.get("source", "web"),
                    },
                )
            return

        if email_address:
            # Email has no TCPA quiet hours; a webform submission is a direct
            # business inquiry, and every message carries the opt-out line.
            self.engine.start_intake_thread(
                firm_id,
                channel="email",
                address=email_address,
                contact_id=payload.get("contact_id"),
                lead_id=payload.get("lead_id"),
                name=payload.get("name"),
                source=payload.get("source", "web"),
            )
            return

        with self.db.firm(firm_id) as conn:
            platform_events.emit(
                conn,
                firm_id,
                "lead.chase_blocked",
                {"lead_id": payload.get("lead_id"), "reason": "no reachable address on lead"},
            )

    def _defer(self, firm_id: str, type_: str, due_at, payload: dict) -> None:
        with self.db.firm(firm_id) as conn:
            conn.execute(
                "INSERT INTO followups (firm_id, thread_id, type, due_at, payload)"
                " VALUES (%s, NULL, %s, %s, %s)",
                (firm_id, type_, due_at, json.dumps(payload)),
            )
        logger.info("chase deferred to %s (%s)", due_at, type_)

    def _dial_lead(self, firm_id: str, payload: dict) -> None:
        """Outbound voice chase: create the call row + audit event, then hand
        the dial to the SIP layer. The agent worker picks the call up in the
        LiveKit room exactly like an inbound one."""
        phone = payload["phone"]
        lead_id = payload.get("lead_id")
        room = f"outbound-{lead_id or phone}"
        with self.db.firm(firm_id) as conn:
            config = load_agent_config(self.db, self.store, firm_id)
            conn.execute(
                "INSERT INTO calls (id, firm_id, agent_id, direction, to_number)"
                " VALUES (%s, %s, %s, 'out', %s) ON CONFLICT (firm_id, id) DO NOTHING",
                (room, firm_id, config.agent_id if config else None, phone),
            )
            if lead_id:
                conn.execute(
                    "UPDATE leads SET first_contact_at = now(), status = 'contacted'"
                    " WHERE id = %s AND first_contact_at IS NULL",
                    (lead_id,),
                )
            platform_events.emit(
                conn,
                firm_id,
                "call.outbound_requested",
                {"call_id": room, "lead_id": lead_id, "to": phone, "dialer": self.dialer.name},
            )
        self.dialer.dial(phone, room, metadata={"lead_id": lead_id, "firm_id": firm_id})

    # --- inbound messages ---

    def _handle_message_received(self, event: platform_events.Event) -> None:
        payload = event.payload
        self.engine.handle_inbound(
            event.firm_id,
            channel=payload.get("channel", "sms"),
            address=payload["address"],
            body=payload.get("body", ""),
        )

    # --- scheduled followups ---

    def process_due_followups(self, limit: int = 20) -> dict[str, int]:
        """Claim and execute due followups. Claimed rows are marked done in
        the claim transaction (at-most-once); execution outcomes are logged."""
        counts: dict[str, int] = {"executed": 0, "failed": 0}
        with self.db.admin() as conn:
            batch = conn.execute(
                "UPDATE followups SET status = 'done', done_at = now()"
                " WHERE id IN ("
                "   SELECT id FROM followups WHERE status = 'pending' AND due_at <= now()"
                "   ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED)"
                " RETURNING id, firm_id, thread_id, type, payload",
                (limit,),
            ).fetchall()
        for row in batch:
            firm_id = str(row["firm_id"])
            try:
                if row["type"] == "chaser.dial":
                    self._dial_lead(firm_id, row["payload"] or {})
                    outcome = "dialed"
                else:
                    outcome = self.engine.run_followup(firm_id, dict(row))
                counts["executed"] += 1
                logger.info("followup %s (%s): %s", row["id"], row["type"], outcome)
            except Exception:  # noqa: BLE001 — one bad followup must not kill the loop
                counts["failed"] += 1
                logger.exception("followup %s (%s) failed", row["id"], row["type"])
        return counts
