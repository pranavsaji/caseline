-- Per-turn latency: surface two stages that used to be invisible.
--
--   stt_ms       — the STT-finalization slice of the EOU delay
--                  (EOUMetrics.transcription_delay). A breakdown of
--                  eou_delay_ms, not additive to total_ms.
--   guardrail_ms — CPU time the regex guardrail spent screening the turn's
--                  tokens between the LLM and TTS.
--
-- Nullable: older turns and any turn where the metric didn't fire simply have
-- NULL, and total_ms stays the eou+llm+tts formula unchanged.

ALTER TABLE turn_metrics ADD COLUMN stt_ms real;
ALTER TABLE turn_metrics ADD COLUMN guardrail_ms real;
