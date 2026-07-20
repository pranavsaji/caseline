# Caseline — Technical Architecture & Engineering Guide

*Caseline is an **AI intake employee** for law firms — hired, not licensed. It answers calls in a
natural voice, qualifies leads against the firm's rules, books consults, and syncs structured
records into the firm's case-management system — and runs the same brain over SMS/email, chases
webform leads within seconds (TCPA-compliant), and tracks signed clients' treatment. Per-turn
latency instrumentation and tenant isolation are built in from the first migration. This document
is how that employee is built; [`BUSINESS.md`](BUSINESS.md) is the case for hiring it.*

This document is the engineering reference: what the system is, the exact stack, how each part
works and **why it was chosen**, the design rules, and how to run it. For a plain-language
"what it is" overview see [`OVERVIEW.md`](OVERVIEW.md); for the business/value
narrative see [`BUSINESS.md`](BUSINESS.md); for the phased build history and progress see
[`plan.md`](plan.md); for the original design blueprint see
[`caseline-voice-intake-architecture.md`](caseline-voice-intake-architecture.md).

---

## 1. What Caseline actually is

An AI intake employee is really **four systems wearing one trench coat**, and Caseline builds
all four:

1. **A real-time voice agent** — answers/places phone calls, holds a natural spoken conversation
   under an 800 ms-per-turn ceiling, handles barge-in, transfers to a human.
2. **An omnichannel messaging agent** — the same orchestration brain over SMS and email threads,
   webform follow-ups, and outbound lead outreach (non-realtime, state-machine driven).
3. **An orchestration & knowledge layer** — per-firm rules, qualification logic, scripts,
   guardrails, scheduling, and a typed tool layer the LLM can call.
4. **An integration & data layer** — bi-directional, idempotent sync with the firm's CMS/CRM,
   a durable append-only record of every interaction, and structured extraction of case facts.

The voice agent is the center of gravity — realism, latency, and reliability at telephony scale
are the hard part. Everything else is known engineering built to protect that hot path.

**Current status:** Phases 0–4 are code-complete and verified under a **257-test** suite
(31 test files). The system has been run live end-to-end on real provider APIs (Deepgram STT,
Cartesia TTS, and a live conversational LLM), deployed to the cloud (backend + agent on Railway
US-West, dashboard on Vercel), and load-tested at 50 concurrent calls with zero duplicate writes.
Since the first cut it has also grown a **login-gated operator dashboard** (dashboard-user
accounts, PBKDF2 + signed session cookie), a **per-firm LLM model picker** (a 13-provider catalog
selectable in the Config Studio, applied to the next call with no worker restart), **Plivo** as a
first-class voice+SMS provider alongside Twilio, and an explicit **10DLC send-gate** for outbound
SMS. The public marketing experience now lives at `/` and the dashboard proper at `/dashboard`.
The remaining open items across every phase are external-account provisioning (a purchased
Twilio/Plivo number → SIP trunk, a real Clio sandbox, a Cartesia clone key, an approved A2P 10DLC
campaign), not code.

---

## 2. Exact stack — what, and why

| Layer | Choice | Why this choice |
|---|---|---|
| **Transport / telephony** | LiveKit (Cloud SIP inbound trunk fed by a **Plivo** or Twilio/Telnyx number) | One media plane serves **both** WebRTC (web widget) and SIP (phone), so the same agent worker handles both. Apache-2.0, self-hostable on GKE later, ships SIP trunking, PSTN bridging, noise cancellation, per-turn latency metrics, and recording out of the box. Plivo (voice + SMS) is the currently-provisioned carrier; the inbound trunk originates to the LiveKit Cloud SIP URI and a Zentrunk outbound trunk carries the lead-chaser's dial-out. |
| **Agent framework** | LiveKit Agents (Python), **cascading** STT→LLM→TTS pipeline | Transport + agents from one vendor; strongest integrated turn-taking. Cascading (not speech-to-speech) is a deliberate decision — see §4. |
| **STT** | Deepgram **Nova-3** | ~150 ms time-to-first-token, streaming, strong on telephony audio, supports keyword/entity boosting (legal terms, firm names). |
| **LLM (voice hot path)** | **Per-firm selectable** from a 13-provider catalog. Default **Anthropic `claude-haiku-4-5`** (primary) + DeepSeek `deepseek-v4-flash` (failover) | The voice LLM is no longer a fixed env value — each firm picks `provider:model` in the Config Studio (`agents.llm_config`), applied to the next call via the same short-TTL config cache. Claude Haiku 4.5 is the default: the most natural fast-tier conversationalist and a **reliable native tool-caller**. Groq's `llama-3.3-70b` (the earlier default, measured 376 ms median TTFT) was dropped because it **leaked tool calls as literal text** (`<function=…>`) and often failed to actually run them. Catalog spans Anthropic, OpenAI, Google Gemini, DeepSeek, Groq, xAI, Mistral, Together, Fireworks, OpenRouter, Perplexity, Cerebras, and local Ollama — each behind an env-key check that the UI surfaces as "not configured". |
| **TTS** | Cartesia **Sonic-3.5** | 40–95 ms first chunk, streaming, supports per-firm cloned voices. A guarded stream adapter buffers text into sentences and calls Cartesia's reliable bytes path (the token-by-token websocket returns zero audio frames under the AgentSession), skips punctuation-only segments, and falls back to a stable default voice for any non-UUID (mock/half-provisioned) voice id. |
| **Turn-taking** | Silero VAD (pre-warmed) + a multilingual semantic end-of-utterance model | Semantic endpointing beats raw silence timers — silence-only either cuts callers off or leaves dead air. `min_endpointing_delay ≈ 0.4 s`. |
| **Backend** | **FastAPI** (Python ≥3.12), app-factory pattern | Confirmed target stack; async-native, typed with Pydantic v2. |
| **System of record** | **Postgres 16** with **row-level security** multi-tenancy + append-only `events` outbox | RLS enforced from the first migration is the tenant-isolation guarantee; the outbox decouples the hot path from CMS/analytics. |
| **Session state** | **Redis** (in-memory fallback for local dev) | A call in flight (and the per-firm agent-config cache) lives here, never on the Postgres hot path. |
| **CMS sync** | Async worker behind a `CaseManagementProvider` interface — Clio, Filevine, Litify, + mock | Swapping CMS is config, not a rewrite; writes are idempotent and event-driven. |
| **Dashboard** | **Next.js 15** (App Router) + **React 19** (TypeScript), **login-gated** | Firm-facing console + config studio + cinematic landing. Every route except the marketing landing and auth screens sits behind a signed-session-cookie middleware gate. |
| **Dashboard auth** | PBKDF2-HMAC-SHA256 (200k iters, stdlib) password hashes in `dashboard_users`; signed HTTP-only session cookie minted by the Next server | Operator sign-in is **login-only — no self-serve signup** (accounts are provisioned by `scripts/create_dashboard_user.py`). Raw passwords transit only browser→Next→backend; the browser only ever holds the session cookie. |
| **Marketing landing** | Vanilla **Three.js 0.171** (WebGL), GSAP, Lenis, Framer Motion | Cinematic experience now served at **`/`** (with `/experience` forwarding to it), rendered imperatively (React-three-fiber does not render reliably here). It renders no firm data, so it is the one unauthenticated page. |
| **Compliance** | PII redaction pipeline, per-state recording consent, 2-layer guardrails (regex + inline classifier), 10DLC SMS send-gate | Legal intake captures PHI-adjacent data; redaction is at write-time, guardrails sit in-pipeline before TTS. Outbound SMS is gated by `CASELINE_SMS_ENABLED` (read by both API and agent) because a US long code can't legally send until its A2P 10DLC campaign is approved — invisible from config, so it's an explicit switch. |
| **Infra (written, not applied)** | Terraform + Helm for GKE / Cloud SQL / Memorystore / Pub-Sub / GCS / KMS (`deploy/`) | Production blueprint; cloud apply is blocked on a GCP account only. |
| **Live cloud (running)** | Railway (backend + agent, US-West), Vercel (dashboard) | Proven deployment; region-pinned to shave transport RTT (~80–145 ms). |

