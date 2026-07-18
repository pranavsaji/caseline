-- Dashboard operator accounts: gate human access to the Next.js dashboard.
--
-- Distinct from firm_tokens (that is machine auth — a service token the Next
-- server holds to call the backend). These rows are PEOPLE who sign up and log
-- in to view the dashboard. Kept global (not RLS-scoped): this is access-control
-- infrastructure for the operator UI, not per-tenant business data, so it lives
-- on the platform role like schema_migrations and firm_tokens.
--
-- Passwords are never stored in the clear — password_hash holds a self-describing
-- pbkdf2_sha256 string (algo$iterations$salt$hash), verified in dashboard_auth.py.
CREATE TABLE IF NOT EXISTS dashboard_users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
