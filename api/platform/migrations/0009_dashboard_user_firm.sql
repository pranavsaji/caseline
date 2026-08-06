-- Bind each dashboard operator account to the firm whose data they see.
--
-- Before this, dashboard_users held only credentials and the Next server
-- resolved the tenant from a single deploy-wide CASELINE_FIRM_TOKEN — so every
-- operator, whichever account they signed in with, landed on the same firm.
-- That is fine for one design partner and wrong the moment there are two.
--
-- firm_id is nullable on purpose: NULL means "no firm bound", and the Next
-- server falls back to CASELINE_FIRM_TOKEN for that session. That keeps every
-- pre-existing account working through the deploy, and keeps single-tenant
-- installs (which never set this) on exactly the path they had before.
--
-- ON DELETE CASCADE: a firm's operators are meaningless once the firm is gone,
-- and leaving them pointed at a dead uuid would silently fall back to the
-- default firm — i.e. show them someone else's data. Deleting is the safe read.
ALTER TABLE dashboard_users
    ADD COLUMN IF NOT EXISTS firm_id uuid REFERENCES firms(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS dashboard_users_firm_id_idx ON dashboard_users (firm_id);
