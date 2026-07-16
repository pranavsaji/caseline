# Caseline

AI voice intake employee for law firms. Answers calls in a natural voice, qualifies leads against the firm's rules, books consults, and syncs structured records into the firm's case management system — with per-turn latency instrumentation and tenant isolation built in from the start.

- Architecture: [`caseline-voice-intake-architecture.md`](caseline-voice-intake-architecture.md)
- Phased plan + progress tracking: [`plan.md`](plan.md)

## Status

| Phase | State |
|---|---|
| Phase 0 — Prototype (voice pipeline, mock CMS, latency instrumentation) | Code complete & tested; live-call validation blocked on provider credentials |
| Phase 1 — Foundation (multi-tenant platform, per-firm config, guardrails, Clio, dashboard) | Code complete & tested (see plan.md for exit-criteria detail) |
| Phase 2 — Hardening (failover, redaction, consent, classifier, analytics/alerts, Filevine+Litify, load test, IaC) | Code complete & tested; 50-call load test PASS; cloud apply blocked on GCP/provider accounts |

## Stack

| Layer | Choice |
|---|---|
| Transport | LiveKit (Cloud SIP inbound trunk from Twilio/Telnyx) |
| Agent framework | LiveKit Agents (Python), cascading pipeline |
| STT / LLM / TTS | Deepgram Nova-3 / Claude Haiku 4.5 / Cartesia Sonic-3 — each stage behind a health-check-driven failover stack (`CASELINE_{STT,LLM,TTS}_PROVIDERS`, OpenAI as optional secondary) |
| Turn-taking | Silero VAD + multilingual semantic end-of-utterance model |
| Backend | FastAPI; Postgres (RLS multi-tenancy) + append-only events outbox |
| Session state | Redis (in-memory fallback for local dev) |
| CMS sync | Async worker behind `CaseManagementProvider` interface (Clio, Filevine, Litify + mock) |
| Dashboard | Next.js (TypeScript), incl. analytics (funnel + latency by day/provider) |
| Compliance | PII redaction pipeline (transcripts/logs), per-state recording consent, 2-layer guardrails (regex + inline classifier) |
| Infra (written, not yet applied) | Terraform + Helm for GKE/Cloud SQL/Memorystore/Pub-Sub/GCS/KMS (`deploy/`) |

## Layout

```
agent/                    # LiveKit Agents voice worker
  agent.py                #   pipeline wiring, typed tools, guardrail LLM->TTS pass
  providers.py            #   STT/LLM/TTS failover stacks (FallbackAdapter, provider labels)
  backend_client.py       #   HTTP client (Phase 0 + /v1 modes; livekit-free, testable)
  latency.py              #   per-turn latency stitching + p50/p95 (livekit-free)
api/
  main.py                 #   app factory: Phase 0 routes + Phase 1 platform mount
  routes_v1.py            #   multi-tenant /v1 API (admin, config, tools, calls, metrics,
                          #   analytics, admin ops: queue overview / DLQ replay / alerts)
  qualification.py        #   qualification rules engine (pure functions)
  tools/                  #   typed tool layer (deterministic; LLM only selects)
  orchestration/          #   per-firm agent config + 2-layer guardrails (regex + classifier)
  compliance/             #   PII redaction pipeline + per-state consent policy
  messaging/              #   SMS provider seam (Twilio / logging)
  platform/               #   db+RLS, migrations, events outbox, auth, secrets, alerts
  storage.py, schemas.py  #   Phase 0 prototype (SQLite) — kept for keyless local runs
integrations/             # CaseManagementProvider ABC + normalized schema;
                          #   clio.py, filevine.py, litify.py, mock.py
workers/cms_sync.py       # event consumer: idempotent CMS writes, retry + DLQ, alert loop
frontend/                 # Next.js dashboard: calls/leads, transcript+latency, analytics, config
deploy/                   # Terraform (GCP) + Helm chart — written, not applied (no GCP account)
compliance/               # SOC 2 groundwork, vendor inventory, security-review checklist
scripts/onboard_firm.py   # CLI onboarding (firm + agent + service token)
scripts/load_test.py      # 50-concurrent-call load test + end-state duplicate audit
tests/                    # pytest suite incl. ephemeral-Postgres RLS verification
```

## Setup