**Python deps** (`pyproject.toml`): `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic`,
`python-dotenv`, `livekit-agents[deepgram,anthropic,cartesia,silero,turn-detector,openai]`,
`psycopg[binary]` + `psycopg-pool`, `redis`, `cryptography`. Dev: `pytest`, `pytest-asyncio`.
Managed with **uv**. (Provider plugins load lazily — only the LLM/STT/TTS vendors actually
configured are imported; OpenAI-compatible providers reuse the `openai` plugin with a `base_url`.)

**Frontend deps** (`frontend/package.json`): `next@15`, `react@19`, `three@0.171`, `gsap`,
`lenis`, `framer-motion`, `livekit-client`, `lucide-react`, TypeScript 5.

---

## 3. Architecture at a glance

```
Callers/Leads          Edge (GCP+K8s)        Voice Workers (autoscaled)      Core Platform (FastAPI)
──────────────         ───────────────       ─────────────────────────      ───────────────────────
Phone / PSTN  ─┐       SIP trunk ─┐          Agent worker ── STT (Deepgram)  API gateway (auth/tenancy)
Web / WebRTC  ─┼──►    LiveKit SFU ├──► ◄──── │            ── LLM (Groq)      Orchestration (rules/config)
Inbound SMS   ─┤       (WebRTC+SIP)│          │            ── TTS (Cartesia)  Typed tool layer
Webforms/Ads  ─┤                   │          │            ── Turn detect     Messaging service (SMS/email)
Email         ─┘                              └── Guardrails (LLM→TTS pass)   Async workers (outbox)
                                                                              │
   Data & State                    CMS Adapters                              ▼
   ────────────                    ────────────                       Events outbox (Postgres)
   Postgres (RLS, system of record)  Clio                             → cms_sync worker → CMS
   Redis (live session state)        Filevine                         → referrals worker
   Events outbox (append-only)       Litify (Salesforce)              → omnichannel handlers
   GCS (recordings/transcripts)      mock                                     │
                                                                              ▼
   Frontend (TypeScript) ── Firm dashboard + Config studio + Cinematic landing
```

The **golden rule**: the caller-audio path (STT→LLM→TTS) does nothing that isn't on a latency
budget. Persistence, CMS writes, analytics, and follow-ups all happen **async off the events
outbox**, never inline from the voice worker.

---

## 4. The core hard problem: real-time voice

### 4.1 Latency is the whole game

Human conversation has a median inter-speaker gap of ~200 ms. Below ~500 ms a voice agent feels
natural; past 800 ms it feels like a walkie-talkie; past 1.5 s callers talk over it or hang up.

The per-turn budget (end of caller speech → first audio back):

