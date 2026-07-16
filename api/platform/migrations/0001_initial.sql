-- Phase 1 initial migration: full data model (architecture doc §6) with
-- firm_id on every tenant row and row-level security enforced from day one.
--
-- Two-role model:
--   * the migration/owner role (whatever runs this file) bypasses RLS by
--     default (table owner) and is used only for platform operations:
--     migrations, token auth lookup, firm onboarding, the event worker.
--   * caseline_app is the tenant-scoped role every request-path query runs
--     as. It is not the table owner, so RLS applies unconditionally. The
--     firm context arrives via `SET LOCAL app.firm_id = '<uuid>'`; with no
--     context set, every policy evaluates to NULL and returns nothing.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'caseline_app') THEN
        CREATE ROLE caseline_app LOGIN;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Tenancy root
-- ---------------------------------------------------------------------------

CREATE TABLE firms (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                text NOT NULL,
    timezone            text NOT NULL DEFAULT 'America/Chicago',
    business_hours      jsonb NOT NULL DEFAULT '{}'::jsonb,
    cms_provider        text NOT NULL DEFAULT 'mock',
    cms_credentials_enc text,          -- Fernet/KMS ciphertext, never plaintext
    plan                text NOT NULL DEFAULT 'design_partner',
    retention_days      integer NOT NULL DEFAULT 365,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE firm_tokens (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id     uuid NOT NULL REFERENCES firms(id),
    name        text NOT NULL,
    token_hash  text NOT NULL UNIQUE,   -- sha256 hex; raw token never stored
    created_at  timestamptz NOT NULL DEFAULT now(),
    revoked_at  timestamptz
);

-- ---------------------------------------------------------------------------
-- Tenant data
-- ---------------------------------------------------------------------------

CREATE TABLE agents (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             uuid NOT NULL REFERENCES firms(id),
    name                text NOT NULL,
    role                text NOT NULL DEFAULT 'intaker'
                        CHECK (role IN ('receptionist', 'intaker', 'chaser')),
    voice_id            text,
    script_config       jsonb NOT NULL DEFAULT '{}'::jsonb,
    routing_rules       jsonb NOT NULL DEFAULT '{}'::jsonb,
    qualification_rules jsonb NOT NULL DEFAULT '{}'::jsonb,
    guardrails          jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE contacts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         uuid NOT NULL REFERENCES firms(id),
    name            text NOT NULL,
    phone           text,
    email           text,
    external_cms_id text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX contacts_firm_phone ON contacts (firm_id, phone);

CREATE TABLE calls (
    id              text NOT NULL,      -- LiveKit room name / call id
    firm_id         uuid NOT NULL REFERENCES firms(id),
    agent_id        uuid REFERENCES agents(id),
    direction       text NOT NULL DEFAULT 'in' CHECK (direction IN ('in', 'out')),
    from_number     text,
    to_number       text,
    started_at      timestamptz NOT NULL DEFAULT now(),
    ended_at        timestamptz,
    outcome         text,
    caller_type     text,
    summary         text,
    structured      jsonb,
    recording_uri   text,
    latency_p50_ms  real,
    latency_p95_ms  real,
    PRIMARY KEY (firm_id, id)
);

CREATE TABLE transcripts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id     uuid NOT NULL REFERENCES firms(id),
    call_id     text NOT NULL,
    turns       jsonb NOT NULL,         -- [{role, text, ts}]
    summary     text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (firm_id, call_id)
);

CREATE TABLE leads (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             uuid NOT NULL REFERENCES firms(id),
    source              text NOT NULL DEFAULT 'phone'
                        CHECK (source IN ('phone', 'web', 'ad', 'email', 'sms')),
    contact_id          uuid REFERENCES contacts(id),
    call_id             text,
    status              text NOT NULL DEFAULT 'new',
    qualification       jsonb,
    practice_area       text,
    assigned_attorney   text,
    external_cms_id     text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE matters (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         uuid NOT NULL REFERENCES firms(id),
    lead_id         uuid REFERENCES leads(id),
    external_cms_id text,
    practice_area   text,
    status          text NOT NULL DEFAULT 'pending',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tasks (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         uuid NOT NULL REFERENCES firms(id),
    matter_id       uuid REFERENCES matters(id),
    type            text NOT NULL,
    due_at          timestamptz,
    status          text NOT NULL DEFAULT 'open',
    external_cms_id text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id     uuid NOT NULL REFERENCES firms(id),
    channel     text NOT NULL CHECK (channel IN ('sms', 'email', 'voice_note')),
    thread_id   text,
    direction   text NOT NULL CHECK (direction IN ('in', 'out')),
    body        text NOT NULL,
    ts          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE consults (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         uuid NOT NULL REFERENCES firms(id),
    lead_id         uuid REFERENCES leads(id),
    name            text NOT NULL,
    phone           text NOT NULL,
    slot_at         timestamptz NOT NULL,
    idempotency_key text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (firm_id, idempotency_key)
);

CREATE TABLE turn_metrics (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    firm_id     uuid NOT NULL REFERENCES firms(id),
    call_id     text NOT NULL,
    speech_id   text NOT NULL,
    eou_delay_ms real NOT NULL,
    llm_ttft_ms real NOT NULL,
    tts_ttfb_ms real NOT NULL,
    total_ms    real NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX turn_metrics_firm_call ON turn_metrics (firm_id, call_id);

-- ---------------------------------------------------------------------------
-- Append-only event log (audit trail + outbox for async consumers)
-- ---------------------------------------------------------------------------

CREATE TABLE events (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    firm_id         uuid NOT NULL REFERENCES firms(id),
    type            text NOT NULL,
    payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    -- consumer bookkeeping (written only by the platform worker role)
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processed', 'dead')),
    attempts        integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    processed_at    timestamptz,
    last_error      text
);
CREATE INDEX events_pending ON events (next_attempt_at) WHERE status = 'pending';

-- Idempotency ledger for external writes (CMS etc.). One row per logical
-- write; retries look the key up and reuse the stored external id instead of
-- writing twice.
CREATE TABLE idempotency_keys (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    firm_id     uuid NOT NULL REFERENCES firms(id),
    key         text NOT NULL,
    target      text NOT NULL,          -- e.g. 'clio:contact'
    external_id text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (firm_id, key)
);

-- ---------------------------------------------------------------------------
-- Row-level security: every tenant table, from the first migration.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'agents', 'contacts', 'calls', 'transcripts', 'leads', 'matters',
        'tasks', 'messages', 'consults', 'turn_metrics', 'events',
        'idempotency_keys'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY firm_isolation ON %I '
            'USING (firm_id = nullif(current_setting(''app.firm_id'', true), '''')::uuid) '
            'WITH CHECK (firm_id = nullif(current_setting(''app.firm_id'', true), '''')::uuid)',
            t
        );
    END LOOP;
END
$$;

-- A firm may read its own row (name, hours, plan) but nothing else's, and
-- never another firm's credentials. Only the platform role writes firms.
ALTER TABLE firms ENABLE ROW LEVEL SECURITY;
CREATE POLICY firm_self ON firms
    USING (id = nullif(current_setting('app.firm_id', true), '')::uuid);

-- Tokens are looked up pre-auth by the platform role only; the app role
-- gets no access at all.
ALTER TABLE firm_tokens ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- Grants: the app role can read/write tenant data but can never delete, and
-- can never touch consumer bookkeeping on the append-only event log.
-- ---------------------------------------------------------------------------

GRANT SELECT ON firms TO caseline_app;
GRANT SELECT, INSERT, UPDATE ON agents, contacts, calls, transcripts, leads,
    matters, tasks, messages, consults TO caseline_app;
GRANT SELECT, INSERT ON turn_metrics, events, idempotency_keys TO caseline_app;
GRANT UPDATE (external_id) ON idempotency_keys TO caseline_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO caseline_app;
