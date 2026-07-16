# Caseline — Phase 0 Prototype

AI voice intake receptionist for personal-injury law firms. Phase 0 proves the marquee path: **call a number → natural voice conversation → lead qualified → consult booked → structured record in a (mock) CMS**, with per-turn latency instrumentation from day one.

- Architecture: [`caseline-voice-intake-architecture.md`](caseline-voice-intake-architecture.md)
- Phased plan + progress tracking: [`plan.md`](plan.md)

## Stack (Phase 0)

| Layer | Choice |
|---|---|
| Transport | LiveKit Cloud (SIP inbound trunk from Twilio/Telnyx) |
| Agent framework | LiveKit Agents (Python), cascading pipeline |
| STT | Deepgram Nova-3 (streaming) |
| LLM | Claude Haiku 4.5 (`claude-haiku-4-5`) |
| TTS | Cartesia Sonic-3 (streaming) |
| Turn-taking | Silero VAD + multilingual semantic end-of-utterance model |
| Backend | FastAPI + SQLite (throwaway; Postgres arrives in Phase 1) |

## Layout

```
agent/                    # LiveKit Agents voice worker
  agent.py                #   worker: pipeline wiring, tools, metrics hookup
  backend_client.py       #   HTTP client for tool endpoints (livekit-free, testable)
  latency.py              #   per-turn latency stitching + p50/p95 (livekit-free)
api/                      # FastAPI backend
  main.py                 #   app factory + routes
  qualification.py        #   PI qualification rules engine (pure functions)
  storage.py              #   SQLite store (consults, cms_records, turn_metrics)
  schemas.py              #   pydantic request/response models
tests/                    # pytest suite (no API keys or network needed)
```

## Setup

Requires Python ≥3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                       # creates .venv and installs everything
cp .env.example .env          # then fill in provider keys
```

## Run the tests (no keys needed)

```bash
uv run pytest -v
```

The suite covers the qualification rules engine, every backend endpoint, the latency tracker, and the exact agent→backend HTTP contract (real `BackendClient` against the real app in-process).

## Run the demo

**1. Backend:**

```bash
uv run uvicorn api.main:app --port 8000
```

**2. Voice worker** (needs `DEEPGRAM_API_KEY`, `ANTHROPIC_API_KEY`, `CARTESIA_API_KEY`; `dev` mode also needs `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`):

```bash
uv run python -m agent.agent download-files   # one-time: turn-detector + VAD models
uv run python -m agent.agent console          # local mic/speaker, no telephony
uv run python -m agent.agent dev              # connect to LiveKit, take real calls
```

**3. Telephony (marquee demo):** buy a Twilio number, point it at a LiveKit Cloud SIP inbound trunk, add a dispatch rule that routes to this agent. See architecture doc §7.3.

**4. Inspect the results:**

```bash
curl -s localhost:8000/mock-cms | jq                    # structured intake records
curl -s localhost:8000/consults | jq                    # booked consults
curl -s localhost:8000/metrics/calls/<room-name> | jq   # per-call p50/p95 latency
```

`within_budget` in the metrics response is the Phase 0 exit criterion: p95 turn latency ≤ 800 ms.

## Deliberately out of scope in Phase 0

Multi-tenancy, real CMS integration, SMS/email, recordings retention, guardrail classifier, autoscaling, infra-as-code. See `plan.md`.
