# Caseline — Business & Value Overview

*Caseline isn't software a firm buys. It's an **employee a firm hires** — a full-time AI intake
specialist that answers every call in the firm's own voice, qualifies each lead against the
firm's own rules, books the consult, and files a clean record in the firm's case-management
system. It works the phones, the texts, the emails, and the webforms; it chases signed clients
for the documents their cases need; and it refers out the work the firm won't take. It starts on
day one, never misses a shift, never takes a call it can't handle, and costs a fraction of the
team it replaces the workload of.*

This is the business-facing companion to [`TECHNICAL.md`](TECHNICAL.md); for a shorter, plain-language
"what it is" overview start with [`OVERVIEW.md`](OVERVIEW.md). This document covers the problem,
the value, the product, the market, how to position and pitch it, pricing logic, and objection
handling — all through one lens: **you're hiring an employee, not licensing a tool.**

---

## 0. The core frame: hire, don't buy

Everything in this document sells better when you stop describing a product and start describing a
**new hire**. Firms understand employees. They know what an intake specialist does, what one
costs, and what it feels like when one drops a lead. Caseline slots into that mental model exactly:

| A human intake hire | Caseline, the AI intake employee |
|---|---|
| Job title: Intake Specialist / Receptionist | Same job. Answers calls, qualifies leads, books consults, follows up. |
| Takes weeks to hire and train | **Onboarded in a day.** You give it the firm's script, rules, and voice; it's ready. |
| Works one call at a time, 40 hours a week | Works **every call at once, 24/7/365** — nights, weekends, holidays, call spikes. |
| Qualifies differently on a bad day | Qualifies **the same way every time**, with a written reason on every decision. |
| Calls in sick, quits, needs managing | Never absent, never turns over, improves as it learns your attorneys' preferences. |
| One salary + benefits + overhead | **A few cents per call** to run; priced against the cases it saves. |
| Takes a message and forgets to follow up | **Follows up automatically** — chases web leads in <1s, chases signed clients for documents. |
| Works in their own head; you hope they log it | **Files structured data in your CMS after every interaction.** Nothing to chase. |

The rest of this doc is the case for that hire.

---

## 1. The problem, in the firm's own money

Law firms lose real revenue at the front door, and they mostly can't see it happening:

- **~30% of potential clients never convert** because calls get missed — after hours, during
  other calls, at lunch, on weekends. A personal-injury lead is worth thousands to tens of
  thousands of dollars in fee value; a missed call is often a signed case walking to the next
  firm on the Google results page.
- **Speed-to-lead decides who wins.** When a lead fills out a webform or clicks an ad, the firm
  that contacts them **first** almost always signs them. Minutes matter; most firms respond in
  hours, if at all. Marketing dollars spent generating that lead are wasted if nobody works it
  fast enough.
- **After-hours is a black hole.** Accidents and arrests don't happen 9-to-5. The lead who calls
  at 11pm reaches a voicemail box and calls a competitor.
- **Intake staff are expensive, inconsistent, and don't scale.** A human receptionist costs a
  salary, works one call at a time, takes vacations, and qualifies leads differently on a bad
  day. Hiring more of them is linear cost for linear capacity.
- **Marketing spend leaks out the bottom.** Firms pour money into ads and SEO to make the phone
  ring, then let a third of those rings go unanswered or poorly worked. The leak is at intake,
  not acquisition.

**Caseline's one-sentence pitch:** *Hire an AI intake employee that answers every call and every
lead instantly, qualifies them by your rules, books the consult, and files it in your system — so
you stop losing cases you already paid to acquire.*

---

## 2. The value proposition

**Revenue protection, not a productivity tool.** This is the frame that sells. Caseline isn't
"save your staff time" — it's "stop leaking signed cases." Every missed call this employee catches
and every lead it contacts in one second instead of one hour is directly attributable case value.

Concretely, the employee you're hiring delivers:

1. **Zero missed intake.** Every call answered on the first ring, 24/7/365, in a natural voice —
   no voicemail, no hold music, no "we're closed."
2. **Sub-second speed-to-lead.** A webform lead is texted back in **~0.6 seconds** (measured),
   not hours. The firm is first, so the firm signs.
3. **Consistent, rules-based qualification.** The AI qualifies every lead against the firm's own
   criteria (statute of limitations, injury type, treatment status, insurance) — the same way,
   every time, with a reason attached to every decision.
4. **It lives inside the firm's existing system.** Structured intake data is written straight
   into Clio / Filevine / Litify. **Nothing new for staff to learn** — the AI works where they
   already work.
