-- Phase 2 hardening migration.
--
--  * Token scopes: raw (unredacted) transcript access becomes an explicit
--    grant (`transcripts:raw`) instead of something every firm token gets.
--  * Provider columns on turn_metrics so latency can be sliced by which
--    STT/LLM/TTS actually served the turn (failover makes this dynamic).
--  * Redacted transcript column: the default read path serves redacted
--    turns; raw turns are the gated exception, not the rule.
--  * Event claim hardening: a `processing` state + visibility timeout closes
--    the double-claim race between concurrent workers (a claim used to
--    release its row locks on commit while the event stayed `pending`).

ALTER TABLE firm_tokens ADD COLUMN scopes text[] NOT NULL DEFAULT '{}';

ALTER TABLE turn_metrics
    ADD COLUMN stt_provider text,
    ADD COLUMN llm_provider text,
    ADD COLUMN tts_provider text;

ALTER TABLE transcripts ADD COLUMN turns_redacted jsonb;

-- Consent bookkeeping: which policy applied to the call (caller state,
-- whether two-party consent rules governed the recording disclosure).
ALTER TABLE calls
    ADD COLUMN consent_state text,
    ADD COLUMN two_party_consent boolean;

-- Event claim hardening -------------------------------------------------

ALTER TABLE events DROP CONSTRAINT events_status_check;
ALTER TABLE events ADD CONSTRAINT events_status_check
    CHECK (status IN ('pending', 'processing', 'processed', 'dead'));
ALTER TABLE events ADD COLUMN claimed_at timestamptz;

-- Requeue scan for crashed workers (visibility timeout) and DLQ listing.
CREATE INDEX events_processing ON events (claimed_at) WHERE status = 'processing';
CREATE INDEX events_dead ON events (id) WHERE status = 'dead';

-- Analytics read paths (per-firm, time-windowed).
CREATE INDEX calls_firm_started ON calls (firm_id, started_at DESC);
CREATE INDEX leads_firm_created ON leads (firm_id, created_at DESC);
CREATE INDEX turn_metrics_firm_created ON turn_metrics (firm_id, created_at);
CREATE INDEX events_firm_type_created ON events (firm_id, type, created_at);
