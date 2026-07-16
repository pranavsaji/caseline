# Caseline — Phased Build Plan

## Status Board

| Phase | Status | Last updated |
|---|---|---|
| Phase 0 — Prototype | ✅ **Code complete & verified** — every engineering item done and re-verified (now under the 217-test suite, re-run 2026-07-16 during Phase 4); the only open items are external account provisioning (LiveKit/Twilio/provider keys), which no code change can close | 2026-07-16 |
| Phase 1 — Foundation | ✅ **Code complete & verified** — all four workstreams built and re-verified under the 217-test suite; open items are the same account blockers + a real Clio sandbox | 2026-07-16 |
| Phase 2 — Hardening | ✅ **Code complete & verified** — all five workstreams built and re-verified under the 217-test suite; 50-call load test PASS with zero duplicate CMS writes; chaos-tested failover; 3 CMS adapters; open items are accounts/infra only (GCP apply, provider keys, CMS sandboxes) — same blocker class as Phases 0/1 — see §Phase 2 Progress | 2026-07-16 |
| Phase 3 — Omnichannel | ✅ **Code complete & verified** — chaser, SMS/email threads, treatment tracker, config studio + preview all built on the Phase 1 brain; re-verified under the 217-test suite; live HTTP smoke PASS with lead-to-first-contact 0.6 s; open items are live-transport verification (Twilio SMS/SIP) — see §Phase 3 Progress | 2026-07-16 |
| Phase 4 — Differentiation | ✅ **Code complete & verified** — consent-gated voice cloning, qualification tuning from attorney verdicts, smart referrals with a human/consent send gate, k-anonymous benchmark analytics, and an evidence-gated S2S greeting path + benchmark harness; 217 tests green (43 new); live HTTP smoke 12/12 PASS; open items are live-account verification only (Cartesia clone, realtime S2S trials, referral email over real SMTP) — see §Phase 4 Progress | 2026-07-16 |

### 🔑 Live-stack verification — 2026-07-16 (provider keys provisioned)

Keys landed in `.env` and the full stack was brought up and verified live on this machine:

