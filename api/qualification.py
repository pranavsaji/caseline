"""Personal-injury qualification rules engine.

Pure functions, no I/O — this is the deterministic stand-in for the per-firm
qualification config that arrives in Phase 1. Decisions:

  qualified  -> book the consult
  refer_out  -> firm won't take it, hand to referral network
  decline    -> cannot take it at all (e.g. statute of limitations passed)

An unparseable or future incident date never auto-declines: a human should
verify before a potential case is turned away, so the lead stays `qualified`
with a needs-verification reason attached.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

DECISION_QUALIFIED = "qualified"
DECISION_REFER_OUT = "refer_out"
DECISION_DECLINE = "decline"

# Injury descriptions the firm refers out rather than works.
REFER_OUT_INJURIES = {"minor", "none", "no injury", "property damage only"}


@dataclass(frozen=True)
class QualificationConfig:
    """Firm-level knobs. Phase 1 loads these from the firm's agent config
    (jsonb on the agents row); Phase 0 callers use the defaults."""

    statute_of_limitations_days: int = 730  # 2 years, common PI default
    refer_out_injuries: frozenset[str] = frozenset(REFER_OUT_INJURIES)


@dataclass(frozen=True)
class QualificationResult:
    decision: str
    reasons: list[str]


def _parse_incident_date(raw: str, today: date) -> tuple[date | None, str | None]:
    """Return (parsed_date, problem). Only ISO dates are trusted; the agent's
    tool schema asks the LLM for ISO format, so anything else means the model
    could not pin the caller down and a human should verify."""
    try:
        parsed = date.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        return None, f"incident date {raw!r} is not a valid ISO date"
    if parsed > today:
        return None, f"incident date {parsed.isoformat()} is in the future"
    return parsed, None


def qualify(
    incident_date: str,
    injury_type: str,
    in_treatment: bool,
    has_insurance: bool,
    config: QualificationConfig | None = None,
    today: date | None = None,
) -> QualificationResult:
    config = config or QualificationConfig()
    today = today or date.today()
    reasons: list[str] = []

    parsed, date_problem = _parse_incident_date(incident_date, today)

    if parsed is not None:
        days_since = (today - parsed).days
        if days_since > config.statute_of_limitations_days:
            return QualificationResult(
                decision=DECISION_DECLINE,
                reasons=[
                    f"incident is {days_since} days old, past the "
                    f"{config.statute_of_limitations_days}-day statute-of-limitations gate"
                ],
            )
        reasons.append(f"incident is {days_since} days old, within limitations period")
    else:
        reasons.append(f"{date_problem}; needs human verification before decline")

    if injury_type.strip().lower() in config.refer_out_injuries:
        return QualificationResult(
            decision=DECISION_REFER_OUT,
            reasons=reasons + [f"injury type {injury_type!r} is below the firm's threshold"],
        )

    reasons.append(f"injury type {injury_type!r} accepted")
    reasons.append("in active treatment" if in_treatment else "not currently in treatment")
    reasons.append("insurance present" if has_insurance else "no insurance on file")
    return QualificationResult(decision=DECISION_QUALIFIED, reasons=reasons)