5. **It's an employee, not a receptionist.** It follows up. It chases signed personal-injury
   clients for treatment updates and missing documents. It hands off cases the firm won't take to
   partner firms (and tracks who converts).
6. **Compliance built in.** Recording consent by state, TCPA-safe outbound, PII redaction, and
   in-line guardrails that stop the employee from ever giving legal advice, quoting a fee, or
   promising an outcome — the three things that create liability in a legal setting. It's a hire
   that already knows the rules of the profession it works in.

**The ROI math a founder can say out loud:** if a firm misses even a handful of qualified PI
leads a month, and each signed case is worth several thousand dollars in fees, recovering a
*single* case a month pays for the service many times over. The product sells against lost
revenue, which is a far bigger number than a receptionist's salary.

---

## 3. The job description — five things this employee does

Caseline is built around the five things a great intake employee actually does on the job:

| Capability | What it does | Why a firm cares |
|---|---|---|
| **AI Receptionist** | Answers inbound calls in the firm's branded voice, identifies caller type (new lead, existing client, adjuster, spam, referral source), routes by the firm's rules. | Every call answered instantly, correctly triaged, 24/7. |
| **Real-time qualification & smart routing** | Runs the firm's qualification script live, extracts structured case facts, decides qualified / refer-out / decline — with a human-readable reason on every decision. | Consistent screening; attorneys' time goes only to real cases. |
| **Digital Lead Chaser** | Detects a webform/ad/email lead and reaches out (SMS or call) within ~1 second, TCPA-compliant, then holds the whole conversation. | Wins the speed-to-lead race that decides who signs. |
| **Customized handoff** | Live-transfers to an on-call attorney, books a consult on the calendar, sends an SMS/email, or takes a message — whichever the outcome calls for. | The lead never hits a dead end; the right thing happens automatically. |
| **Treatment Tracker** | For signed PI clients, periodically checks in on medical treatment progress and chases missing documents, creating tasks in the CMS. | Protects case value after signing — the PI-specific killer feature. |

Underneath all five: **every interaction is logged, structured, and centralized** in the firm's
CMS after it happens — this is an employee that documents its own work. And you train it in a
**config studio** (its playbook: script, qualification rules, routing, hours, voice) with a
zero-risk **test-call preview** — interview the new hire and role-play calls before it ever picks
up a real one, with no side effects.

---

## 4. Why the integrations are the moat

The AI demo is impressive but copyable. The defensibility is in **clean, idempotent,
bi-directional sync across a dozen messy legal case-management systems.** Caseline ships adapters
for the three highest-value systems behind a single internal interface:

- **Clio** — solid REST API, the market-leading CMS.
- **Filevine** — strong API, popular with PI firms.
- **Litify** — Salesforce-native (you talk to Salesforce APIs and its managed-package objects),
  the enterprise-PI system.
- Plus a **mock adapter** for demos and onboarding.

These systems vary wildly in API quality, and building/maintaining adapters that *never duplicate
a matter or double-book a consult* — even under retries and failures — is genuinely hard
engineering. That's the part competitors can't quickly clone, and it's the reason a firm can't
easily rip Caseline out once it's wired into their system of record. The normalized internal
schema (Lead / Contact / Matter / Task / Note) means adding the next CMS (MyCase, Lawmatics, Law
Ruler, Lead Docket, Neos, …) is a bounded adapter project, not a re-architecture.

---

## 5. Target market

**Anchor vertical: Personal Injury.** The Treatment Tracker, the "protect case value" language,
and the highest per-case fee values all point at PI first. PI firms spend heavily on marketing,
live and die on speed-to-lead, and feel missed-call pain most acutely.

**Expansion verticals:** Family Law, Criminal Defense, Immigration, Employment Law, Estate
Planning — same intake motion, different qualification rules (which are just per-firm config).

**Buyer:** the firm owner / managing partner (revenue owner) and the intake manager (workflow
owner). The pitch to the partner is revenue; the pitch to the intake manager is "it does the
repetitive work and never drops a lead."

---

## 6. How to pitch it

### 6.1 The 30-second version

> "Law firms lose about a third of their potential clients to missed calls, and they lose the
> rest to slow follow-up. Caseline is an AI employee you hire to fix that. It answers every call
> in a natural voice, texts back every web lead in under a second, qualifies them by your rules,
> books the consult, and files it in Clio or Filevine — 24/7, never a sick day. It doesn't just
> answer phones; it chases your signed clients for documents and refers out the cases you don't
> want. One hire, a fraction of a salary, and you stop losing cases you already paid to acquire."

