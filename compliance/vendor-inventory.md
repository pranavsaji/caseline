# Vendor inventory (Phase 2 / SOC 2 groundwork)

Every external service in the serving path, what data reaches it, and the
blast radius if it fails. Re-verify quarterly (this space moves fast —
architecture doc §12).

| Vendor | Role | Data exposed | Failure blast radius | Mitigation |
|---|---|---|---|---|
| Deepgram | STT (primary) | Caller audio (PHI-adjacent) | Calls can't transcribe | STT FallbackAdapter (openai:whisper configurable) |
| Anthropic | LLM (primary) | Transcript turns, tool schemas | Agent can't reason | LLM FallbackAdapter (openai secondary) |
| Cartesia | TTS (primary) | Agent-side text only | Agent can't speak | TTS FallbackAdapter (openai secondary) |
| OpenAI | STT/LLM/TTS (secondary) | Same as the stage it backs | None unless primary is down | Off by default; enabled per-deploy |
| LiveKit Cloud / self-hosted SFU | Media transport | Live audio streams | No calls at all | Phase 2A: self-hosted SFU on GKE; LiveKit Cloud as fallback trunk |
| Twilio | PSTN/SIP ingress | Caller number, audio | No inbound calls | Evaluate Telnyx as second SIP provider (HD voice) |
| Clio / Filevine / Litify | Firm CMS | Intake records (names, phones, case facts) | Sync delayed — never blocks calls (async outbox) | DLQ + replay; idempotent writes |
| Google Cloud | Infra (SQL, Redis, Pub/Sub, GCS, KMS) | Everything at rest | Platform outage | Regional HA (prod tier), PITR backups |

Notes:
- No vendor receives credentials of another vendor; CMS credentials are
  encrypted with KMS and decrypted only in worker memory.
- Caller PII reaches STT/LLM vendors inherently (it's in the audio); this is
  the BAA/DPA conversation to have before HIPAA-sensitive verticals.
