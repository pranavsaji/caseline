# Caseline

AI voice intake employee for law firms. Answers calls in a natural voice, qualifies leads against the firm's rules, books consults, and syncs structured records into the firm's case management system — with per-turn latency instrumentation and tenant isolation built in from the start.

- Architecture: [`caseline-voice-intake-architecture.md`](caseline-voice-intake-architecture.md)
- Phased plan + progress tracking: [`plan.md`](plan.md)

## Status

| Phase | State |
|---|---|
| Phase 0 — Prototype (voice pipeline, mock CMS, latency instrumentation) | Code complete & tested; live-call validation blocked on provider credentials |
| Phase 1 — Foundation (multi-tenant platform, per-firm config, guardrails, Clio, dashboard) | Code complete & tested (see plan.md for exit-criteria detail) |

## Stack

| Layer | Choice |
|---|---|
| Transport | LiveKit (Cloud SIP inbound trunk from Twilio/Telnyx) |
| Agent framework | LiveKit Agents (Python), cascading pipeline |
| STT / LLM / TTS | Deepgram Nova-3 / Claude Haiku 4.5 / Cartesia Sonic-3 |
| Turn-taking | Silero VAD + multilingual semantic end-of-utterance model |
| Backend | FastAPI; Postgres (RLS multi-tenancy) + append-only events outbox |
| Session state | Redis (in-memory fallback for local dev) |
| CMS sync | Async worker behind `CaseManagementProvider` interface (Clio + mock) |
| Dashboard | Next.js (TypeScript) |

## Layout

```
agent/                    # LiveKit Agents voice worker
  agent.py                #   pipeline wiring, typed tools, guardrail LLM->TTS pass
  backend_client.py       #   HTTP client (Phase 0 + /v1 modes; livekit-free, testable)
  latency.py              #   per-turn latency stitching + p50/p95 (livekit-free)
api/
  main.py                 #   app factory: Phase 0 routes + Phase 1 platform mount
  routes_v1.py            #   multi-tenant /v1 API (admin, config, tools, calls, metrics)
  qualification.py        #   qualification rules engine (pure functions)
  tools/                  #   typed tool layer (deterministic; LLM only selects)
  orchestration/          #   per-firm agent config + guardrail output filter
  messaging/              #   SMS provider seam (Twilio / logging)
  platform/               #   db+RLS, migrations, events outbox, auth, secrets, session state
  storage.py, schemas.py  #   Phase 0 prototype (SQLite) — kept for keyless local runs
integrations/             # CaseManagementProvider ABC + normalized schema; clio.py, mock.py
workers/cms_sync.py       # event consumer: idempotent CMS writes, retry + DLQ
frontend/                 # Next.js dashboard: calls/leads, transcript+latency, config editing
scripts/onboard_firm.py   # CLI onboarding (firm + agent + service token)
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

83 tests: the qualification engine, every Phase 0 endpoint, latency stitching, the agent→backend contract, and the Phase 1 platform — RLS cross-tenant isolation (against a real throwaway Postgres the suite boots itself), token auth + rate limiting, guardrails, typed tools, idempotency under fault injection, event retry/dead-letter/replay, the Clio adapter (mocked transport), and a full simulated-firm end-to-end run.

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

## Design rules that hold in every phase

- **≤800 ms p95 turn latency** is a hard ceiling; every call's per-stage breakdown is stored and rolled up (`/v1/metrics/calls/{id}`, dashboard).
- **The hot path is sacred:** CMS writes and analytics run async off the events outbox — never inline from the voice worker.
- **Tenancy is enforced by Postgres RLS**, set from the first migration, verified by tests that run cross-tenant queries as the app role.
- **Every external write carries an idempotency key** — retries can never duplicate a matter or double-book a consult.
- **Providers live behind interfaces** (STT/LLM/TTS/SMS/CMS); swapping is config, not a rewrite.
- **Guardrails in-pipeline:** a regex screen between LLM and TTS blocks legal advice, fee quotes, and outcome guarantees (sub-ms; the ML classifier lands in Phase 2).
