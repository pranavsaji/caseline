# SOC 2 Type II Groundwork (Phase 2 Workstream C)

Status: groundwork, not an audit. This maps what the platform already
enforces in code to the Trust Services Criteria, and lists the
organizational controls that need an owner before an audit window opens.
Firms will ask for this before they sign — keep it current.

## Access control (CC6)

| Control | Implementation | Evidence |
|---|---|---|
| Tenant isolation | Postgres RLS on every tenant table from migration 0001; app role is non-owner so RLS is unconditional | `tests/test_rls.py` (cross-tenant SELECT/INSERT verified at DB + API) |
| Least-privilege DB roles | `caseline_app` cannot DELETE tenant data, cannot UPDATE the append-only event log; owner role is platform-ops only | migration 0001 grants; `tests/test_rls.py` |
| Credential storage | CMS credentials encrypted at rest (Fernet locally, Cloud KMS in prod); raw service tokens never stored (sha256 only) | `api/platform/secrets.py`, `api/platform/auth.py` |
| Scoped access | Raw (unredacted) transcripts require an explicit `transcripts:raw` token scope; default tokens read redacted copies only | `tests/test_compliance.py` |
| Admin plane separation | Onboarding/ops endpoints gated by a deploy-level admin token, not firm tokens | `tests/test_ops_reliability.py::test_ops_endpoints_require_admin_token` |

## Audit logging & change management (CC7/CC8)

- Append-only `events` table is the audit trail: every meaningful action
  (qualification, booking, transfer, message, call completion) is an event
  written in the same transaction as the state change. The app role cannot
  update or delete events (enforced by grants, tested).
- PII is redacted before log sinks (`RedactingFilter` installed in every
  process) and before analytics (aggregates only).
- Schema changes are numbered SQL migrations tracked in `schema_migrations`;
  code changes land via reviewed commits (repo history is the change log).

## Availability (A1)

- Provider failover per pipeline stage (STT/LLM/TTS FallbackAdapters),
  DLQ + replay for event consumers, alerting on latency regression, error
  spikes, and backlog (`api/platform/alerts.py`).
- Load-tested: 50 concurrent synthetic calls at SLO with zero duplicate
  external writes (`scripts/load_test.py`, results in plan.md).

## Confidentiality (C1)

- Per-firm retention (`firms.retention_days`) + GCS lifecycle ceiling.
- Recording consent handled per state (two-party consent states force the
  disclosure line; unknown callers get the safe default).

## Organizational controls still needing an owner (pre-audit backlog)

- [ ] Vendor inventory & review cadence — see `vendor-inventory.md`
- [ ] Written policies: infosec, incident response, BC/DR, acceptable use
- [ ] Employee access reviews (quarterly) + offboarding checklist
- [ ] Pen test / vulnerability scanning cadence
- [ ] Subprocessor list + DPAs with providers (Deepgram, Anthropic, Cartesia,
      OpenAI, Twilio, LiveKit, Google Cloud)
- [ ] BAA evaluation: PI intake is HIPAA-adjacent; decide whether to sign
      BAAs with STT/LLM vendors that offer them
