-- Phase 4 differentiation migration.
--
--  * voice_profiles: per-firm branded/cloned voices. A profile is created
--    only with the voice owner's recorded consent; assignment to an agent
--    requires status = 'ready'.
--  * lead_reviews: attorney accept/reject verdicts on leads — the training
--    signal for per-firm qualification tuning. One verdict per lead (an
--    attorney re-reviewing overwrites their prior verdict).
--  * referral_partners + referrals: the smart-referral network. A referral
--    is proposed automatically for declined-but-viable (refer_out) leads,
--    but nothing leaves the system until a human sends it with client
--    consent recorded.

CREATE TABLE voice_profiles (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id            uuid NOT NULL REFERENCES firms(id),
    name               text NOT NULL,
    provider           text NOT NULL DEFAULT 'mock',
    provider_voice_id  text,
    status             text NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'ready', 'failed')),
    -- Voice cloning without the speaker's consent is off the table, ever.
    consent_confirmed  boolean NOT NULL DEFAULT false CHECK (consent_confirmed),
    sample_uri         text,
    error              text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX voice_profiles_firm ON voice_profiles (firm_id, created_at DESC);

CREATE TABLE lead_reviews (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id     uuid NOT NULL REFERENCES firms(id),
    lead_id     uuid NOT NULL REFERENCES leads(id),
    verdict     text NOT NULL CHECK (verdict IN ('accepted', 'rejected')),
    reviewer    text,
    reason      text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (firm_id, lead_id)
);

CREATE TABLE referral_partners (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         uuid NOT NULL REFERENCES firms(id),
    name            text NOT NULL,
    practice_areas  text[] NOT NULL DEFAULT '{}',
    states          text[] NOT NULL DEFAULT '{}',
    contact_email   text,
    contact_phone   text,
    active          boolean NOT NULL DEFAULT true,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX referral_partners_firm ON referral_partners (firm_id) WHERE active;

CREATE TABLE referrals (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id        uuid NOT NULL REFERENCES firms(id),
    lead_id        uuid NOT NULL REFERENCES leads(id),
    partner_id     uuid NOT NULL REFERENCES referral_partners(id),
    status         text NOT NULL DEFAULT 'proposed'
                   CHECK (status IN ('proposed', 'sent', 'accepted', 'declined')),
    match_reasons  jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- What the partner receives: case facts only, assembled at send time.
    packet         jsonb NOT NULL DEFAULT '{}'::jsonb,
    client_consent boolean NOT NULL DEFAULT false,
    sent_at        timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    -- One referral per lead: an event retry must never propose twice.
    UNIQUE (firm_id, lead_id)
);
CREATE INDEX referrals_firm_status ON referrals (firm_id, status);

-- Row-level security + grants, same posture as every other tenant table.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['voice_profiles', 'lead_reviews', 'referral_partners', 'referrals'] LOOP
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

GRANT SELECT, INSERT, UPDATE ON voice_profiles, lead_reviews, referral_partners, referrals
    TO caseline_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO caseline_app;
