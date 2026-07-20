-- Let operators delete a cloned voice from the dashboard.
--
-- The app role could create, read, and reassign voice profiles but not remove
-- them (0004 granted only SELECT, INSERT, UPDATE). Deleting is a normal operator
-- action — a bad clone, a revoked consent, cleaning up test voices — so grant
-- DELETE. Row-level security still applies: the existing firm_isolation policy's
-- USING clause governs DELETE too, so a firm can only delete its own voices.
GRANT DELETE ON voice_profiles TO caseline_app;