| Stage | Target | Notes |
|---|---|---|
| Network / transport (WebRTC or SIP) | 20–60 ms | Wideband Opus over WebRTC; PSTN adds jitter |
| Streaming STT (first useful partial) | 60–120 ms | Deepgram Nova-3 class |
| LLM first token | 100–250 ms | Fast-tier model + prompt caching (Claude Haiku 4.5 default; Groq's `llama-3.3` measured 376 ms median before it was dropped for tool-call leakage) |
| TTS first chunk | 40–100 ms | Cartesia Sonic-class streaming |
| Orchestration overhead | 20–80 ms | Turn detection, guardrails, buffering |

A naive pipeline lands ~1.2–1.4 s p95; a tuned one ~500–650 ms p95. **≤800 ms p95 is a hard
ceiling** in Caseline — every call's per-stage breakdown is stitched and rolled up
(`agent/latency.py`, `GET /v1/metrics/calls/{id}`, dashboard). The single biggest mistake —
batch transcription — is banned; every layer streams.

**Per-turn stages captured** (migration `0005` surfaced the two that used to be invisible):

| Field | Counts toward `total_ms`? | Source |
|---|---|---|
| `eou_delay_ms` — end-of-utterance delay | Yes | `EOUMetrics.end_of_utterance_delay` |
| ↳ `stt_ms` — STT-finalization slice of the EOU delay | No (a **breakdown of** EOU, not additive) | `EOUMetrics.transcription_delay` |
| `llm_ttft_ms` — LLM time-to-first-token | Yes | `LLMMetrics.ttft` |
| `guardrail_ms` — regex-screen CPU between LLM and TTS | No (an overhead diagnostic, best-effort) | timed in `IntakeAgent.llm_node`, keyed by `current_speech.id` |
| `tts_ttfb_ms` — TTS time-to-first-byte | Yes | `TTSMetrics.ttfb` |
| **`total_ms`** (budget 800 ms p95) | = `eou + llm_ttft + tts_ttfb` | — |

### 4.2 Cascading vs speech-to-speech — a decision, not a default

**Cascading (STT→LLM→TTS)** gives discrete swappable components, a full transcript for audit,
clean insertion points for guardrails and PII redaction, provider independence, and cheaper
per-minute cost. **Speech-to-speech** (single realtime model) gives ~300 ms latency and lovely
prosody but loses the transcript, the guardrail insertion points, and provider independence, and
degrades over 8 kHz PSTN.

**Caseline chooses cascading.** Legal intake captures legally meaningful facts, must produce an
auditable transcript, and cannot hallucinate into an unauthorized-practice-of-law situation. The
rule of thumb: S2S for consumer assistants where personality beats precision; cascading for
anything that touches a database, could be quoted back in a dispute, or carries compliance weight.

The architecture stays swappable so S2S can be adopted **per-segment** later. Phase 4 built an
**evidence-gated S2S greeting path** (`agent/s2s.py`): the greeting is served S2S only behind
explicit opt-in **and** a configured provider **and** a benchmark verdict file with a
human-confirmed realism win — every unmet precondition falls back to cascaded with the reason
logged. The qualification body stays cascaded unconditionally.

### 4.3 The realism levers (the tuning that earns the latency budget)

Streaming turn detection (semantic EOU, not silence) · preemptive generation (fire the LLM on
STT partials, cancel/re-fire on more speech) · near-instant barge-in (stop TTS, flush buffer,
cancel in-flight LLM the moment caller audio is detected) · backchannels/fillers to mask
tool-call dead air · per-firm cloned voice · wideband audio where the transport allows ·
prompt/prefix caching on the system prompt + firm script · pre-warmed Silero VAD · regional
pinning of STT/LLM/TTS to the SFU region.

---

## 5. Repository layout & what each piece does

```
agent/                      # LiveKit Agents voice worker (the hot path)
  agent.py                  #   pipeline wiring, typed tools, guardrail LLM→TTS pass, immediate
                            #     TTS greeting, end_call tool, current-date anchoring, LLM warmup
  providers.py              #   STT/LLM/TTS failover stacks + the 13-provider LLM catalog/registry,
                            #     the guarded Cartesia TTS, provider labels for metrics
  backend_client.py         #   HTTP client (Phase 0 + /v1 modes; livekit-free, unit-testable)
  latency.py                #   per-turn latency stitching + p50/p95 incl. stt_ms/guardrail_ms
  s2s.py                    #   evidence-gated speech-to-speech greeting decision

api/                        # FastAPI core platform
  main.py                   #   app factory: Phase 0 routes + Phase 1 /v1 platform mount
  routes_v1.py              #   the multi-tenant /v1 API (see §6)
  qualification.py          #   qualification rules engine (pure functions)
  voice.py                  #   VoiceCloneProvider seam (Cartesia adapter + mock)
  tuning.py                 #   qualification-tuning suggestion engine (pure functions)
  telephony.py              #   outbound dialer seam (LiveKit SIP / logging)
  benchmarks.py             #   benchmark analytics (k-anonymous peer cohort)
  storage.py, schemas.py    #   Phase 0 prototype (SQLite) — kept for keyless local runs
  tools/                    #   typed tool layer (deterministic; the LLM only selects/parameterizes)
  orchestration/            #   per-firm config + threads brain + 2-layer guardrails + classifier
  compliance/               #   PII redaction, per-state consent, TCPA outbound policy
  messaging/                #   SMS + email provider seams (Plivo / Twilio / SMTP / logging;
                            #     auto-selected by which creds are set) + the 10DLC send-gate
  platform/                 #   db+RLS, migrations (0001–0007), events outbox, auth (service tokens),
                            #     dashboard_auth (operator login, PBKDF2), secrets, alerts, session_state

integrations/               # CaseManagementProvider ABC + normalized schema
  base.py, models.py        #   the interface + normalized Lead/Contact/Matter/Task/Note
  clio.py, filevine.py, litify.py, mock.py

workers/
  cms_sync.py               # the single event-consumer loop: idempotent CMS writes, retry + DLQ,
                            #   alert loop, omnichannel handlers + followups
  omnichannel.py            # lead chaser, thread advancer, scheduled followups
  referrals.py              # lead.qualified consumer → idempotent referral proposals

frontend/                   # Next.js dashboard + config studio + cinematic landing
deploy/                     # Terraform (GCP) + Helm chart — written, not applied
compliance/                 # SOC 2 groundwork, vendor inventory, security-review checklist
scripts/onboard_firm.py     # CLI onboarding (firm + agent + service token)
scripts/create_dashboard_user.py  # provisions a dashboard operator account (login-only; no signup)
scripts/seed_demo_data.py   # idempotent demo rows for Threads/Referrals/Tuning + booked consults
scripts/load_test.py        # 50-concurrent-call load test + end-state duplicate audit
scripts/s2s_benchmark.py    # cascaded vs realtime time-to-first-audio harness
scripts/plivo_trunk_setup.sh / twilio_trunk_setup.sh  # SIP inbound/outbound trunk provisioning
scripts/dev_db.sh           # boots a dedicated local Postgres cluster on :5455
tests/                      # 33 pytest files (~253 tests) incl. ephemeral-Postgres RLS,
                            #   dashboard-auth, LLM-catalog, and managed-Postgres-auth coverage
```

---

## 6. The `/v1` API surface

All `/v1` routes are firm-scoped (Bearer service token) except `/v1/admin/*` (admin token).
Tools are the actions the LLM can invoke; everything else is dashboard/webhook/ops surface.

**Admin & config**
`POST /v1/admin/firms` · `POST /v1/admin/firms/{id}/tokens` · `GET /v1/agent-config` ·
`PUT /v1/agents/{id}/config` (script/routing/**`llm_config`**/voice) · `GET /v1/agents` ·
`POST /v1/agents/{id}/preview` (zero-side-effect config test-drive) ·
`GET /v1/llm-providers` (13-provider catalog with per-provider `configured` / `not configured` flag)

**Typed tools (LLM-callable, deterministic)**
`POST /v1/tools/lookup_caller` · `qualify_lead` · `schedule_consult` · `transfer_to_human` ·
`send_sms` · `take_message`

**Calls & metrics**
`POST /v1/calls/complete` · `POST /v1/calls/{id}/transcript` · `POST /v1/calls/dial` (outbound) ·
`POST /v1/calls/web-session` · `POST /v1/calls/{id}/hangup` (operator teardown — deletes the
LiveKit room; idempotent) · `POST /v1/calls/{id}/outcome` (manual disposition override) ·
`POST /v1/metrics/turn` · `GET /v1/metrics/calls/{id}` · `GET /v1/calls` (each row carries a
derived `booked` flag) · `GET /v1/calls/{id}`

**Data reads** `GET /v1/leads` · `/consults` · `/messages` · `/events`

> **Booking is a distinct signal from qualification.** A booked consult lives in `consults` and
> never touched `calls.outcome`, so qualified-and-booked calls used to show only "qualified".
> `GET /calls` now derives `booked` via an `EXISTS` on the linked consult, `GET /calls/{id}`
> returns `booked` + `consult_slot_at`, and `/analytics/outcomes` reports both a lead-level
> `booking_rate` (consults ÷ qualified leads) and a call-level `call_booking_rate` (booked calls
> ÷ total calls) so booked calls no longer hide inside the "qualified" bucket.

**Omnichannel (Phase 3)**
`POST /v1/hooks/leads` (webform → chaser) · `POST /v1/hooks/sms` (inbound reply → thread) ·
`GET /v1/threads` · `GET /v1/threads/{id}` · `POST /v1/tracker/enroll` (treatment tracker) ·
`GET /v1/analytics/chaser` (speed-to-lead)

**Analytics** `GET /v1/analytics/latency` · `/analytics/outcomes` · `/analytics/benchmarks`
(k-anonymous peer cohort)

**Phase 4 differentiation**
`POST /v1/voice-profiles` (consent-gated clone) · `GET /v1/voice-profiles` ·
`POST /v1/agents/{id}/voice` (assign) · `POST /v1/leads/{id}/review` (attorney verdict) ·
`GET /v1/tuning/suggestions` · `POST /v1/referral-partners` · `GET /v1/referral-partners` ·
`GET /v1/referrals` · `POST /v1/referrals/{id}/send` (consent-gated) · `POST /v1/referrals/{id}/status`

**Admin ops** `GET /v1/admin/ops/overview` · `/ops/alerts` · `/ops/onboarding` ·
`GET /v1/admin/events/dead` (DLQ) · `POST /v1/admin/events/{id}/replay`

**Phase 0 legacy (keyless local path)** `POST /qualify` · `/schedule` · `/mock-cms` (+ GET) ·
`GET /consults` · `POST /metrics/turn` · `GET /metrics/calls/{id}` · `GET /health`

---

## 7. Data model & multi-tenancy

21 tables across 7 migrations. Every **tenant** row carries `firm_id`; **Postgres row-level
security** is set from migration `0001` and verified by tests that run cross-tenant queries as
the app role.

- **Core (0001):** `firms`, `firm_tokens`, `agents`, `contacts`, `calls`, `transcripts`,
  `leads`, `matters`, `tasks`, `messages`, `consults`, `turn_metrics`, `events`,
  `idempotency_keys`
- **Hardening (0002):** columns for redaction/consent
- **Omnichannel (0003):** `threads`, `followups`
- **Differentiation (0004):** `voice_profiles`, `lead_reviews`, `referral_partners`,
  `referrals` — same RLS + grants posture as every other tenant table, cross-tenant tested
- **Turn latency (0005):** `turn_metrics.stt_ms`, `turn_metrics.guardrail_ms` (nullable columns)
- **LLM selection (0006):** `agents.llm_config jsonb` — the per-firm `provider:model` spec; empty
  `{}` means "use the worker default", so existing agents are unaffected
- **Dashboard users (0007):** `dashboard_users` (`email`, PBKDF2 `password_hash`) — deliberately
  **global, not RLS-scoped**: it's operator access-control infrastructure like `schema_migrations`
  and `firm_tokens`, not per-tenant business data, so it lives on the platform role

`events` is the append-only audit log **and** the integration outbox — one table, two jobs.
`idempotency_keys` is what makes every external write safe to retry.

---

## 8. Design decisions that hold in every phase

1. **≤800 ms p95 turn latency is a hard ceiling.** Per-stage breakdown stored and rolled up per
   call. *Why:* below this, the agent stops feeling human and callers hang up — it's the
   existential risk the whole architecture exists to retire.
2. **The hot path is sacred.** CMS writes and analytics run async off the events outbox, never
   inline from the voice worker. *Why:* a slow CMS API must never add latency to a live call.
3. **Tenancy is enforced by Postgres RLS**, set from the first migration, verified by
   cross-tenant tests as the app role. *Why:* retrofitting isolation onto live legal data is how
   you lose customers; the DB is the last line, not the app code.
4. **Every external write carries an idempotency key.** *Why:* retries can never duplicate a
   matter or double-book a consult — proven under the 50-call load test with forced duplicates.
5. **Providers live behind interfaces** (STT/LLM/TTS/SMS/CMS/voice-clone). *Why:* providers get
   swapped mid-life on price/latency/deprecation — the voice LLM has already moved
   Anthropic → DeepSeek → Groq → **back to Anthropic Claude Haiku 4.5** as tool-calling reliability
   and cost/latency shifted, each a config-only change. That seam is now **exposed to the firm**:
   the LLM is selectable per-agent (`agents.llm_config`) from a 13-provider catalog in the Config
   Studio, not just an operator env value.
6. **Guardrails in-pipeline, two layers.** A regex screen plus an inline lexical classifier
   (catches paraphrases) sit between LLM and TTS and block legal advice, fee quotes, and outcome
   guarantees — **p95 < 5 ms, perf-gated in tests**; the classifier is behind a Protocol seam an
   ML model can replace. *Why:* an unauthorized-practice-of-law slip is a legal liability, and it
   has to be blocked inside the turn budget.
7. **PII stays inside.** Transcripts are redacted at write time and served redacted by default
   (`transcripts:raw` scope for the exception); every process logs through a redaction filter.
   *Why:* PI intake is HIPAA-adjacent — treat health spans as if HIPAA applies.
8. **Cascading pipeline, by decision** (see §4.2). S2S only per-segment, only behind a
   human-confirmed evidence gate.
9. **Consent is structural, not advisory.** No SMS consent → no automated outbound, ever. Voice
   cloning refuses without `consent_confirmed` at both the API and a DB CHECK. Referral packets
   leave the system only via an explicit human `send` with `client_consent=true`. STOP/HELP are
   honored inline; STOP is permanent.

---

## 9. How the moving parts work

**Provider failover (`agent/providers.py`).** STT/LLM/TTS each sit behind a `FallbackAdapter`
built from a comma-separated `provider:model` spec (primary first). A health-check-driven stack
fails over mid-call to a secondary provider on slowdown/error — the argument for cascading over
S2S. Provider labels flow into latency metrics so you can slice p95 by provider. An LLM spec whose
API key is absent is **skipped, not fatal**, so a not-yet-configured primary degrades to the next
provider instead of crashing the worker on every call.

**LLM model picker (`agent/providers.py` `_LLM_REGISTRY` + `llm_catalog()`).** One registry row per
provider — `(env key, default model, connector)` — is the single source of truth for the 13
supported vendors (Anthropic, OpenAI, Google Gemini, DeepSeek, Groq, xAI, Mistral, Together,
Fireworks, OpenRouter, Perplexity, Cerebras, local Ollama). The *connector* tells `_build_llm` how
to construct the client: the native Anthropic/OpenAI plugin, an `openai`-plugin `with_*` helper, or
an OpenAI-compatible `base_url`. Adding a provider is a row here plus its `.env` key — no other
code. `GET /v1/llm-providers` serves this as a catalog (label, what it `requires`, whether that
requirement is `configured` in this process's env, default + suggested models) so the Config Studio
can show unconfigured providers as "not configured" and disable them (Ollama counts as configured
only when explicitly pointed at a reachable server). A firm's pick is stored in `agents.llm_config`
and reaches the worker through the normal config load; the worker builds the stack from that spec
and falls back to the env default (`anthropic:claude-haiku-4-5,deepseek:deepseek-v4-flash`) for an
empty `{}`. Claude gets `caching="ephemeral"` on the stable system-prompt + tool-schema prefix — the
single biggest per-turn LLM-latency lever.

**Agent conversational behavior (`agent/agent.py`).** The greeting is spoken **immediately** via
`session.say()` with a fixed opening line (firm name + agent name + AI disclosure + optional
recording disclosure) — not `generate_reply()`, which ran a full system-prompt LLM call and left
~20 s of silence callers talked over; first-audio dropped to ~3 s. A warmup task absorbs the
primary LLM's cold-start cost while that greeting plays. The system prompt is anchored to the real
**current date/time in the firm's timezone** so the model resolves "today"/"a few hours ago" to a
correct ISO date (a same-day accident was being stamped a year off, tripping the SOL gate). An
`end_call` tool lets the agent hang up after goodbye: it drains playout, speaks the farewell
non-interruptibly, then deletes the LiveKit room (firing transcript flush + CMS drain). A streaming
`FunctionCallStripper` in `llm_node` deletes any tool call a model emits as literal text
(`<function=…>`) before it can be spoken — defense-in-depth on top of choosing a reliable native
tool-caller.

**Qualification engine (`api/qualification.py`).** Pure functions: a statute-of-limitations gate
(730 days), refer-out injury rules, decisions with human-readable reasons. Unparseable/future
dates never auto-decline — they attach a human-verification reason instead.

**Guardrails (`api/orchestration/guardrails.py` + classifier).** Layer 1 regex screen, Layer 2
inline lexical classifier that catches paraphrases, both between LLM output and TTS. Perf-gated
< 5 ms p95.

**Events outbox + `workers/cms_sync.py`.** The single event-consumer loop: claims events
(concurrent-worker-safe), writes to the CMS idempotently, retries with backoff, dead-letters
poison payloads, runs the alert-evaluation loop, and dispatches omnichannel handlers +
scheduled followups. DLQ is inspectable and replayable via admin ops.

**CMS adapters (`integrations/`).** A `CaseManagementProvider` ABC + a normalized schema
(Lead/Contact/Matter/Task/Note). Clio/Filevine have REST; Litify is Salesforce-native (managed
package objects); `mock.py` logs payloads for keyless local runs. The orchestration layer never
knows which CMS a firm runs.

**Omnichannel brain (`api/orchestration/threads.py` + `workers/omnichannel.py`).** The intake
state machine is a pure function reused across transports. A webform lead emits `lead.created`;
the chaser texts back within ~1 s (TCPA-gated); caller replies arrive as inbound SMS webhooks and
advance the thread; the treatment tracker is a scheduled follow-up state machine for signed
clients. The config studio's preview runs the exact same brain with **zero side effects**.

**Phase 4 differentiation.** Voice cloning (`api/voice.py`) is consent-gated at API + DB CHECK,
only `ready` profiles are assignable, assignment invalidates the config cache so the next call
speaks the firm's voice. (Fix, b2c8767: the provider now **auto-selects Cartesia whenever
`CARTESIA_API_KEY` is set** — the old behavior silently fell back to the mock provider, whose
non-UUID `mock-voice-…` ids the TTS stage rejects, so a "successful" clone never actually spoke;
force the no-network mock with `CASELINE_VOICE_CLONE_PROVIDER=mock`, and re-clone any pre-existing
mock profiles.) Qualification tuning (`api/tuning.py`) turns attorney accept/reject
verdicts into an engine-vs-attorney confusion matrix and advisory rule suggestions (sample-gated
5+, threshold-gated 80%) — **a human applies them through the same validated config PUT**. Smart
referrals route `refer_out` (viable but declined) cases to registered partner firms via an
idempotent event consumer; the AI proposes, a person shares. Benchmarks are k-anonymous
(suppressed below 3 peer firms, aggregates only).

---

## 10. Frontend

**Stack:** Next.js 15 (App Router) + React 19, TypeScript 5. Plain CSS + CSS Modules — **no
Tailwind, no CSS-in-JS**. `three@0.171` (landing WebGL), `framer-motion`, `gsap`, `lenis`
(smooth scroll), `livekit-client` (browser voice), `lucide-react` (icons). `next.config.mjs` is
empty; the project is linked to Vercel (`.vercel/project.json`, git-ignored).

**Access gate (`frontend/middleware.ts`).** Every request except the marketing landing (`/`,
`/experience`) and the auth surface (`/login`, `/signup`, `/api/auth/*`) requires a valid **signed
session cookie** (`frontend/lib/session.ts`): unauthenticated page loads redirect to `/login?next=…`,
unauthenticated `/api/*` calls get a clean `401` JSON. Login posts to `/api/auth/login`, which
calls the backend `verify_user` (PBKDF2), and on success the Next server sets the HTTP-only session
cookie — **raw passwords only ever transit browser→Next→backend**. Self-serve signup is disabled
(`/signup` 307s to `/login`); accounts come from `scripts/create_dashboard_user.py`.

**Architecture — server-first with a BFF token boundary.** List/analytics pages are React Server
Components (`dynamic = "force-dynamic"`) that fetch through `frontend/lib/api.ts`, a
**server-only** client. Two auth scopes: `api()` sends the firm Bearer token, `adminApi()` sends
the admin token; both read from env and **never reach the browser** (`cache: "no-store"`).
Interactive client components never call the backend directly — they POST to thin proxy route
handlers under `frontend/app/api/*` (auth login/logout/me, dial, hangup, call-outcome,
web-session/LiveKit token, config PUT, preview, lead review, tuning apply, referral send/status,
voice-profiles/voice-library, partner register, dead-letter replay, llm-providers), which call
`lib/api.ts` server-side so the token stays put. `adminEnabled` hides admin surfaces when no
admin token is set.

**Routing:** the public **cinematic landing now lives at `/`** (server page → client
`ExperienceRoot`; `/experience` forwards to it) and the **dashboard root moved to `/dashboard`**.
`ShellGate` strips the dashboard chrome (sidebar + aurora) for the landing and auth screens and
wraps everything else in `AppShell` (sidebar nav: Overview `/dashboard`, Calls, Threads, Analytics,
Tuning, Referrals, Studio, Ops, Config).

**Dashboard pages** (rendered inside `AppShell`): `/dashboard` intake overview (answer-speed p95,
consults booked, qualification rate, recent calls/leads with inline attorney `LeadReview`) ·
`/calls` (WebVoiceConsole browser test + CallConsole outbound/simulate; per-call operator hang-up
and `CallDisposition` outcome override) · `/calls/[id]` (transcript, per-turn latency table incl.
STT/guardrail slices, recording, "Qualified · Consult booked" signal) · `/threads` +
`/threads/[id]` (omnichannel + speed-to-lead) · `/analytics` (funnel, outcomes incl. call-booking
rate, latency by day/provider, peer benchmarks) · `/tuning` (engine-vs-attorney confusion matrix +
advisory suggestions, `ApplyTuningRules`) · `/referrals` (referrals + partner network +
`PartnerForm`) · `/studio` (config studio + zero-side-effect test-call preview + `VoiceManager` +
`ModelManager`, the per-firm LLM picker) · `/config` (raw JSON power-editor with live validation) ·
`/ops` (messages, event log, admin queue/alerts/DLQ/onboarding) · `/login` + `/signup` (auth).

**Design language:** futuristic **dark glassmorphism over a live WebGL aurora** (dark-only
"Aurora" theme). The kit evolved from the earlier neomorphic system — the token *names*
(`--nm-raised/pressed/flat/glow`) were kept but values are now translucent glass (hairline indigo
borders + backdrop blur + neon glow). Deep-space base, cyan-teal accent (`#22e0c7`) with
electric-violet companion (`#9d7bff`). Fonts: Space Grotesk (display), Inter (body), JetBrains
Mono. `AuroraBackground` is a raw WebGL2 fragment-shader aurora on the dashboard; full
`prefers-reduced-motion` handling everywhere with CSS fallbacks.

**Cinematic landing (served at `/`, with `/experience` forwarding to it):** `ShellGate` strips the
dashboard chrome so it renders full-bleed, and because it renders no firm data it is the one
unauthenticated page. The scene is **vanilla Three.js** (`components/experience/webgl/VoiceScene.ts`) —
deliberately not react-three-fiber, whose reconciler doesn't commit reliably under Next 15 /
React 19, so Three.js is driven imperatively: a noise-displaced fresnel "voice orb", two particle
layers, a scroll-driven camera spline, `UnrealBloomPass` post-processing, ACES tone mapping,
per-device-tier DPR clamping, and a CSS poster fallback when WebGL is unavailable. Six scrollytelling
sections (Hero/Intro/Features/Demo/Proof/Cta) with a Lenis smooth-scroll spine.

Deployed on Vercel (`caseline-three.vercel.app`), `CASELINE_API_URL` + firm token in env, pointed
at the Railway backend.

> **Security note:** `frontend/.env.local` currently contains a live-looking `CASELINE_FIRM_TOKEN`.
> It's a local dev file, but rotate that token and keep real tokens out of committed env files.

---

## 11. How to run it

Requires **Python ≥3.12** and [uv](https://docs.astral.sh/uv/). Postgres 16 + Node 20+ for the
platform/dashboard.

### 11.1 Install & test (no API keys or network needed)

```bash
uv sync                       # creates .venv and installs everything
cp .env.example .env          # fill in what you need (see comments)
uv run pytest -v              # 253 tests: RLS isolation, guardrails, idempotency, auth, e2e, ...
```

The suite boots its own throwaway Postgres to verify RLS cross-tenant isolation — no external
services required.

### 11.2 Run the platform (Phase 1)

```bash
# 0. Local Postgres just for Caseline (own cluster on :5455, data in .tmp/pgdata)
./scripts/dev_db.sh start     # prints the CASELINE_DATABASE_URL to put in .env

# 1. Backend (needs CASELINE_DATABASE_URL, CASELINE_SECRETS_KEY, CASELINE_ADMIN_TOKEN;
#    migrations apply on boot)
uv run uvicorn api.main:app --port 8000

# 2. Onboard a firm (prints the service token exactly once)
uv run python scripts/onboard_firm.py --name "Bluebonnet Injury Law" \
  --cms mock --transfer-number +15125550199

# 3. CMS sync worker (consumes the events outbox; idempotent writes, DLQ)
uv run python -m workers.cms_sync

# 4. Voice worker (set CASELINE_FIRM_TOKEN from step 2 for the /v1 API;
#    leave empty for the Phase 0 single-tenant path)
uv run python -m agent.agent download-files   # one-time: turn-detector + VAD models
uv run python -m agent.agent console          # local mic/speaker, no telephony
uv run python -m agent.agent dev              # connect to LiveKit, take real calls

# 5. Dashboard operator account (login-only — there is no self-serve signup)
uv run python scripts/create_dashboard_user.py you@firm.com   # prompts for a password

# 6. Dashboard (the landing is at `/`; the dashboard proper is at `/dashboard`, behind login)
cd frontend && npm install
CASELINE_API_URL=http://localhost:8000 CASELINE_FIRM_TOKEN=cl_... npm run dev
```

**Telephony (marquee demo):** buy a **Plivo** or Twilio number, point its inbound trunk at the
LiveKit Cloud SIP URI (`LIVEKIT_SIP_URI`), add a dispatch rule that routes to this agent, and (for
the lead-chaser's dial-out) create a LiveKit outbound trunk over Plivo Zentrunk. See
`deploy/plivo-trunk.md`, `deploy/sip-outbound-trunk.md`, and
`scripts/plivo_trunk_setup.sh` / `scripts/twilio_trunk_setup.sh`.

### 11.3 Try the omnichannel layer (Phase 3)

```bash
# Webform lead → the chaser texts back within ~1 s (logging SMS provider prints it)
curl -s -X POST localhost:8000/v1/hooks/leads \
  -H "Authorization: Bearer cl_..." -H "Content-Type: application/json" \
  -d '{"name":"Dana Torres","phone":"+15125550111","source":"web",
       "sms_consent":true,"consent_source":"landing form"}'

# Caller replies arrive as inbound SMS webhooks and advance the thread
curl -s -X POST localhost:8000/v1/hooks/sms \
  -H "Authorization: Bearer cl_..." -H "Content-Type: application/json" \
  -d '{"from_number":"+15125550111","body":"It was on June 1"}'

# Enroll a signed client in the treatment tracker
curl -s -X POST localhost:8000/v1/tracker/enroll \
  -H "Authorization: Bearer cl_..." -H "Content-Type: application/json" \
  -d '{"name":"Sam Client","phone":"+15125550777","cadence_days":14}'
```

Dashboard: `/threads`, `/studio` (config + zero-side-effect preview). Speed metric:
`GET /v1/analytics/chaser`. STOP/HELP honored inline; no consent → no automated outbound.

### 11.4 Load test (Phase 2)

```bash
uv run python scripts/load_test.py --base-url http://localhost:8000 \
  --admin-token $CASELINE_ADMIN_TOKEN --calls 50          # realistic pacing
# --think 0  = stress mode: every request in the same instant (burst-capacity probe)
```

Drives 50 concurrent synthetic calls through the full tool path (including a forced duplicate
booking per call), reports per-endpoint p50/p95, waits for the outbox to drain, and audits the
end state: exactly one lead + one consult per call, zero dead letters. Exit 0 only if the SLO
held and nothing duplicated. Sizing knobs: `CASELINE_DB_POOL_SIZE`,
`CASELINE_RATE_LIMIT_PER_MINUTE`, uvicorn `--workers`.

**Measured result (2026-07-16):** realistic pacing — worst-endpoint p95 **10.4 ms** vs the
800 ms budget, zero failed requests, exactly one lead + one consult per call, outbox drained,
zero dead letters, zero alerts. Stress mode (all ~600 requests at once): correctness still
perfect, latency p95 1.1 s — a documented burst-capacity finding (add API replicas), not a
realistic-load failure.

### 11.5 Cloud deployment (proven)

- **Backend + agent on Railway** (US-West), managed Postgres, migrations apply on boot; agent
  registered with LiveKit Cloud from Railway. `deploy/railway/start.sh` branches on
  `CASELINE_SERVICE` (backend vs agent) from one Docker image.
- **Dashboard on Vercel** (`caseline-three.vercel.app`) → Railway backend.
- Region pinning matters: services pinned to `us-west2` brought backend RTT to ~80–145 ms and
  the agent onto "US West B" (an accidental `asia-southeast1` default had added ~280 ms).

---

## 12. Environment variables (non-secret highlights)

```
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_SIP_URI=                          # the PROJECT-ID SIP subdomain the carrier originates to
CASELINE_STT_PROVIDERS=deepgram:nova-3
# Default voice LLM: primary,failover. Firms can override per-agent in the Config Studio.
CASELINE_LLM_PROVIDERS=anthropic:claude-haiku-4-5,deepseek:deepseek-v4-flash
CASELINE_TTS_PROVIDERS=cartesia:sonic-3.5
CARTESIA_VOICE_ID=                        # per-firm branded voice; empty = provider default
# LLM provider keys — adding a key unlocks that provider in the Config Studio picker; a
# provider whose key is missing shows as "not configured". (ANTHROPIC/OPENAI/GEMINI/DEEPSEEK/
# GROQ/XAI/MISTRAL/TOGETHER/FIREWORKS/OPENROUTER/PERPLEXITY/CEREBRAS_API_KEY; Ollama needs none.)
ANTHROPIC_API_KEY=  / OPENAI_API_KEY=  / DEEPSEEK_API_KEY=  / ...
CASELINE_DATABASE_URL=                    # Postgres; migrations apply on boot
CASELINE_REDIS_URL=                       # empty = in-memory session fallback (local dev)
CASELINE_RATE_LIMIT_PER_MINUTE=300
CASELINE_DB_POOL_SIZE=4
CASELINE_WORKER_BATCH_SIZE=20
CASELINE_ALERT_INTERVAL_SECONDS=60
# Outbound SMS carrier is auto-selected: Plivo if its pair is set, else Twilio, else logged.
PLIVO_AUTH_ID= / PLIVO_AUTH_TOKEN= / PLIVO_FROM_NUMBER=
TWILIO_ACCOUNT_SID= / TWILIO_AUTH_TOKEN= / TWILIO_FROM_NUMBER=
CASELINE_SMS_ENABLED=true                 # master send-gate; set false until A2P 10DLC clears
CASELINE_SMTP_HOST= / _PORT=587 / _FROM=intake@caseline.app
CASELINE_SIP_OUTBOUND_TRUNK_ID=           # LiveKit outbound trunk for the lead-chaser dial-out
PLIVO_SIP_TERMINATION= / PLIVO_SIP_USERNAME= / PLIVO_SIP_PASSWORD=   # Zentrunk outbound
CASELINE_S2S_GREETING=                    # opt-in flag for the evidence-gated S2S greeting
```
Secrets (provider API keys, `CASELINE_SECRETS_KEY`, `CASELINE_ADMIN_TOKEN`, firm tokens, Plivo/
Twilio creds) live in `.env` locally and the platform secret store in the cloud — never in the app
DB in plaintext (CMS credentials are encrypted with the secrets key / KMS). Dashboard-operator
passwords are stored only as PBKDF2 hashes in `dashboard_users`.

---

## 13. Testing & verification posture

**253 tests, 33 files, zero API keys or network needed.** Coverage: the qualification engine
(incl. SOL boundary + bad-date edges), every Phase 0 endpoint, latency stitching (incl.
interleaved turns), the agent→backend contract (in-process ASGI), the Phase 1 platform — **RLS
cross-tenant isolation against a real throwaway Postgres the suite boots itself**, token auth +
rate limiting, guardrails, typed tools, idempotency under fault injection, event
retry/dead-letter/replay, the Clio adapter (mocked transport), a full simulated-firm e2e run —
the Phase 2 hardening layer — PII redaction + scoped raw-transcript access, per-state consent,
the inline guardrail classifier (with a **< 5 ms p95 perf gate**), mid-call LLM failover chaos
tests, concurrent-worker claim safety, DLQ replay + alert evaluation, analytics, Filevine/Litify
adapters — the Phase 3 omnichannel layer — TCPA outbound policy (consent, quiet hours, STOP
permanence), the thread brain, and webform→chaser→SMS→booking→CMS e2e with tenancy, nudges, and
the zero-side-effect config preview — and the Phase 4 differentiation layer — consent-gated voice
cloning, attorney-verdict qualification tuning, smart referrals, k-anonymous benchmarks, and the
evidence-gated S2S decision. Newer suites add **dashboard-operator auth** (PBKDF2 hash/verify,
signup-disabled), the **LLM provider catalog** (`test_llm_catalog.py` — configured/not-configured
flags, alias resolution), and **managed-Postgres auth** wiring (`test_managed_pg_auth.py`).

Live validation (2026-07-16): real Deepgram/Cartesia/LiveKit/Twilio auth; a real hot-path round
trip (Cartesia TTS → Deepgram STT, word-perfect); a full voice turn through the production
failover stack with a real tool call; an all-phases 24/24 HTTP smoke including webform → chaser
SMS (first contact 0.5 s) → booked consult.

**Open items across all phases are external accounts, not code:** a purchased Plivo/Twilio number →
SIP trunk + ≥20-call live latency measurement, an approved A2P 10DLC campaign for real outbound SMS,
a real Clio sandbox, a Cartesia clone key, provider keys for the S2S benchmark, real SMTP for
referral email, and the GCP account to apply the Terraform/Helm.