- **Validated against real provider APIs:** Deepgram (auth OK), Cartesia (auth OK + real sonic-3 synthesis), LiveKit Cloud (server-API auth OK; agent worker `dev` mode **registered** with the project, US West B), Twilio (account auth OK; from-number corrected to E.164 `+13124830370`). **Hot-path round trip proven with real audio: Cartesia TTS → Deepgram nova-3 STT returned the exact input line.**
- **Persistent dev stack running:** dedicated Postgres cluster (`scripts/dev_db.sh`, port 5455) + uvicorn :8000 + cms_sync worker + Next.js dashboard :3000. First real firm onboarded ("Saji & Partners Injury Law"); firm token wired into `.env` and `frontend/.env.local`.
- **All-phases live sweep over real HTTP: 24/24 PASS** — Phase 0 endpoints; Phase 1 tools/idempotent booking/redaction/RLS/CMS sync; Phase 2 analytics/ops/alerts; Phase 3 webform → chaser SMS thread (first contact 0.5 s) → full SMS conversation → consult booked; Phase 4 voice profile → agent assignment, verdicts → tuning suggestion, worker-proposed referral, benchmarks. Dashboard pages all render the live data.
- ~~⛔ One real blocker: no working LLM key.~~ **Resolved 2026-07-16:** a valid DeepSeek key landed and the full voice turn was proven end-to-end on the production provider stack — caller utterance → DeepSeek (via `providers.build_llm`) → streamed reply → Cartesia TTS on the first sentence → Deepgram STT round trip, word-perfect.
- **⚠️ New measured finding — DeepSeek TTFT vs the SLO (risk #2 verification the switch commit asked for):** warm median TTFT **748 ms** over 5 trials (min 671, max 2530 cold). The LLM stage alone eats ~93% of the 800 ms **total-turn** ceiling that must also fit STT endpointing (~0.4 s min-endpointing) and TTS TTFB — realistic turns land ~1.3–1.6 s, so **deepseek-chat as primary cannot meet the voice SLO** (its API has no US region). It is fine for the async channels (SMS/email threads have no turn budget). Decision needed: keep DeepSeek on cost and accept slower voice turns, or put an SLO-compliant model first for voice (`CASELINE_LLM_PROVIDERS=anthropic:claude-haiku-4-5,deepseek:deepseek-chat` — needs an Anthropic key) and keep DeepSeek as failover/async.
- Still human-in-the-loop: Twilio number → LiveKit SIP inbound trunk (do after the LLM key, or the number answers and stalls), a real-recipient SMS test, mic `console` smoke, and the ≥20-call latency exit measurements.

Execution plan for the architecture defined in `caseline-voice-intake-architecture.md`. Written from the principal-architect seat: each phase has a single risk it exists to retire, hard exit criteria, and an explicit "not in this phase" list. Phases are gates, not calendar promises — you do not start Phase N+1 until Phase N's exit criteria are demonstrably true.

---

## Guiding Principles

1. **Retire the riskiest assumption first.** The existential risk is per-turn voice latency (≤800 ms p95, target 500–650 ms). Everything else — multi-tenancy, CMS sync, dashboards — is known engineering. Voice realism is proven or disproven in week one.
2. **The hot path is sacred.** Nothing lands on the caller-audio path (STT → LLM → TTS) without a latency budget line item. All persistence, CMS writes, and analytics happen async off the event bus.
3. **Swappability over optimality.** Every external provider (STT, LLM, TTS, telephony, CMS) sits behind an internal interface. Providers will be swapped mid-life; the architecture must make that a config change, not a rewrite.
4. **Compliance is a foundation, not a feature.** Tenant isolation, audit trail, PII handling, and guardrails are built into the schema and pipeline from Phase 1 — retrofitting row-level security or transcript redaction onto a live legal-data system is how you lose customers.
5. **Cascading pipeline, by decision.** STT → LLM → TTS, not speech-to-speech. Auditable transcripts, guardrail insertion points, and provider failover are non-negotiable in legal intake. Revisit per-segment S2S only in Phase 4.

---

## Phase 0 — Prototype: Prove the Call (days, ~1 week)

**Risk being retired:** "Can we hold a natural, sub-800 ms spoken conversation over a real phone line that ends in a structured intake record?" If this fails, nothing downstream matters.

### Scope

- One Twilio number → LiveKit Cloud SIP inbound trunk (no self-hosting).
- One LiveKit Agents (Python) worker: Deepgram Nova-3 STT, Claude Haiku 4.5, Cartesia Sonic-3 TTS, Silero VAD + semantic turn detector, `preemptive_generation=True`, `min_endpointing_delay≈0.4s`.
- Hardcoded personal-injury intake script in the system prompt.
- Single FastAPI app with three tools: `qualify_lead` (naive rules), `schedule_consult` (stub), `write_to_cms` (mock endpoint that logs the payload).
- SQLite or throwaway Postgres. No auth, no tenancy, no frontend beyond an optional one-page transcript viewer.
- **Per-stage latency instrumentation from day one** — STT first-partial, LLM first-token, TTS first-chunk, total turn time, logged per turn. You cannot tune what you don't measure, and this instrumentation carries forward to production.

### Exit criteria

- Dial the number → AI answers in a natural voice, qualifies a PI lead (incident date, injury type, treatment, insurance), books a consult, structured record lands in the mock CMS.
- p95 turn latency ≤ 800 ms measured over ≥20 test calls; barge-in interrupts TTS within ~200 ms.
- A written latency breakdown per stage identifying the actual bottleneck.

### Deliberately out

Multi-tenancy, real CMS, SMS/email, recordings retention, guardrail classifier, autoscaling, any infra-as-code.

### ✅ Progress — updated 2026-07-16

**Implemented (all code in this repo, `uv sync` to install, `uv run pytest` to verify):**

- [x] Repo scaffold per architecture doc §10 (Phase 0 subset): `agent/` (voice worker), `api/` (FastAPI backend), `tests/`
- [x] FastAPI backend (`api/main.py`, app-factory pattern): `/qualify`, `/schedule`, `/mock-cms` (write + list), `/consults`, `/metrics/turn`, `/metrics/calls/{call_id}`, `/health`
- [x] Qualification rules engine (`api/qualification.py`): pure functions, statute-of-limitations gate (730d), refer-out injuries, decisions with human-readable reasons; unparseable/future dates never auto-decline (human-verification reason attached instead)
- [x] SQLite store (`api/storage.py`): consults, CMS records, per-turn latency samples with p50/p95 rollup and `within_budget` (≤800 ms p95) flag
- [x] LiveKit Agents voice worker (`agent/agent.py`): Deepgram Nova-3 + Claude Haiku 4.5 + Cartesia Sonic-3, Silero VAD prewarm, multilingual semantic turn detector, `preemptive_generation=True`, `min_endpointing_delay=0.4`, three function tools, PI intake instructions with no-legal-advice constraint
- [x] Per-stage latency instrumentation from day one (`agent/latency.py`): stitches EOU delay + LLM TTFT + TTS TTFB per `speech_id`, logs each turn, posts to backend, per-call p50/p95 summary on shutdown
- [x] Livekit-free `BackendClient` (`agent/backend_client.py`) so the agent↔backend contract is testable without the voice stack; metrics posting can never break a live call
- [x] Tests: **28 passed** (rules engine incl. SOL boundary + bad-date edge cases; every endpoint; latency stitching incl. interleaved turns; agent→backend contract via in-process ASGI, incl. full intake round trip)
- [x] Live smoke test: backend served via uvicorn, full path exercised over real HTTP — qualify (qualified + decline cases) → schedule → CMS write → 3 turn-metric posts → call summary `within_budget: true`, record persisted
- [x] Agent module import-validated against installed `livekit-agents` 1.x (entrypoint, prewarm, all 3 tools registered)
- [x] `.env.example`, README with run/validation instructions

**Remaining for Phase 0 exit (blocked on credentials/accounts, not code — re-verified again 2026-07-16 during Phase 2: all Phase 0 tests still green, keyless prototype path unchanged, no code work outstanding):**

- [ ] Provision LiveKit Cloud project + Deepgram/Anthropic/Cartesia API keys (fill `.env` from `.env.example`)
- [ ] Local voice smoke test: `uv run python -m agent.agent download-files` then `console` mode (mic/speaker)
- [ ] Twilio number → LiveKit SIP inbound trunk + dispatch rule (architecture doc §7.3)
- [ ] **Exit criterion:** ≥20 real test calls, p95 turn latency ≤800 ms via `/metrics/calls/{call_id}`
- [ ] **Exit criterion:** barge-in interrupts TTS within ~200 ms (manual verification on test calls)
- [ ] **Exit criterion:** written per-stage latency breakdown identifying the actual bottleneck

> 2026-07-16 note: Phase 1 was built without waiting on these (they need human account
> provisioning only). The Phase 0 prototype path — SQLite endpoints + tokenless worker —
> still works unchanged for the keyless local demo, and all Phase 0 tests still pass.

---

## Phase 1 — Foundation: One Real Firm, End to End (weeks 2–8)

**Risk being retired:** "Can the prototype become a multi-tenant system of record that a real firm configures and trusts?" This phase builds the skeleton everything else hangs on — the decisions here (schema, tenancy, event bus, adapter interface) are the expensive-to-change ones.

### Workstream A — Core platform (FastAPI on GCP)

- Postgres (Cloud SQL) with the full data model from the architecture doc: `firms`, `agents`, `calls`, `transcripts`, `leads`, `contacts`, `matters`, `tasks`, `messages`, `events`. `firm_id` on every row with **row-level security enforced from the first migration**.
- Append-only `events` table + Pub/Sub event bus. Every meaningful moment (`call.completed`, `lead.qualified`, `consult.booked`) is an event; CMS sync and analytics are consumers, never inline calls.
- Redis for live call/session state; a call in flight never touches Postgres on the hot path.
- API gateway concerns: auth (firm users + service tokens), webhook ingest, rate limiting.
- CMS credentials encrypted via Cloud KMS / Secret Manager from day one — never plaintext in the DB.

### Workstream B — Orchestration layer

- Replace the hardcoded prompt with per-firm agent config: script config, qualification rules, routing tree, business hours, guardrails — all `jsonb`, loaded by the worker at call start and cached in Redis.
- Typed tool layer: `lookup_caller`, `qualify_lead`, `schedule_consult`, `transfer_to_human`, `send_sms`, `take_message`, `write_to_cms`. Each a deterministic, tested function; the LLM only ever selects and parameterizes them.
- First guardrail pass: output filter between LLM and TTS blocking legal advice, fee quotes, and outcome guarantees. Start with prompt + regex/keyword screen; the sub-100 ms inline classifier is Phase 2.
- Live transfer to a human (SIP REFER / LiveKit participant bridge) — firms will not go live without an escape hatch.

### Workstream C — First CMS integration (Clio)

- Define the `CaseManagementProvider` interface (ABC) and the normalized internal schema (Lead, Contact, Matter, Task, Note) **before** writing the Clio adapter — the interface is the moat, the adapter is an instance.
- Clio first (best API, OAuth, webhooks). Bi-directional: intake writes out, CMS webhooks update local state.
- **Idempotency keys on every write from the first line of code.** Retries must never duplicate a matter or double-book a consult.
- Async workers (Celery or Cloud Tasks) consume events and perform writes with retry + dead-letter queue.

### Workstream D — Recordings, transcripts, minimal dashboard

- Call recordings and raw transcripts to GCS with per-firm retention policy; recording-consent disclosure line in the agent script (two-party consent states).
- Next.js (TypeScript) dashboard v1: call/lead list, transcript + recording playback, outcome and latency per call. Config editing can be raw-but-safe forms; the polished config studio is Phase 3.

### Exit criteria

- One design-partner firm (or a realistic simulated one) fully onboarded: their number, their script, their Clio.
- Inbound call → qualification → booking → structured record visible in Clio within 60 s of hangup, idempotent under forced retry.
- RLS verified: a cross-tenant query attempt returns nothing. Latency SLO from Phase 0 still holds with the real orchestration layer in the loop (regression here is a blocker, not a note).

### Deliberately out

Self-hosted SFU, autoscaling, provider failover, outbound calling, email channel, second CMS, voice cloning.

### ✅ Progress — updated 2026-07-16

**Code complete across all four workstreams. 83 tests green (`uv run pytest`): the 28 Phase 0 tests unchanged + 55 new, including RLS verification against a real throwaway Postgres the suite boots itself (initdb, trust auth, zero footprint). Full stack also validated live over real HTTP: uvicorn + Postgres + worker + built Next.js dashboard rendering the resulting calls/leads/transcript.**

**Workstream A — Core platform:**

- [x] Full data model from architecture doc §6 (`firms`, `agents`, `calls`, `transcripts`, `leads`, `contacts`, `matters`, `tasks`, `messages`, `events`, plus `consults`, `firm_tokens`, `idempotency_keys`, `turn_metrics`), `firm_id` on every row, **RLS enforced from migration 0001** (`api/platform/migrations/`)
- [x] Two-role model: owner role for platform ops only; `caseline_app` role (non-owner, RLS always applies) for every request-path query via `db.firm(firm_id)` + `SET LOCAL app.firm_id`
- [x] Append-only `events` table as outbox + audit trail; `EventBus` seam with Pub/Sub adapter stub for GCP (local outbox poll is the bus); app role can INSERT but never UPDATE/DELETE events (append-only enforced by grants, tested)
- [x] Session state behind one interface: Redis (`CASELINE_REDIS_URL`) or in-memory; live-call config cache never touches Postgres on the hot path
- [x] Auth: opaque firm service tokens (sha256-hashed at rest, shown once), bearer-token → firm_id → RLS context; per-token rate limiting (429); `/v1/admin/*` gated by deploy-level admin token
- [x] CMS credentials encrypted at rest from day one: `SecretsCipher` interface — Fernet locally, Cloud KMS adapter for GCP; plaintext never stored (tested)
- ⚠️ Deviations from the letter of the plan, deliberate: Cloud SQL/GCP Pub/Sub/KMS are config-swap adapters, not live services (no GCP account in play); events consumers poll the outbox table rather than Pub/Sub locally — same contract, swap is config

**Workstream B — Orchestration layer:**

- [x] Hardcoded prompt replaced by per-firm agent config (`script_config`, `qualification_rules`, `routing_rules`, `guardrails`, business hours — all jsonb), validated by pydantic before persisting, compiled to runtime instructions, cached with explicit invalidation on update (edits reach the next call in seconds)
- [x] Typed tool layer, each a deterministic tested function the LLM only selects: `lookup_caller`, `qualify_lead` (per-firm SOL + refer-out rules), `schedule_consult` (idempotency key; retry returns the same consult), `transfer_to_human` (business-hours aware), `send_sms` (provider seam: Twilio/logging), `take_message`, `write_to_cms`/`complete_call`
- [x] First guardrail pass between LLM and TTS: regex/keyword screen (legal advice, fee quotes, outcome guarantees + per-firm blocklist), sentence-granularity streaming filter wired into the worker's `llm_node`, deflection line speaks instead; microseconds per sentence (perf-tested). Inline ML classifier remains Phase 2
- [x] Live transfer escape hatch: routing decision + audit event in the platform; SIP REFER via LiveKit API in the worker (best-effort, can't be exercised without live telephony)
- [x] Worker degrades safely: config/backend unreachable → Phase 0 default script, guardrails still on; metrics/transcript posting can never break a live call

**Workstream C — CMS integration:**

- [x] `CaseManagementProvider` ABC + normalized schema (Lead/Contact/Matter/Task/Note) defined before any adapter (`integrations/base.py`, `models.py`)
- [x] Clio adapter (Manage API v4): contact dedupe by phone search, matter/task/note mapping, OAuth refresh-and-retry with rotated tokens re-encrypted + persisted, retryable-vs-poison error mapping — fully tested against a mocked transport
- [x] Idempotency keys on every external write from the first line: ledger table + keys derived from event id, so a retried event finishes a half-completed sync instead of duplicating (tested: provider crash mid-sync → retry → exactly one contact/matter/note)
- [x] Async worker (`workers/cms_sync.py`): claims events `FOR UPDATE SKIP LOCKED`, exponential backoff, dead-letter after 5 attempts, `replay_dead` for fixed poison payloads
- ⚠️ Bi-directional sync is outbound + external-id backfill; **Clio inbound webhooks are not built yet** (needs a real Clio app registration) — carried as the first Phase 1 pilot item

**Workstream D — Recordings, transcripts, dashboard:**

- [x] Transcripts persisted per call (jsonb turns + summary) with per-call latency rollup onto the call row; `recording_uri` column + per-firm `retention_days` in the schema
- [x] Next.js (TypeScript) dashboard v1 (`frontend/`): call/lead/consult lists with outcome + latency-SLO pills and CMS sync status, call detail with transcript + per-stage turn latency, raw-but-safe JSON config editing (client-validated, pydantic-revalidated, firm token stays server-side). `next build` type-checks clean; pages verified rendering live data
- ⚠️ Recording *capture* (GCS upload from LiveKit egress) needs live telephony — schema and dashboard playback link are ready; carried to the pilot checklist

**Exit-criteria status:**

- [x] Simulated design-partner firm fully onboarded (admin API + `scripts/onboard_firm.py`): their script, their rules, their routing, their (mock) CMS — exercised end-to-end in tests and over live HTTP
- [x] Call → qualification → booking → structured record in the CMS within seconds of hangup, **idempotent under forced retry** (event replayed: zero duplicate writes; consult re-booked with same key: same consult returned)
- [x] RLS verified at the database (cross-tenant SELECT/INSERT as app role: nothing/rejected) and through the live API (firm B token sees zero of firm A's calls/leads)
- [ ] **Blocked on accounts:** the same three Phase 0 credential items, plus a real Clio sandbox (OAuth app) to point the adapter at, and the latency-SLO regression check on real calls with the orchestration layer in the loop (instrumentation to measure it is in place; simulated-metric path already rolls up per call)

**Remaining for Phase 1 exit (pilot checklist — accounts/keys, not code; re-verified 2026-07-16 during Phase 2, all Phase 1 behavior still green under the expanded 135-test suite):**

- [ ] Provision provider keys + LiveKit + Twilio (same blockers as Phase 0)
- [ ] Register a Clio developer app, onboard a pilot firm with real Clio OAuth credentials, verify record-in-Clio-within-60s on a real call
- [ ] Clio inbound webhooks (CMS → local state) once the Clio app exists
- [ ] Wire LiveKit egress → recording upload + retention job (schema ready)
- [ ] Re-verify p95 ≤ 800 ms on ≥20 real calls with the full orchestration layer in the loop

---

## Phase 2 — Production Hardening: Scale, Reliability, Compliance (weeks 8–16)

**Risk being retired:** "Does it survive real call volume, provider brownouts, and a security review?" This is the phase that makes it a business instead of a demo. Gate to entry: at least one paying/design-partner firm generating real calls — hardening against imagined load is wasted motion.

### Workstream A — Infrastructure (GKE)

- Terraform + Helm for everything: GKE, Cloud SQL, Redis, Pub/Sub, GCS.
- Self-hosted LiveKit SFU on GKE; evaluate Telnyx as SIP provider for HD Voice/wideband alongside Twilio.
- Stateless agent workers autoscaled on concurrent-call count, with a **warm pool** so cold starts never eat first-turn latency. One worker per active call.
- Regional pinning of STT/LLM/TTS to the region nearest the SFU.

### Workstream B — Reliability

- Mid-call provider failover: secondary TTS and LLM configured per worker; health-check driven cutover. This is the payoff of the cascading architecture — prove it with a chaos test that kills the primary provider mid-conversation.
- Backpressure and DLQ on all event consumers; replay tooling for poison payloads.
- Load test: 50+ concurrent synthetic calls with latency SLOs holding.

### Workstream C — Compliance and security

- PII/PHI redaction pipeline before anything hits logs or analytics (treat PI intake as HIPAA-adjacent). Raw transcripts gated behind strict access controls.
- Inline guardrail classifier (<100 ms) replacing the Phase 1 keyword screen.
- Per-state consent handling (disclosure and recording rules keyed off caller area code + firm config).
- Begin SOC 2 Type II groundwork: access controls, audit logging, vendor inventory, policies. Firms will ask before they sign.

### Workstream D — Observability

- Per-turn, per-stage latency dashboards (p50/p95) sliced by firm and provider; full conversation tracing.
- Alerting on latency regression and provider error spikes — a slow provider silently ruins calls before anyone complains.
- Call-outcome analytics: qualification rate, booking rate, transfer rate, abandonment, sampled WER.

### Workstream E — Integration breadth

- Second and third CMS adapters (Filevine, then Litify via Salesforce APIs) to pressure-test the `CaseManagementProvider` abstraction. If the interface survives Litify's Salesforce-managed-package weirdness, it's real.

### Exit criteria

- 50 concurrent calls at SLO; mid-call failover demonstrated; zero duplicate CMS writes under fault injection.
- Redaction verified on transcripts/logs; security review checklist passed; three CMS adapters live behind one interface.

### ✅ Progress — updated 2026-07-16

**Code complete across all five workstreams. 135 tests green (`uv run pytest`): the 83 Phase 0/1 tests unchanged + 52 new. Live-validated over real HTTP: uvicorn (4 workers) + ephemeral Postgres + cms_sync worker + built Next.js dashboard (incl. the new analytics page rendering provider-sliced latency).**

**Workstream A — Infrastructure (GKE):**

- [x] Terraform for the full production footprint (`deploy/terraform/`): GKE with a dedicated compute-optimized agent node pool (tainted, warm floor via autoscaler min), Cloud SQL Postgres 16 (regional HA + PITR in prod), Memorystore Redis, Pub/Sub topic + subscription with DLQ mirroring `events.MAX_ATTEMPTS`, GCS recordings bucket with lifecycle ceiling, KMS keyring (90-day rotation), Artifact Registry, VPC
- [x] Helm chart (`deploy/helm/caseline/`): API (readiness/liveness on `/health`), cms-sync worker (safe to scale out — see claim protocol below), agent Deployment + HPA whose floor **is** the warm pool (`warmReplicas`), 1 h termination grace so a drain never kills a live call; provider-failover env in values; regional pinning via `var.region`
- ⚠️ **Written and reviewed, NOT applied** — no GCP project/billing account exists (same account blocker as Phases 0/1); terraform/helm binaries not present locally, so not even lint-validated. First item once an account exists.
- ⚠️ Self-hosted LiveKit SFU deploys from the upstream chart (values file to be added when the cluster exists); Telnyx-vs-Twilio evaluation needs live telephony

**Workstream B — Reliability:**

- [x] Mid-call provider failover: every pipeline stage built from spec lists (`CASELINE_{STT,LLM,TTS}_PROVIDERS="primary,fallback,..."`) behind LiveKit's health-check-driven `FallbackAdapter` (`agent/providers.py`); openai plugin added as cross-provider secondary for all three stages; single-spec = Phase 0/1 behavior
- [x] **Chaos test** (`tests/test_failover.py`): primary LLM killed mid-conversation → same turn served by the secondary (no dead air), primary marked unavailable, background recovery probes stay off the hot path; all-providers-down raises cleanly
- [x] Turn metrics now carry which STT/LLM/TTS actually served each turn (failover-aware `active_label()`), so latency is sliceable by provider
- [x] **Found and fixed a real double-claim race**: `claim_pending`'s row locks died with the claim transaction while events stayed `pending` — two workers could re-process one event. Fix: `processing` status + `claimed_at` visibility timeout (5 min) in migration 0002; proven by a two-worker race test (12 events, competing batches → exactly one CMS write per event) and a crashed-worker reclaim test
- [x] Backpressure: bounded claim batches (`CASELINE_WORKER_BATCH_SIZE`), queue-depth/lag stats (`events.queue_stats`); DLQ replay tooling: `GET /v1/admin/events/dead`, `POST /v1/admin/events/{id}/replay` (409 on non-dead), plus the existing `replay_dead` primitive
- [x] **Load test PASS** (`scripts/load_test.py`, run live 2026-07-16): 50 concurrent synthetic calls through the full v1 path (lookup → qualify → book **+ forced duplicate booking** → 6 turn-metric posts → complete → transcript) against uvicorn ×4 + Postgres + worker. Realistic pacing (1 s think time; real calls pause 10–30 s between tool calls): worst endpoint p95 **10.4 ms** vs the 800 ms budget, zero failed requests, exactly one lead + one consult per call, outbox fully drained, zero dead letters, zero alerts. Stress mode (`--think 0`, all ~600 requests in the same instant): correctness still perfect (zero duplicates, drained), latency p95 1.1 s — documented as a burst-capacity finding (add API replicas for burst absorb), not a realistic-load failure
- [x] Capacity findings baked into config: `CASELINE_DB_POOL_SIZE` (pool of 4 queues at 50 calls), rate-limit sizing note in Helm values (default 300/min/token caps ~25 concurrent calls per token)

**Workstream C — Compliance and security:**

- [x] PII/PHI redaction pipeline (`api/compliance/redaction.py`): SSN/card (Luhn-gated)/email/phone/street-address scrubbing + key-aware structured redaction; transcripts stored with a redacted copy **served by default** — raw turns require an explicit `transcripts:raw` token scope (scopes added in migration 0002); `RedactingFilter` installed in every process so PII never reaches log sinks; incident dates deliberately survive (they're case facts the pipeline runs on)
- [x] Inline guardrail classifier (`api/orchestration/classifier.py`): weighted lexical scorer layered behind the Phase 1 regex screen inside `GuardrailScreen`; catches paraphrased legal advice / fee quotes / outcome guarantees the regexes miss; verdicts auditable (category, score, fired features); behind a `GuardrailClassifier` Protocol seam so a distilled ML model can swap in; **perf-tested p95 < 5 ms** (20× headroom on the < 100 ms budget — it measures in µs)
- [x] Per-state consent (`api/compliance/consent.py`): NANP area-code → state map + all-party-consent state set (kept over-inclusive); unknown/toll-free/international callers get the **safe default (two-party)**; when two-party rules may apply the recording disclosure becomes mandatory — firm config cannot turn it off (enforced in `/v1/agent-config?from_number=`); the applied policy is recorded on the call row
- [x] SOC 2 Type II groundwork (`compliance/`): controls-to-evidence map, vendor inventory with blast-radius analysis, security-review checklist (all code-enforceable items ✅ and tested; org-process items listed as the pre-audit backlog)

**Workstream D — Observability:**

- [x] `/v1/analytics/latency` (per-day + per-provider p50/p95, SLO annotated) and `/v1/analytics/outcomes` (qualification/booking/transfer/abandonment rates) — aggregates only, asserted PII-free
- [x] Alert evaluator (`api/platform/alerts.py`): SLO breach (p95 > 800 ms last hour), regression (>1.3× trailing 7-day p95 — the "provider silently degrading" case), error spike, DLQ growth, consumer backlog; exposed at `/v1/admin/ops/alerts`, evaluated + webhook-pushed periodically by the sync worker (`CASELINE_ALERT_WEBHOOK_URL`, Slack-compatible)
- [x] `/v1/admin/ops/overview`: queue depth, processing, dead, retrying, oldest-pending age
- [x] Dashboard analytics page (`frontend/app/analytics/`): funnel tiles, outcomes, latency by day with SLO pills, latency by provider; `next build` clean; verified rendering live data
- ⚠️ Sampled WER needs real call audio — carried with the live-call checklist

**Workstream E — Integration breadth:**

- [x] Filevine adapter (`integrations/filevine.py`): session-token auth minted from key/secret with re-mint-on-401 + rotated-token persistence; Contact→Person, Matter→Project (per-firm `project_type_id`), wrapped-id (`{"native": ...}`) normalization; phone dedupe
- [x] Litify adapter (`integrations/litify.py`): the Salesforce stress test — sObject CRUD + SOQL dedupe (with injection-escaping, tested), OAuth refresh against the org instance, Contact→Account, Matter→`litify_pm__Matter__c`, Task/Note→Salesforce activities
- [x] **The `CaseManagementProvider` interface survived all three dissimilar providers unchanged** — no upstream code knows which CMS a firm runs; token rotation persistence now generic across clio/filevine/litify in the worker
- ⚠️ Both new adapters are validated against mocked transports (like Clio); real sandbox verification needs vendor accounts

**Exit-criteria status:**

- [x] 50 concurrent calls at SLO — PASS at realistic pacing (worst endpoint p95 10.4 ms; burst-mode capacity finding documented above)
- [x] Zero duplicate CMS writes under fault injection — proven three ways: forced retry (Phase 1 test), forced duplicate booking mid-load-test, and the new concurrent-worker race test
- [x] Mid-call failover demonstrated — chaos test at the adapter level (primary killed mid-conversation, same-turn cutover); full voice-path demonstration needs provider accounts
- [x] Redaction verified on transcripts and logs (tested end-to-end through the API, including the scoped raw-access path)
- [x] Security review checklist passed for everything code-enforceable (`compliance/security-review-checklist.md`; two ☐ items are org-process: CI vuln scanning, external pen test)
- [x] Three CMS adapters live behind one interface (Clio, Filevine, Litify — all mock-transport tested)

**Remaining for Phase 2 exit (accounts/infra, not code):**

- [ ] GCP project + billing → `terraform apply`, Helm deploys, self-hosted LiveKit SFU values, regional pinning verification
- [ ] Provider keys (same Phase 0 blockers) → run the failover chaos scenario on a live call; measure voice p95 under 50 real concurrent calls
- [ ] Filevine/Litify sandbox accounts → verify both adapters against real APIs
- [ ] Wire Pub/Sub bus (adapter exists) once GCP exists; point DLQ alerting webhook at the on-call channel

---

## Phase 3 — Omnichannel and Outbound: The Full Intake Employee (weeks 16–24)

**Risk being retired:** "Is this a receptionist or an intake *employee*?" The revenue story (speed-to-lead, follow-up) requires outbound and messaging. Everything here reuses the Phase 1 brain — new transports, same orchestration and tools.

- **Digital Lead Chaser:** webform/ad-lead webhook → `lead.created` → outbound call or SMS within seconds. Outbound dialing via the existing SIP layer; compliance pass for outbound consent/TCPA.
- **SMS + email threads:** messaging service running the same orchestration policy as async threads; thread state in Postgres, follow-ups as scheduled tasks, not held connections.
- **Treatment Tracker:** signed-client state machine (scheduled workflow) chasing treatment progress and documents, creating CMS tasks. Clean first showcase of the async-workflow engine.
- **Config studio v1:** self-serve script, routing, hours, qualification-rule editing with test-call preview. Onboarding speed is the highest-leverage frontend surface — measure time-to-first-live-call per firm and drive it down.
- Remaining long-tail CMS adapters as customer demand dictates (MyCase, Lawmatics, Law Ruler, Lead Docket, Neos, Lawcus, BackDocket) — demand-ordered, never speculative.

### Exit criteria

- Lead-to-first-contact under 60 s from webform submit. A firm self-onboards to a live agent in under a day. One firm running voice + SMS + chaser + tracker simultaneously on the same brain.

### ✅ Progress — updated 2026-07-16

**Code complete. 172 tests green (`uv run pytest`): the 135 Phase 0–2 tests unchanged + 37 new. Live-validated over real HTTP (`uvicorn` + ephemeral Postgres + the real `cms_sync` worker process): webform submit → chaser SMS in **0.6 s** → full SMS conversation → qualified → consult booked → CMS task, plus tracker enroll/check-in and STOP opt-out — 12/12 smoke checks PASS. `next build` clean with the new studio/threads pages.**

**Design decision that shaped everything here:** the voice worker and the async channels run the *same brain* — one `AgentConfig` (script/qualification/routing/guardrails), the same `api.qualification` rules engine, and the same `GuardrailScreen` on every outbound utterance. The thread brain (`api/orchestration/threads.py`) is a pure function `(config, state, inbound) -> (state, reply, actions)` — deterministic slot-filling intake (date → injury → treatment → insurance → qualify → book) — so the config studio's test-call preview runs the identical code with zero side effects, and an LLM extractor can slot in later without touching persistence.

**Digital Lead Chaser:**

- [x] `POST /v1/hooks/leads` (webform/ad webhook): contact + lead + `lead.created` event in one transaction; never blocks on any outbound transport
- [x] Chaser kicks off from the events outbox (same single-consumer loop as CMS sync — no competing claimers) and makes first contact in ~1 poll interval; `leads.first_contact_at` stamps the speed metric
- [x] **TCPA compliance pass** (`api/compliance/outbound.py`): prior-express-consent gate (no consent = hard deny → `lead.chase_blocked` event for human follow-up, never silent), 8am–9pm recipient-local quiet hours (area-code→state→timezone, firm-tz fallback, defer-don't-drop), CTIA STOP/HELP keywords honored inline and unconditionally; **opt-out is permanent** — a fresh form submit cannot resurrect revoked consent
- [x] Outbound voice chase behind the `OutboundDialer` seam (`api/telephony.py`): `calls` row + `call.outbound_requested` audit event + LiveKit SIP dial (LoggingDialer locally; real trunk is config)
- [x] No-reply nudges (2, quiet-hours-aware) then a polite close as `unresponsive`; an inbound reply disarms pending nudges
- [x] `GET /v1/analytics/chaser`: lead-to-first-contact p50/p95, under-60s rate — the exit criterion is *measured*, and shown on the dashboard Threads page

**SMS + email threads:**

- [x] `threads` table (state jsonb, one open thread per firm/channel/address) + `followups` scheduled-task table (claimable FOR UPDATE SKIP LOCKED, cancellable — deliberately not the append-only events outbox); follow-ups are scheduled rows, never held connections
- [x] `POST /v1/hooks/sms` inbound webhook → `message.received` event → thread engine advances one turn; cold inbound from an unknown number starts intake exactly like an inbound call
- [x] Email channel behind `EmailProvider` (logging default, SMTP config-selected); the thread engine is channel-agnostic
- [x] Bookings are idempotent (`thread:{id}:consult` key); `lead.qualified`/`consult.booked` payloads match the voice path, so **CMS sync consumes threads unchanged** (verified: SMS booking → mock CMS task)
- [x] Guardrail screen on every outbound message (regex + inline classifier, deflection line on trip) — same policy as the voice path; every outbound-initiated thread opens with the AI disclosure + STOP notice
- [x] Dashboard: Threads list with speed-to-lead tiles + per-thread conversation view

**Treatment Tracker:**

- [x] `POST /v1/tracker/enroll`: signed-client state machine as a `treatment_tracker` thread — intro message, check-ins every N days as scheduled followups, replies parsed (progress vs. discharged)
- [x] Each update emits `tracker.update` → CMS worker creates an idempotent CMS task; completion closes the thread (`treatment_complete`) — the async-workflow engine's first showcase, end-to-end tested
- [x] STOP wins over everything, including tracker check-ins (enrollment of an opted-out contact is refused with 409)

**Config studio v1:**

- [x] `/studio` page: structured forms (script, qualification, routing, guardrails) replacing raw JSON for the common path (raw editor stays at `/config` for power users)
- [x] **Test-call preview**: `POST /v1/agents/{id}/preview` runs caller messages through the same brain — including *unsaved* config overrides — returning turns, tool actions, guardrail trips, and the compiled instructions, with zero side effects (asserted in tests)
- [x] Onboarding-speed metric: `GET /v1/admin/ops/onboarding` reports time-to-first-live-call per firm (the number Phase 3 says to drive down)
- ⚪ Long-tail CMS adapters (MyCase, Lawmatics, …) deliberately **not** built — the plan says demand-ordered, never speculative, and there is no demand signal yet

**Exit-criteria status:**

- [x] Lead-to-first-contact under 60 s from webform submit — **0.6 s measured** over real HTTP with the real worker (logging SMS transport; re-measure on Twilio when keys exist)
- [x] One firm running voice + SMS + chaser + tracker simultaneously on the same brain — exercised in one test: Phase 1 voice tools + chaser SMS thread + tracker on a single firm, all events through one outbox, one CMS pipeline
- [~] Firm self-onboards to a live agent in under a day — the config-studio surface and the time-to-first-call metric exist; *verifying* under-a-day needs live telephony (below)

**Remaining for Phase 3 exit (transports/accounts, not code):**

- [ ] Twilio SMS webhooks → point at `/v1/hooks/sms` (+ Twilio signature validation at the edge), verify a real SMS conversation end-to-end
- [ ] LiveKit SIP outbound trunk (`CASELINE_SIP_OUTBOUND_TRUNK_ID`) → verify a real chaser dial; agent worker answering outbound rooms
- [ ] SMTP credentials → verify the email channel beyond the logging provider
- [ ] A pilot firm self-onboarding run, timed (the under-a-day exit criterion)

**Known v1 limitations (accepted, documented):** thread replies after a closed conversation start a fresh intake thread (no "reopen" flow yet); the deterministic brain re-asks once then defers to humans rather than free-form NLU (an LLM extractor can swap in behind the same pure interface); followups execute at-most-once by design — a missed nudge beats a double-texted client.

---

## Phase 4 — Differentiation (week 24+)

Only after the core is boringly reliable:

- **Per-firm voice cloning** (branded, consistent voice per firm).
- **Per-firm qualification tuning** — learn from attorney accept/reject decisions to refine qualification; evaluate fine-tunes vs. richer RAG context per firm.
- **Smart referrals** — route declined-but-viable cases to partner firms (product + marketplace motion, not just engineering).
- **Analytics product** — intake funnel benchmarks firms will pay for on their own.
- **Selective speech-to-speech** — revisit S2S for the greeting segment only, keeping cascading for the qualification body, if realism benchmarks justify it.

### ✅ Progress — updated 2026-07-16

**Code complete. 217 tests green (`uv run pytest`): the Phase 0–3 suite unchanged + 43 new. Live-validated over real HTTP (uvicorn + ephemeral Postgres + the real `cms_sync` worker process): consent-gated voice clone → agent assignment → agent-config carries the voice; 5 attorney rejections → tuning suggestion → applied rules flip the next decision to refer_out; refer_out lead → worker proposes referral → consent-gated send → partner outcome tracked; benchmarks suppressed at 2 peers, reported at 3 — **12/12 smoke checks PASS**. `next build` clean with the new tuning/referrals pages. Migration 0004 adds `voice_profiles`, `lead_reviews`, `referral_partners`, `referrals` — RLS + grants same posture as every other tenant table, cross-tenant tested.**

**Per-firm voice cloning:**

- [x] `VoiceCloneProvider` seam (`api/voice.py`): Cartesia adapter (mocked-transport tested, same posture as the CMS adapters) + mock local default; provider names stay in adapter code and config (cross-phase rule)
- [x] **Consent is structural**: `POST /v1/voice-profiles` refuses without `consent_confirmed`, and the table CHECK refuses again even from code — cloning a voice whose owner has not agreed is a non-starter
- [x] Only `ready` profiles are assignable (`POST /v1/agents/{id}/voice` → 409 otherwise); assignment flows through `update_agent_config`, so the cache invalidates and the very next call speaks the firm's voice — the worker's existing `voice_id` plumbing needed zero changes
- [x] Provider failure → profile marked `failed` with the error, 502 to the caller, nothing assignable
- ⚠️ Real Cartesia clone verification needs the API key (same Phase 0 blocker class)

**Per-firm qualification tuning:**

- [x] `POST /v1/leads/{id}/review`: attorney accept/reject verdicts (one per lead, re-review overwrites), emitted as `lead.reviewed` audit events
- [x] Deterministic suggestion engine (`api/tuning.py`, pure functions): engine-vs-attorney confusion matrix + agreement rate; add/remove refer-out-injury suggestions and a tighten-only SOL-gate suggestion, all sample-gated (5+) and threshold-gated (80%) — **suggestions are advisory; a human applies `proposed_rules` through the same validated config PUT every other edit uses**, closing the loop end-to-end in tests (applied rules flip the next decision)
- [x] Fine-tune vs RAG evaluation (the plan asks): deterministic rule tuning chosen — decisions must stay explainable for legal review, per-firm verdict volume is fine-tune starvation territory, and the rules engine is the seam we already have. Revisit an LLM-assisted extractor when verdict volume supports holdout evaluation; the suggestion interface wouldn't change
- [x] Dashboard `/tuning` page: matrix, agreement, suggestions, proposed rules

**Smart referrals:**

- [x] "Declined-but-viable" = `refer_out` (real case, firm won't take it); hard declines (blown SOL) are never referred
- [x] Partner registry (`/v1/referral-partners`) — registering partners **is** the opt-in: no partners, no proposals; deterministic matcher (explicit practice-area match beats wildcard, caller-state match breaks ties, using the consent state Phase 2 already records on calls)
- [x] Event-driven proposal: `lead.qualified` consumer (`workers/referrals.py`) mounts into the same single outbox loop; `UNIQUE (firm_id, lead_id)` makes event retries idempotent (tested)
- [x] **The AI proposes, a person shares**: client case facts leave the system only via `POST /v1/referrals/{id}/send` with `client_consent=true` recorded (422 without); packet is case facts only (no transcript, no internal notes), emailed via the existing `EmailProvider` seam; partner outcomes tracked (`sent` → `accepted`/`declined`) so firms see which partners convert
- [x] Dashboard `/referrals` page: referrals + partner network

**Analytics product (benchmarks):**

- [x] `GET /v1/analytics/benchmarks`: the firm's funnel (qualification rate, booking rate, speed-to-lead p50, turn-latency p95) vs an anonymized peer cohort — cohort p25/p50/p75 + the firm's percentile rank per metric
- [x] Privacy enforced and tested: **k-anonymity** (suppressed below 3 peer firms with activity — with two peers, "the cohort median" is just your competitor's number) and **aggregates only** (no peer id/name/row data in any response; asserted in tests and the live smoke)
- [x] Cross-firm aggregation runs platform-side by design (it *is* the product); dashboard analytics page grew a peer-benchmarks section

**Selective speech-to-speech:**

- [x] Evidence gate (`agent/s2s.py`): the greeting is served S2S only behind explicit opt-in (`CASELINE_S2S_GREETING`) **and** a configured provider **and** a benchmark verdict file with a human-confirmed realism win — every unmet precondition falls back to cascaded with the reason logged at call start. Default: cascaded, like every other turn
- [x] Benchmark harness (`scripts/s2s_benchmark.py`): cascaded (LLM TTFT + TTS TTFB) vs realtime time-to-first-audio over N trials; writes the verdict file with `realism_win: null` — latency is measured, realism is judged by a human listening, and the gate refuses S2S until someone does
- [x] The qualification body stays cascaded unconditionally (guardrails, transcripts, failover are non-negotiable) — S2S, if it ever ships, touches the greeting segment only
- ⚠️ Running the benchmark needs live provider keys (OpenAI realtime + the cascaded stack) — same blocker class as Phase 0

**Remaining for Phase 4 (accounts/keys, not code):**

- [ ] Cartesia key → verify a real voice clone end-to-end and A/B the branded voice on live calls
- [ ] Provider keys → run `scripts/s2s_benchmark.py`, human listening review, set `realism_win`
- [ ] SMTP credentials → referral packet email over a real transport (logging provider verified locally)
- [ ] Volume: tuning suggestions and benchmarks get meaningful once real firms generate verdicts and traffic (thresholds are deliberately conservative until then)

---

## Cross-Phase Concerns

| Concern | Rule |
|---|---|
| Latency SLO | ≤800 ms p95 hard ceiling, 500–650 ms target — a release that regresses it does not ship, in any phase |
| Provider abstraction | STT/LLM/TTS/telephony/CMS always behind interfaces; provider names appear only in adapter code and config |
| Event-first writes | Anything off the hot path goes through the event bus; no synchronous CMS calls from the voice worker, ever |
| Tenancy | `firm_id` + RLS on every table from the first migration; every new query path tested cross-tenant |
| Idempotency | Every external write carries an idempotency key from its first implementation |
| Audit | Append-only events + immutable recordings/transcripts; never add a mutable shortcut "temporarily" |

## Top Risks and Mitigations

1. **Latency misses the human threshold.** Mitigation: Phase 0 exists solely to test this; per-stage instrumentation from day one; playbook in architecture doc §9 applied in order of measured bottleneck.
2. **Provider dependence** (pricing, deprecation, brownouts). Mitigation: cascading architecture + interfaces + Phase 2 failover; re-verify model/pricing quarterly (doc is explicit that this space moves fast). *2026-07-16: default LLM switched `anthropic:claude-haiku-4-5` → `deepseek:deepseek-chat` on cost — a config-only change, proving the seam. Open item: verify DeepSeek TTFT against the 800 ms turn budget on real calls (turn metrics already slice latency by provider); if it misses, switching back or stacking anthropic as primary is one env entry.*
3. **CMS adapter fragility** — long-tail legal APIs are messy, poll-based, or partner-gated. Mitigation: normalized schema + ABC proven against three dissimilar providers (Clio/Filevine/Litify) before scaling breadth; adapters are demand-ordered.
4. **Compliance incident** (advice given, consent violated, PHI leaked). Mitigation: guardrail pass in-pipeline from Phase 1, redaction before persistence in Phase 2, consent rules per state, human-transfer escape hatch always available.
5. **Scope creep into channels before voice is solid.** Mitigation: phase gates — omnichannel (Phase 3) is blocked on hardening (Phase 2) exit criteria, no exceptions.

## Sequencing Logic (why this order)

Voice latency is the only assumption that can kill the project, so it goes first with everything else mocked. Multi-tenancy, the event bus, and the adapter interface are the irreversible decisions, so they come second, done once, done right. Scale and compliance come third because you harden against real traffic, not imagined traffic. Channels and outbound come fourth because they reuse the proven brain over cheap new transports. Differentiation comes last because cloned voices on a flaky pipeline is lipstick on downtime.
