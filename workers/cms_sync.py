"""CMS sync worker: consumes events and performs idempotent CMS writes.

The only component that talks to a firm's CMS. Consumes the events outbox
(claim -> handle -> mark), with:

  * per-write idempotency keys derived from the event id — a retried event
    reuses the same keys, so a half-completed write finishes instead of
    duplicating (Phase 1 exit criterion: idempotent under forced retry);
  * exponential backoff + dead-letter after MAX_ATTEMPTS (events.mark_failed);
  * per-firm provider construction from encrypted credentials, decrypted
    only in memory, with rotated OAuth tokens re-encrypted on refresh.

Run:  uv run python -m workers.cms_sync
"""

from __future__ import annotations

import json
import logging
import os
import time

import psycopg

from api.platform import alerts, events
from api.platform.db import Database
from api.platform.secrets import SecretsCipher, make_cipher
from integrations import CaseManagementProvider, Contact, Matter, Note, Task, get_provider_class

logger = logging.getLogger("caseline.workers.cms_sync")


class EventProcessor:
    def __init__(
        self,
        db: Database,
        cipher: SecretsCipher,
        provider_overrides: dict[str, CaseManagementProvider] | None = None,
        extra_handlers: dict | None = None,
    ):
        self.db = db
        self.cipher = cipher
        # firm_id -> provider, for tests and for connection reuse
        self._providers: dict[str, CaseManagementProvider] = dict(provider_overrides or {})
        # type -> handler. Phase 3 mounts the omnichannel handlers here so the
        # outbox keeps exactly one consumer loop (no competing claimers).
        self._handlers: dict = {
            "call.completed": self._handle_call_completed,
            "consult.booked": self._handle_consult_booked,
            "tracker.update": self._handle_tracker_update,
            **(extra_handlers or {}),
        }

    # --- provider plumbing ---

    def _provider_for(self, firm_id: str) -> CaseManagementProvider:
        if firm_id in self._providers:
            return self._providers[firm_id]
        with self.db.admin() as conn:
            firm = conn.execute(
                "SELECT cms_provider, cms_credentials_enc FROM firms WHERE id = %s", (firm_id,)
            ).fetchone()
        if firm is None:
            raise RuntimeError(f"firm {firm_id} not found")
        credentials = (
            self.cipher.decrypt(firm["cms_credentials_enc"]) if firm["cms_credentials_enc"] else {}
        )
        cls = get_provider_class(firm["cms_provider"])
        kwargs = dict(credentials)
        # Every OAuth-style adapter rotates tokens; rotated credentials are
        # merged and re-encrypted at rest, never logged, never plaintext.
        if firm["cms_provider"] in ("clio", "filevine", "litify"):
            kwargs["on_token_refresh"] = lambda rotated: self._persist_rotated_tokens(
                firm_id, credentials, rotated
            )
        provider = cls(**kwargs)
        self._providers[firm_id] = provider
        return provider

    def _persist_rotated_tokens(self, firm_id: str, credentials: dict, rotated: dict) -> None:
        merged = {**credentials, **rotated}
        with self.db.admin() as conn:
            conn.execute(
                "UPDATE firms SET cms_credentials_enc = %s WHERE id = %s",
                (self.cipher.encrypt(merged), firm_id),
            )
        logger.info("persisted rotated CMS tokens for firm %s", firm_id)

    # --- idempotency ledger ---

    def _idempotent_write(
        self, conn: psycopg.Connection, firm_id: str, key: str, target: str, write
    ) -> str:
        """Perform ``write()`` at most once per (firm, key). Retries return
        the recorded external id without touching the provider again."""
        row = conn.execute(
            "SELECT external_id FROM idempotency_keys WHERE firm_id = %s AND key = %s",
            (firm_id, key),
        ).fetchone()
        if row and row["external_id"]:
            return row["external_id"]
        external_id = write(key)
        conn.execute(
            "INSERT INTO idempotency_keys (firm_id, key, target, external_id)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (firm_id, key) DO UPDATE SET external_id = EXCLUDED.external_id",
            (firm_id, key, target, external_id),
        )
        conn.commit()  # ledger entry survives even if a later step fails
        return external_id

    # --- handlers ---

    def _handle_call_completed(self, event: events.Event) -> None:
        payload = event.payload
        structured = payload.get("structured") or {}
        name = structured.get("name") or structured.get("caller_name")
        phone = structured.get("phone")
        if not name:
            logger.info("event %s has no caller identity; nothing to sync", event.id)
            return
        provider = self._provider_for(event.firm_id)
        with self.db.admin() as conn:
            contact_id = self._idempotent_write(
                conn,
                event.firm_id,
                f"evt{event.id}:contact",
                f"{provider.name}:contact",
                lambda key: provider.upsert_contact(Contact(name=name, phone=phone), key),
            )
            matter_id = self._idempotent_write(
                conn,
                event.firm_id,
                f"evt{event.id}:matter",
                f"{provider.name}:matter",
                lambda key: provider.create_matter(
                    Matter(
                        description=payload.get("summary") or "Caseline intake",
                        practice_area=structured.get("practice_area"),
                    ),
                    contact_id,
                    key,
                ),
            )
            self._idempotent_write(
                conn,
                event.firm_id,
                f"evt{event.id}:note",
                f"{provider.name}:note",
                lambda key: provider.add_note(
                    Note(
                        subject="Caseline intake call",
                        detail=json.dumps(
                            {"summary": payload.get("summary"), "structured": structured},
                            indent=2,
                        ),
                    ),
                    matter_id,
                    key,
                ),
            )
            # Reflect external ids back onto local rows (bi-directional sync).
            if payload.get("contact_id"):
                conn.execute(
                    "UPDATE contacts SET external_cms_id = %s"
                    " WHERE firm_id = %s AND id = %s AND external_cms_id IS NULL",
                    (contact_id, event.firm_id, payload["contact_id"]),
                )
            conn.execute(
                "UPDATE leads SET external_cms_id = %s"
                " WHERE firm_id = %s AND call_id = %s AND external_cms_id IS NULL",
                (matter_id, event.firm_id, payload.get("call_id")),
            )

    def _handle_consult_booked(self, event: events.Event) -> None:
        payload = event.payload
        provider = self._provider_for(event.firm_id)
        with self.db.admin() as conn:
            self._idempotent_write(
                conn,
                event.firm_id,
                f"evt{event.id}:task",
                f"{provider.name}:task",
                lambda key: provider.create_task(
                    Task(name=f"Consultation with {payload['name']} at {payload['slot_iso']}"),
                    None,
                    key,
                ),
            )

    def _handle_tracker_update(self, event: events.Event) -> None:
        """Treatment-tracker update -> a task in the firm's CMS (Phase 3)."""
        payload = event.payload
        provider = self._provider_for(event.firm_id)
        who = payload.get("name") or payload.get("phone") or "client"
        kind = payload.get("kind", "progress")
        note = (payload.get("note") or "").strip()
        matter = payload.get("matter_description")
        detail = f"Treatment {kind} from {who}"
        if matter:
            detail += f" ({matter})"
        if note:
            detail += f": {note[:200]}"
        with self.db.admin() as conn:
            self._idempotent_write(
                conn,
                event.firm_id,
                f"evt{event.id}:task",
                f"{provider.name}:task",
                lambda key: provider.create_task(Task(name=detail), None, key),
            )

    # --- the loop ---

    def process_once(self, limit: int = 20) -> dict[str, int]:
        """Claim and process one batch. Returns counters for observability."""
        counts = {"processed": 0, "retried": 0, "dead": 0, "skipped": 0}
        with self.db.admin() as conn:
            # Claim inside one short transaction; per-event outcome is
            # written in its own transaction below so a crash mid-batch
            # loses no bookkeeping.
            batch = events.claim_pending(conn, limit=limit)
        for event in batch:
            try:
                handler = self._handlers.get(event.type)
                if handler is not None:
                    handler(event)
                else:
                    counts["skipped"] += 1  # no consumer for this type yet
                with self.db.admin() as conn:
                    events.mark_processed(conn, event.id)
                if handler is not None:
                    counts["processed"] += 1
            except Exception as exc:  # noqa: BLE001 — worker must never die on one event
                logger.warning("event %s failed (attempt %s): %s", event.id, event.attempts + 1, exc)
                with self.db.admin() as conn:
                    status = events.mark_failed(conn, event.id, event.attempts, str(exc))
                counts["dead" if status == "dead" else "retried"] += 1
        return counts

    def close(self) -> None:
        for provider in self._providers.values():
            provider.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv

    from api.compliance.redaction import install_log_redaction

    load_dotenv()
    install_log_redaction()
    dsn = os.environ["CASELINE_DATABASE_URL"]
    db = Database(dsn)
    db.migrate()
    # Phase 3: the omnichannel processor (chaser, threads, followups) mounts
    # into the same consumer loop — the outbox keeps exactly one claimer.
    from api.messaging import make_email_provider, make_sms_provider
    from api.platform.session_state import make_session_store
    from api.telephony import make_dialer
    from workers.omnichannel import OmniProcessor
    from workers.referrals import ReferralProcessor

    omni = OmniProcessor(
        db, make_session_store(), make_sms_provider(), make_email_provider(), make_dialer()
    )
    # Phase 4: smart referrals consume lead.qualified in the same loop.
    referrals = ReferralProcessor(db)
    processor = EventProcessor(
        db, make_cipher(), extra_handlers={**omni.handlers(), **referrals.handlers()}
    )
    poll_seconds = float(os.getenv("CASELINE_WORKER_POLL_SECONDS", "1.0"))
    # Backpressure: the claim batch bounds in-flight work per poll; a flooded
    # outbox drains at a steady rate instead of ballooning worker memory.
    batch_size = int(os.getenv("CASELINE_WORKER_BATCH_SIZE", "20"))
    alert_every = max(int(float(os.getenv("CASELINE_ALERT_INTERVAL_SECONDS", "60")) / poll_seconds), 1)
    logger.info("event worker polling every %.1fs (batch %s)", poll_seconds, batch_size)
    ticks = 0
    try:
        while True:
            counts = processor.process_once(limit=batch_size)
            counts |= omni.process_due_followups(limit=batch_size)
            if any(counts.values()):
                logger.info("batch: %s", counts)
            ticks += 1
            if ticks % alert_every == 0:
                firing = alerts.evaluate(db)
                if firing:
                    alerts.log_alerts(firing)
                    alerts.notify(firing)
            time.sleep(poll_seconds)
    finally:
        processor.close()
        db.close()


if __name__ == "__main__":
    main()
