"""Compliance layer: PII redaction, per-state consent, SOC 2 groundwork.

Phase 2 Workstream C. PI intake is treated as HIPAA-adjacent: nothing
personally identifying leaves the transcript store un-redacted unless the
caller holds an explicit ``transcripts:raw`` grant, and log/analytics paths
are scrubbed before anything is written.
"""
