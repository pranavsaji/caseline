# Caseline — What It Is

*A plain-language overview of the business and the product. This is the "start here" document:
it explains what Caseline is, the problem it solves, what it does, and how it works — without the
sales framing of [`BUSINESS.md`](BUSINESS.md) or the engineering depth of
[`TECHNICAL.md`](TECHNICAL.md). Read those next depending on whether you're pitching it or building
on it.*

---

## In one line

**Caseline is an AI intake employee for law firms** — it answers every call in a natural voice,
qualifies each lead against the firm's own rules, books the consult, and files a clean record in
the firm's case-management system, 24/7. It runs the same brain over text and email, chases web
leads within seconds, and follows up with signed clients — the work a whole intake team does, for
a fraction of the cost.

## What it is (and isn't)

It is **hired, not licensed.** The mental model is an employee, not a software tool: you give it
the firm's script, qualification rules, and voice, and it starts taking calls the same day. It
never misses a shift, answers every call at once, qualifies the same way every time, and documents
its own work in the firm's system.

It is **not** a generic voicebot or an answering service. It's trained for legal intake
specifically — it knows the qualification logic, lives inside the firm's CMS, follows the
compliance rules of the profession, and can't give legal advice, quote a fee, or promise an outcome.

## The problem it solves

Law firms lose real revenue at the front door and mostly can't see it:

- **~30% of potential clients never convert** because calls get missed — after hours, during other
  calls, on weekends. A personal-injury case can be worth thousands to tens of thousands in fees; a
  missed call is a signed case walking to the next firm.
- **Speed-to-lead decides who wins.** The firm that contacts a web lead *first* almost always signs
  it. Most firms respond in hours, if at all.
- **Intake staff are expensive, inconsistent, and don't scale.** One person, one call at a time,
  vacations and sick days, and a different mood on a bad day.

The leak is at intake, not at marketing. Caseline closes it.

## What it does — five jobs

| Capability | What it does |
|---|---|
| **AI Receptionist** | Answers inbound calls in the firm's branded voice, identifies the caller type, and routes by the firm's rules — every call, instantly, around the clock. |
| **Real-time qualification & routing** | Runs the firm's qualification script live, extracts the case facts, and decides qualified / refer-out / decline — with a written reason on every decision. |
| **Digital Lead Chaser** | Detects a webform/ad/email lead and reaches out (text or call) within about a second — TCPA-compliant — then holds the whole conversation. |
| **Customized handoff** | Live-transfers to an on-call attorney, books a consult on the calendar, sends a text/email, or takes a message — whichever the outcome calls for. |
| **Treatment Tracker** | For signed personal-injury clients, checks in on treatment progress and chases missing documents, creating tasks in the CMS — protecting case value after signing. |

Underneath all five: **every interaction is logged, structured, and written into the firm's CMS**
(Clio, Filevine, or Litify) after it happens. Nothing for staff to chase or re-type.

## How it works (in plain terms)

1. **A call or lead comes in** — over the phone, a web form, a text, or an email.
2. **The AI handles it live.** For voice, it listens, thinks, and speaks fast enough to feel human
   (under an 800-millisecond-per-turn ceiling, measured on every call). It greets the caller, runs
   the firm's script, and captures the facts.
3. **It decides and acts** using a fixed set of safe, deterministic actions — look up the caller,
   qualify the lead, book a consult, transfer to a human, send a text, take a message.
4. **It files the record** into the firm's case-management system, safely and without duplicates,
   off to the side so it never slows down the live call.
5. **It follows up** — chasing web leads in seconds, checking in with signed clients, and referring
   out cases the firm won't take (with the client's consent).

The firm sets all of this up — and safely test-drives it — in a **Config Studio** dashboard, and
watches everything it does (transcripts, speed, qualification reasoning, outcomes) from a
login-protected operator console.

## Who it's for

- **Anchor market: Personal Injury firms.** Highest per-case value, heaviest marketing spend, and
  the most acute missed-call and speed-to-lead pain. The Treatment Tracker is PI-specific.
- **Expansion: Family Law, Criminal Defense, Immigration, Employment, Estate Planning** — the same
  intake motion, different qualification rules (which are just per-firm configuration).
- **Buyers:** the managing partner (who owns the revenue) and the intake manager (who owns the
  workflow).

## Why it's defensible

The impressive AI demo is copyable; the moat is **clean, two-way, never-duplicating sync across a
dozen messy legal case-management systems.** Once Caseline is wired into a firm's system of record —
with its branded voice, tuned rules, partner-referral network, and benchmark history — it's an
institutional employee the firm doesn't want to let go. The longer it works there, the more it's
worth.

## Compliance, built in

Recording consent by state, TCPA-safe outbound texting (no consent → no automated outbound; a hard
send-gate until carrier registration clears), PII redaction before data hits logs, encrypted CMS
credentials, tenant data isolated at the database level, and in-line guardrails that stop the AI
from ever giving legal advice, quoting a fee, or promising an outcome. It's a hire that already
knows the rules of the profession.

## How to think about price

Price it like a hire: **a monthly "salary" for an employee that never sleeps.** Cost to run is a
few cents per call, so it's priced against the cases it recovers and the intake salary it replaces
the workload of — not against cost-to-serve. Recovering a single qualified PI case a month pays for
it many times over.

## Where the product stands today

A **working system, not a slide.** All five capabilities are code-complete and covered by 257
automated tests. It's been run live end-to-end on real voice/telephony providers, deployed to the
cloud (backend and agent on Railway, dashboard on Vercel), and load-tested at 50 simultaneous calls
with zero duplicate records. The remaining work to go fully live for a given firm is account
provisioning (a phone number and SIP trunk, the firm's real CMS credentials, a cloned-voice key,
and A2P text-messaging registration) — setup, not engineering.

---

**Read next:** [`BUSINESS.md`](BUSINESS.md) for positioning, pitch, pricing, and objection
handling · [`TECHNICAL.md`](TECHNICAL.md) for the architecture and engineering detail ·
[`README.md`](README.md) for the phase-by-phase build status.
