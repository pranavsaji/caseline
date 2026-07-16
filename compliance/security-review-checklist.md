# Security review checklist (Phase 2 exit criterion)

Self-assessment against the platform as built. ✅ = enforced in code and
tested; ⚠️ = built, needs a live environment to fully verify; ☐ = open.

## Tenancy & data access
- ✅ RLS on every tenant table from the first migration; cross-tenant reads
  return nothing, cross-tenant writes raise (tested at DB and API level)
- ✅ Request-path queries run as a non-owner role — RLS cannot be bypassed
- ✅ App role cannot DELETE tenant data or mutate the append-only event log
- ✅ Analytics endpoints return aggregates only (asserted PII-free in tests)

## Secrets & credentials
- ✅ CMS credentials ciphertext at rest (Fernet local / KMS prod); rotated
  OAuth tokens re-encrypted on refresh, all three adapters
- ✅ Service tokens stored as sha256 only; shown once at issuance
- ✅ No secrets in the repo; `.env` is gitignored, `.env.example` documents keys
- ✅ Firm dashboard token stays server-side (Next.js route handlers)

## PII / PHI
- ✅ Redaction pipeline: transcripts stored with a redacted copy served by
  default; raw access requires an explicit `transcripts:raw` scope
- ✅ Log redaction filter installed in every process (API, workers)
- ✅ Structured payload redaction is key-aware (a field named `phone` is PII
  regardless of its value's shape)
- ✅ Per-state recording consent, safe default two-party for unknown callers;
  consent policy recorded per call

## Injection & input handling
- ✅ SQL always parameterized (psycopg placeholders throughout)
- ✅ SOQL string literals escaped in the Litify adapter (tested with an
  injection attempt)
- ✅ Config writes validated by pydantic before persisting; invalid config
  can never reach a live call
- ✅ Rate limiting per token (429s tested); admin plane gated separately

## Guardrails (agent output)
- ✅ Two-layer output filter between LLM and TTS (regex + inline classifier),
  sentence-granularity streaming, deflection line on trip
- ✅ Per-firm blocklists; classifier verdicts auditable (category, score,
  features)

## Reliability & abuse
- ✅ Idempotency keys on every external write; retried/raced events cannot
  duplicate CMS records (proven under concurrent workers + fault injection)
- ✅ DLQ with human replay tooling; alerting on latency/error/backlog
- ⚠️ Provider failover proven at the adapter level (chaos test); full
  voice-path cutover needs live provider accounts
- ☐ Dependency vulnerability scanning in CI (add once CI exists)
- ☐ External penetration test (pre-GA)