### 6.2 The demo that closes

The single most persuasive thing is a live call. **Call a number → an AI answers in a natural
voice → it qualifies you as a PI lead → books a consult → a structured record appears in the
CMS.** Sub-second turn latency makes it feel human, not like a 2019 phone tree. Follow that with
the dashboard: the transcript, the per-turn latency, the qualification reasoning, and the record
that landed in the CMS. Then show the webform → 0.6-second text-back. That sequence — *it sounds
human, it's instant, and it already filed the paperwork* — is what wins the room.

### 6.3 The pitch arc

1. **Open with their leak, in dollars.** "How many after-hours calls did you get last month? How
   fast do you call a web lead back? What does it cost you to hire and keep an intake person?"
   Let them feel the number.
2. **Introduce the hire.** "Let me introduce your new intake specialist." Then show the live call
   — realism + speed does the heavy lifting.
3. **Show it inside their CMS.** "There's nothing new for your team to learn — this employee works
   where they already work, and documents everything itself." This kills the change-management
   objection.
4. **Show the follow-up + referral + treatment tracker.** "A receptionist takes a message. An
   employee follows up." This is the expansion story and the retention story.
5. **Close on compliance.** Consent, TCPA, PII redaction, no-legal-advice guardrails. "It's a
   hire that already knows the rules of the profession." In a regulated, dispute-prone field this
   is a reason to trust, not a footnote.

### 6.4 Positioning against the alternatives

- **vs. a human receptionist / answering service:** it's the same job, but this hire answers
  *every* call simultaneously, never has after-hours gaps, qualifies consistently, and documents
  its own work in the CMS — a service that takes a message can't do that. One "salary," a fraction
  of the cost, and capacity that scales with call volume instead of headcount. It doesn't replace
  your best people; it covers the shifts and spikes they can't.
- **vs. a generic AI voice tool:** those are software. Caseline is a *trained* employee for legal
  intake specifically — it knows the qualification logic, lives in the firm's CMS, follows the
  compliance rules, and runs the treatment tracker. A horizontal voicebot has none of that job
  training and can't be trusted in a legal setting.
- **vs. doing nothing:** the open role is costing them cases every week — the leak is invisible on
  the P&L but real. The pitch quantifies the vacancy.

---

## 7. What makes it credible (engineering proof points a buyer will trust)

You don't sell these details, but they're the substance behind the promises — and they matter to
a sophisticated buyer or investor:

- **It's genuinely fast.** A hard ≤800 ms-per-turn latency ceiling, measured per stage on every
  call (now down to the STT-finalization and guardrail slices), through a real production stack.
  The conversational model is chosen for exactly this — a fast, natural, reliable tool-caller — and
  is **selectable per firm** from a dozen-plus providers, so the firm is never locked to one
  vendor's price or speed. This is the difference between "sounds human" and "sounds like a robot."
- **It never double-files.** Every write to the CMS carries an idempotency key; a 50-call load
  test with forced duplicates produced exactly one lead and one consult per call, zero
  duplicates. Firms trust their system of record because it's provably clean.
- **It won't say the wrong thing.** Two layers of in-pipeline guardrails (under 5 ms) block legal
  advice, fee quotes, and outcome guarantees before the caller ever hears them.
- **It respects consent, structurally.** No SMS consent means no automated outbound, ever. STOP
  is permanent. Recording disclosure is mandatory in two-party-consent states and the firm can't
  turn it off. Voice cloning and case referrals both require explicit, recorded consent.
- **Tenants can't see each other's data.** Isolation is enforced at the database level (Postgres
  row-level security), verified by tests that try to cross tenants and fail.
- **It fails over gracefully.** If a voice provider slows or errors mid-call, it switches to a
  backup provider without dropping the call — a reliability property a single-model system can't
  offer.
- **It's proven end-to-end.** 257 automated tests, live validation on real provider APIs, and a
  running cloud deployment (with a login-gated operator dashboard). This is a working system, not
  a slide.

---

## 8. Pricing logic (how to think about it)

Price it the way a firm thinks about a hire: **a monthly salary for an employee that never sleeps.**
The cost to serve is low — on the order of **a few cents per call** (~2.5¢ in LLM cost, plus STT/
TTS/telephony) — which gives enormous headroom, because you're pricing against the **salary of the
team it replaces the workload of** and the **cases it recovers**, not against cost-to-serve.

Sensible packaging:

