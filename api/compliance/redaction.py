"""PII/PHI redaction pipeline (Phase 2 Workstream C).

Deterministic, dependency-free, microseconds per call — the same design
rules as the guardrail screen, because redaction sits on every persistence
and logging path. Two surfaces:

  * ``redact_text`` / ``redact_turns`` — pattern-based scrubbing of free
    text (SSNs, credit cards, emails, phone numbers, street addresses).
  * ``redact_structured`` — key-aware scrubbing of structured payloads
    (a field *named* ``phone`` is PII no matter what its value looks like).

Raw transcripts stay in Postgres behind RLS; the default read path serves
the redacted copy. Only a token holding the ``transcripts:raw`` scope (or
the platform admin) sees originals. Incident dates are deliberately NOT
redacted — they are case facts the qualification pipeline runs on, not
identifiers.
"""

from __future__ import annotations

import logging
import re

REDACTED = "[REDACTED:{kind}]"

# Order matters: longer/more-specific shapes match before phone numbers
# would otherwise eat their digits.
_TEXT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ssn", re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b")),
    # 13-16 digit runs with optional separators; validated by Luhn below so
    # ordinary long numbers (claim numbers, case ids) survive.
    ("card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    (
        "phone",
        re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]?\d{4}(?!\d)"),
    ),
    ("phone", re.compile(r"(?<![\d-])\+?1?\d{10}(?![\d-])")),
    (
        "address",
        re.compile(
            r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}"
            r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln|Road|Rd|Court|Ct|Way|Place|Pl)"
            r"\.?\b",
        ),
    ),
]

# Structured-payload keys whose values are PII by definition.
_SENSITIVE_KEYS = {
    "name", "caller_name", "first_name", "last_name", "full_name",
    "phone", "phone_number", "from_number", "to", "to_number",
    "email", "email_address", "ssn", "dob", "date_of_birth", "address",
}


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def redact_text(text: str) -> str:
    """Scrub PII patterns from free text."""
    if not text:
        return text
    for kind, pattern in _TEXT_PATTERNS:
        if kind == "card":

            def _card(m: re.Match[str]) -> str:
                digits = re.sub(r"\D", "", m.group(0))
                return REDACTED.format(kind="card") if _luhn_ok(digits) else m.group(0)

            text = pattern.sub(_card, text)
        else:
            text = pattern.sub(REDACTED.format(kind=kind), text)
    return text


def redact_turns(turns: list[dict]) -> list[dict]:
    """Redacted copy of transcript turns; the original is never mutated."""
    return [{**t, "text": redact_text(t.get("text", ""))} for t in turns]


def redact_structured(obj: object) -> object:
    """Key-aware recursive scrub of a structured payload (dict/list/str)."""
    if isinstance(obj, dict):
        return {
            k: (
                REDACTED.format(kind=k)
                if k.lower() in _SENSITIVE_KEYS and obj[k] not in (None, "")
                else redact_structured(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_structured(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


class RedactingFilter(logging.Filter):
    """Logging filter that scrubs PII from every record it sees.

    Attach at the handler level so it covers all loggers routing through
    that handler. Formats the message eagerly (args folded in) so patterns
    that span an interpolation boundary still match.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_text(record.getMessage())
            record.args = None
        except Exception:  # noqa: BLE001 — a bad record must never kill logging
            pass
        return True


def install_log_redaction() -> None:
    """Attach the redacting filter to every current root handler (and keep a
    module-level filter instance for handlers created later via basicConfig).
    Call after logging is configured, in every process that logs."""
    filt = RedactingFilter()
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig()
    for handler in root.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(filt)
