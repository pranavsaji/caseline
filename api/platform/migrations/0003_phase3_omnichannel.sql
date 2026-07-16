-- Phase 3 omnichannel migration.
--
--  * threads: async SMS/email conversations running the same orchestration
--    policy as voice calls. State lives here, not in a held connection.
--  * followups: scheduled work (chaser nudges, tracker check-ins). Unlike
--    events (append-only audit log) a followup can be canceled, so it gets
--    its own claimable table instead of overloading the outbox.
--  * Outbound consent (TCPA): automated outbound contact requires prior
--    express consent, tracked per contact per channel, revocable (STOP).
--  * leads.first_contact_at: the chaser speed metric (lead-to-first-contact
--    under 60 s is the Phase 3 exit criterion — measure it, don't assert it).

CREATE TABLE threads (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id          uuid NOT NULL REFERENCES firms(id),
    channel          text NOT NULL CHECK (channel IN ('sms', 'email')),
    address          text NOT NULL,      -- phone (sms) or email address
    contact_id       uuid REFERENCES contacts(id),
    lead_id          uuid REFERENCES leads(id),
    goal             text NOT NULL DEFAULT 'intake'
                     CHECK (goal IN ('intake', 'treatment_tracker')),
    status           text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    state            jsonb NOT NULL DEFAULT '{}'::jsonb,  -- step + collected slots
    closed_reason    text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    last_outbound_at timestamptz,
    last_inbound_at  timestamptz
);
-- One live conversation per (firm, channel, address): an inbound message
-- always has exactly one open thread to land in.
CREATE UNIQUE INDEX threads_open_per_address ON threads (firm_id, channel, address)
    WHERE status = 'open';
CREATE INDEX threads_firm_updated ON threads (firm_id, updated_at DESC);

CREATE TABLE followups (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    firm_id     uuid NOT NULL REFERENCES firms(id),
    thread_id   uuid REFERENCES threads(id),
    type        text NOT NULL,           -- chaser.start | chaser.nudge | tracker.checkin
    due_at      timestamptz NOT NULL,
    status      text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'done', 'canceled')),
    payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    done_at     timestamptz
);
CREATE INDEX followups_due ON followups (due_at) WHERE status = 'pending';

-- TCPA consent bookkeeping: prior express consent per contact, revocable.
ALTER TABLE contacts
    ADD COLUMN sms_consent boolean,
    ADD COLUMN sms_consent_source text,
    ADD COLUMN sms_opt_out_at timestamptz;

-- Webform payload + chaser speed metric.
ALTER TABLE leads
    ADD COLUMN details jsonb,
    ADD COLUMN first_contact_at timestamptz;

-- Row-level security + grants, same posture as every other tenant table.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['threads', 'followups'] LOOP
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

GRANT SELECT, INSERT, UPDATE ON threads, followups TO caseline_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO caseline_app;