- **A monthly "salary" per employee** (per-firm subscription) tiered by call/lead volume and
  seats, CMS integration and config studio included. Anchor it to what a part-time intake hire
  costs — then point out this one works 24/7 and takes every call at once. A firm that would
  never blink at a $4–6k/mo intake salary sees the value instantly.
- **Usage component** for high-volume firms (per-minute or per-lead) so cost scales with the work
  the employee does.
- **Hire more than one.** Expansion revenue is literally staffing up: a dedicated chaser employee
  separate from the receptionist, plus the analytics/benchmark product firms pay for on its own,
  and the smart-referral marketplace (a natural referral-fee or take-rate motion later).

The margin story is strong: near-zero marginal cost per interaction against a subscription priced
to a fraction of the salary — and the revenue — it protects.

---

## 9. Differentiation & expansion (the moat widens over time)

Beyond the core intake loop, Caseline has built the features that turn a tool into a platform:

- **Per-firm branded voice cloning** — the AI sounds like it belongs to that firm (consent-gated).
- **Qualification that learns** — attorneys accept/reject the AI's leads, and the system surfaces
  advisory tuning suggestions (a human applies them) so screening gets sharper over time, while
  staying fully explainable for legal review.
- **Smart referrals marketplace** — cases the firm won't take are routed to partner firms with
  the client's consent, and partner conversion is tracked. This is a network-effects motion, not
  just a feature.
- **Benchmark analytics** — a firm sees its intake funnel (qualification rate, booking rate,
  speed-to-lead, latency) against an anonymized peer cohort (k-anonymous, aggregates only). Firms
  pay for this on its own, and it's data no single-firm tool can produce.

Each of these deepens lock-in the way a tenured employee does: the branded voice, the tuned rules,
the partner network, and the benchmark history are all institutional knowledge the firm loses if
it lets this employee go. The longer it works there, the more it's worth — and the harder it is to
replace.

---

## 10. Objection handling

| Objection | Response |
|---|---|
| "Callers hate talking to robots." | Play the live call. Sub-second latency and a branded, natural voice change the reaction — and it discloses it's an AI where required. The alternative for a missed call isn't a human, it's voicemail. |
| "What if it gives bad legal advice?" | It structurally can't. Two in-pipeline guardrail layers block legal advice, fee quotes, and outcome guarantees before the caller hears anything. It captures facts; it never advises. |
| "We already have a receptionist / answering service." | Then think of Caseline as the hire that covers what one person can't: it answers every call at once, 24/7, qualifies consistently, writes structured data into your CMS, and keeps working leads and clients after the call. It doesn't replace your best people — it makes sure nothing reaches voicemail while they're busy, at lunch, or gone for the night. |
| "I'm not comfortable letting an AI handle my clients." | You're not handing over judgment — you're hiring for the repetitive front-door work, with an escape hatch. It qualifies and books; it live-transfers to a human the moment a call needs one; and every attorney still reviews and can accept/reject its leads, which is how it learns your preferences. You stay in charge; it just makes sure no one is ever left ringing. |
| "Is our client data safe?" | Tenant data is isolated at the database level, PII is redacted before it hits logs or analytics, CMS credentials are encrypted, and every interaction is an immutable audit record. SOC 2 groundwork is in place. |
| "We use [CMS X] that you don't support yet." | The integration layer is a normalized interface — adding a CMS is a bounded adapter project. Clio, Filevine, and Litify ship today; the roadmap covers the rest of the legal-CMS landscape. |
| "This sounds expensive." | It's priced against the case value you're currently losing. Recover one qualified PI case a month and it pays for itself many times over — and cost-to-serve is a few cents a call. |

---

## 11. One-paragraph summary for a deck or email

> Caseline is an AI intake employee that law firms hire — not software they buy. It answers every
> inbound call in a natural, branded voice 24/7, texts back web leads in under a second, qualifies
> each lead against the firm's own rules, books the consult, and writes a clean structured record
> into the firm's case-management system (Clio, Filevine, Litify) — with nothing new for staff to
> learn. It works the phones, texts, and emails, chases signed personal-injury clients for
> treatment updates and documents, and refers out cases the firm won't take. It onboards in a day,
> never misses a shift, and costs a fraction of the intake team whose workload it carries.
> Compliance is built in: recording consent by state, TCPA-safe outbound, PII redaction, and
> guardrails that stop it from ever giving legal advice. Firms lose roughly a third of their
> potential clients to missed calls and slow follow-up; this is the employee that closes that
> leak, so they stop losing cases they already paid to acquire.
