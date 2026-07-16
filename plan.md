# Caseline — Phased Build Plan

## Status Board

| Phase | Status | Last updated |
|---|---|---|
| Phase 0 — Prototype | 🟡 **Code complete & tested** — live-call validation blocked on provider credentials | 2026-07-16 |
| Phase 1 — Foundation | ⚪ Not started | — |
| Phase 2 — Hardening | ⚪ Not started | — |
| Phase 3 — Omnichannel | ⚪ Not started | — |
| Phase 4 — Differentiation | ⚪ Not started | — |

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

**Remaining for Phase 0 exit (blocked on credentials/accounts, not code):**

- [ ] Provision LiveKit Cloud project + Deepgram/Anthropic/Cartesia API keys (fill `.env` from `.env.example`)
- [ ] Local voice smoke test: `uv run python -m agent.agent download-files` then `console` mode (mic/speaker)
- [ ] Twilio number → LiveKit SIP inbound trunk + dispatch rule (architecture doc §7.3)
- [ ] **Exit criterion:** ≥20 real test calls, p95 turn latency ≤800 ms via `/metrics/calls/{call_id}`
- [ ] **Exit criterion:** barge-in interrupts TTS within ~200 ms (manual verification on test calls)
- [ ] **Exit criterion:** written per-stage latency breakdown identifying the actual bottleneck

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

---

## Phase 4 — Differentiation (week 24+)

Only after the core is boringly reliable:

- **Per-firm voice cloning** (branded, consistent voice per firm).
- **Per-firm qualification tuning** — learn from attorney accept/reject decisions to refine qualification; evaluate fine-tunes vs. richer RAG context per firm.
- **Smart referrals** — route declined-but-viable cases to partner firms (product + marketplace motion, not just engineering).
- **Analytics product** — intake funnel benchmarks firms will pay for on their own.
- **Selective speech-to-speech** — revisit S2S for the greeting segment only, keeping cascading for the qualification body, if realism benchmarks justify it.

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
2. **Provider dependence** (pricing, deprecation, brownouts). Mitigation: cascading architecture + interfaces + Phase 2 failover; re-verify model/pricing quarterly (doc is explicit that this space moves fast).
3. **CMS adapter fragility** — long-tail legal APIs are messy, poll-based, or partner-gated. Mitigation: normalized schema + ABC proven against three dissimilar providers (Clio/Filevine/Litify) before scaling breadth; adapters are demand-ordered.
4. **Compliance incident** (advice given, consent violated, PHI leaked). Mitigation: guardrail pass in-pipeline from Phase 1, redaction before persistence in Phase 2, consent rules per state, human-transfer escape hatch always available.
5. **Scope creep into channels before voice is solid.** Mitigation: phase gates — omnichannel (Phase 3) is blocked on hardening (Phase 2) exit criteria, no exceptions.

## Sequencing Logic (why this order)

Voice latency is the only assumption that can kill the project, so it goes first with everything else mocked. Multi-tenancy, the event bus, and the adapter interface are the irreversible decisions, so they come second, done once, done right. Scale and compliance come third because you harden against real traffic, not imagined traffic. Channels and outbound come fourth because they reuse the proven brain over cheap new transports. Differentiation comes last because cloned voices on a flaky pipeline is lipstick on downtime.