Requires Python ≥3.12 and [uv](https://docs.astral.sh/uv/). Postgres 16 + Node 20+ for the Phase 1 platform/dashboard.

```bash
uv sync                       # creates .venv and installs everything
cp .env.example .env          # then fill in what you need (see comments)
```

## Tests (no API keys or network needed)

```bash
uv run pytest -v
```

135 tests: the qualification engine, every Phase 0 endpoint, latency stitching, the agent→backend contract, the Phase 1 platform — RLS cross-tenant isolation (against a real throwaway Postgres the suite boots itself), token auth + rate limiting, guardrails, typed tools, idempotency under fault injection, event retry/dead-letter/replay, the Clio adapter (mocked transport), a full simulated-firm end-to-end run — plus the Phase 2 hardening layer: PII redaction + scoped raw-transcript access, per-state consent, the inline guardrail classifier (with a <5 ms p95 perf gate), mid-call LLM failover chaos tests, concurrent-worker claim safety, DLQ replay + alert evaluation, analytics endpoints, and the Filevine/Litify adapters.

## Run the platform (Phase 1)

```bash
# 1. Backend (needs CASELINE_DATABASE_URL, CASELINE_SECRETS_KEY, CASELINE_ADMIN_TOKEN;
#    migrations apply on boot)
uv run uvicorn api.main:app --port 8000

# 2. Onboard a firm (prints the service token exactly once)
uv run python scripts/onboard_firm.py --name "Bluebonnet Injury Law" \
  --cms mock --transfer-number +15125550199

# 3. CMS sync worker (consumes the events outbox; idempotent writes, DLQ)
uv run python -m workers.cms_sync

# 4. Voice worker (set CASELINE_FIRM_TOKEN from step 2 to use the /v1 API;
#    leave it empty for the Phase 0 single-tenant path)
uv run python -m agent.agent download-files   # one-time: turn-detector + VAD models
uv run python -m agent.agent console          # local mic/speaker, no telephony
uv run python -m agent.agent dev              # connect to LiveKit, take real calls

# 5. Dashboard
cd frontend && npm install
CASELINE_API_URL=http://localhost:8000 CASELINE_FIRM_TOKEN=cl_... npm run dev
```

**Telephony (marquee demo):** buy a Twilio number, point it at a LiveKit Cloud SIP inbound trunk, add a dispatch rule that routes to this agent. See architecture doc §7.3.

## Load test (Phase 2)

Against a running stack (backend + worker + Postgres):

```bash
uv run python scripts/load_test.py --base-url http://localhost:8000 \
  --admin-token $CASELINE_ADMIN_TOKEN --calls 50          # realistic pacing
# --think 0  = stress mode: every request in the same instant (burst capacity probe)
```

Drives 50 concurrent synthetic calls through the full tool path (including a
forced duplicate booking per call), reports per-endpoint p50/p95, waits for
the outbox to drain, and audits the end state: exactly one lead + one consult
per call, zero dead letters. Exit code 0 only if the SLO held and nothing
duplicated. Sizing knobs it will surface: `CASELINE_DB_POOL_SIZE`,
`CASELINE_RATE_LIMIT_PER_MINUTE`, uvicorn `--workers`.

## Design rules that hold in every phase

- **≤800 ms p95 turn latency** is a hard ceiling; every call's per-stage breakdown is stored and rolled up (`/v1/metrics/calls/{id}`, dashboard).
- **The hot path is sacred:** CMS writes and analytics run async off the events outbox — never inline from the voice worker.
- **Tenancy is enforced by Postgres RLS**, set from the first migration, verified by tests that run cross-tenant queries as the app role.
- **Every external write carries an idempotency key** — retries can never duplicate a matter or double-book a consult.
- **Providers live behind interfaces** (STT/LLM/TTS/SMS/CMS); swapping is config, not a rewrite.
- **Guardrails in-pipeline:** two layers between LLM and TTS — a regex screen plus an inline lexical classifier that catches paraphrases — block legal advice, fee quotes, and outcome guarantees (p95 < 5 ms, perf-gated in tests; the classifier sits behind a Protocol seam an ML model can replace).
- **PII stays inside:** transcripts are redacted at write time and served redacted by default (`transcripts:raw` scope for the exception); every process logs through a redaction filter.
