"""Per-firm qualification tuning (Phase 4): learn from attorney verdicts.

Attorneys record accept/reject verdicts on leads (``lead_reviews``). This
module compares those verdicts against what the rules engine decided and
produces **suggestions** — never silent changes. A human applies a proposed
rule set through the same validated config path every other edit uses
(``PUT /v1/agents/{id}/config``), so tuning is auditable and reversible.

Why deterministic rule tuning instead of a per-firm fine-tune or RAG
context (the plan asks for the evaluation):

  * Qualification decisions must stay *explainable* — "declined: incident is
    900 days old, past the firm's 730-day gate" survives a bar-complaint
    review; a fine-tuned model's weights do not.
  * The signal is tiny (tens of verdicts per firm), which is fine-tune
    starvation territory but plenty for threshold/list adjustment with a
    minimum-sample gate.
  * The rules engine is the per-firm seam we already have; tuning its
    config reuses validation, caching, and the preview studio unchanged.
  Revisit an LLM-assisted extractor/ranker when verdict volume (hundreds per
  firm) supports holdout evaluation; the suggestion interface here would not
  change.

All functions are pure: rows in, report out. The API route feeds them from
``lead_reviews`` joined to the qualification payload stored on each lead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from api.orchestration.config import QualificationRules

# A suggestion needs at least this many verdicts behind it, and this level
# of attorney (dis)agreement, before it is worth a human's attention.
MIN_SAMPLES = 5
AGREEMENT_THRESHOLD = 0.8
# Suggested statute-of-limitations gates round up to whole months.
SOL_ROUND_DAYS = 30


@dataclass(frozen=True)
class ReviewSample:
    """One attorney verdict joined to what the engine decided at the time."""

    verdict: str  # accepted | rejected
    decision: str  # qualified | refer_out | decline
    injury_type: str | None
    incident_age_days: int | None  # age at qualification time; None if unparseable


@dataclass
class Suggestion:
    kind: str  # add_refer_out_injury | remove_refer_out_injury | tighten_sol_days
    detail: str
    evidence: dict


@dataclass
class TuningReport:
    reviews: int
    agreement_rate: float | None
    matrix: dict[str, dict[str, int]]  # engine decision -> verdict -> count
    suggestions: list[Suggestion] = field(default_factory=list)
    proposed_rules: dict | None = None


def sample_from_row(
    verdict: str, qualification: dict | None, lead_created: date
) -> ReviewSample:
    """Build a ReviewSample from a lead's stored qualification payload."""
    q = qualification or {}
    age: int | None = None
    try:
        incident = date.fromisoformat(str(q.get("incident_date", "")).strip())
        age = (lead_created - incident).days
        if age < 0:
            age = None
    except ValueError:
        age = None
    injury = q.get("injury_type")
    return ReviewSample(
        verdict=verdict,
        decision=q.get("decision", "qualified"),
        injury_type=injury.strip().lower() if isinstance(injury, str) else None,
        incident_age_days=age,
    )


def _agreed(sample: ReviewSample) -> bool:
    """The engine and the attorney agree when a qualified lead is accepted
    or a refer_out/decline lead is rejected."""
    if sample.decision == "qualified":
        return sample.verdict == "accepted"
    return sample.verdict == "rejected"


def _injury_suggestions(
    samples: list[ReviewSample],
    rules: QualificationRules,
    min_samples: int,
    threshold: float,
) -> list[Suggestion]:
    refer_out = {i.strip().lower() for i in rules.refer_out_injuries}
    by_injury: dict[str, list[ReviewSample]] = {}
    for s in samples:
        if s.injury_type:
            by_injury.setdefault(s.injury_type, []).append(s)

    suggestions: list[Suggestion] = []
    for injury, group in sorted(by_injury.items()):
        qualified = [s for s in group if s.decision == "qualified"]
        referred = [s for s in group if s.decision == "refer_out"]
        # Attorneys keep rejecting an injury the engine qualifies -> the firm
        # doesn't actually want these; propose adding it to the refer-out list.
        if injury not in refer_out and len(qualified) >= min_samples:
            rejected = sum(1 for s in qualified if s.verdict == "rejected")
            rate = rejected / len(qualified)
            if rate >= threshold:
                suggestions.append(
                    Suggestion(
                        kind="add_refer_out_injury",
                        detail=(
                            f"attorneys rejected {rejected}/{len(qualified)} qualified "
                            f"{injury!r} leads — add it to refer_out_injuries"
                        ),
                        evidence={"injury_type": injury, "reviews": len(qualified),
                                  "rejected": rejected, "rejection_rate": round(rate, 3)},
                    )
                )
        # Attorneys keep accepting an injury the engine refers out -> the
        # firm is losing cases it wants; propose removing it from the list.
        if injury in refer_out and len(referred) >= min_samples:
            accepted = sum(1 for s in referred if s.verdict == "accepted")
            rate = accepted / len(referred)
            if rate >= threshold:
                suggestions.append(
                    Suggestion(
                        kind="remove_refer_out_injury",
                        detail=(
                            f"attorneys accepted {accepted}/{len(referred)} referred-out "
                            f"{injury!r} leads — remove it from refer_out_injuries"
                        ),
                        evidence={"injury_type": injury, "reviews": len(referred),
                                  "accepted": accepted, "acceptance_rate": round(rate, 3)},
                    )
                )
    return suggestions


def _sol_suggestion(
    samples: list[ReviewSample],
    rules: QualificationRules,
    min_samples: int,
) -> Suggestion | None:
    """Suggest a tighter statute-of-limitations gate when attorneys reject
    every qualified lead older than the ones they accept. Only ever tightens
    — loosening a legal deadline gate is a lawyer's call, not a heuristic's."""
    aged = [s for s in samples if s.decision == "qualified" and s.incident_age_days is not None]
    accepted_ages = [s.incident_age_days for s in aged if s.verdict == "accepted"]
    if not accepted_ages:
        return None
    oldest_accepted = max(accepted_ages)
    stale_rejects = [
        s for s in aged if s.verdict == "rejected" and s.incident_age_days > oldest_accepted
    ]
    if len(stale_rejects) < min_samples:
        return None
    # Round the oldest accepted age up to a whole month; never suggest a gate
    # the current rules already enforce or exceed.
    proposed = -(-max(oldest_accepted, 1) // SOL_ROUND_DAYS) * SOL_ROUND_DAYS
    if proposed >= rules.statute_of_limitations_days:
        return None
    return Suggestion(
        kind="tighten_sol_days",
        detail=(
            f"attorneys rejected {len(stale_rejects)} qualified leads older than "
            f"{oldest_accepted} days and accepted none — tighten the gate from "
            f"{rules.statute_of_limitations_days} to {proposed} days"
        ),
        evidence={
            "oldest_accepted_age_days": oldest_accepted,
            "stale_rejections": len(stale_rejects),
            "current_sol_days": rules.statute_of_limitations_days,
            "proposed_sol_days": proposed,
        },
    )


def analyze_reviews(
    samples: list[ReviewSample],
    rules: QualificationRules,
    min_samples: int = MIN_SAMPLES,
    threshold: float = AGREEMENT_THRESHOLD,
) -> TuningReport:
    """Compare attorney verdicts to engine decisions and propose rule edits."""
    matrix: dict[str, dict[str, int]] = {}
    for s in samples:
        matrix.setdefault(s.decision, {"accepted": 0, "rejected": 0})
        matrix[s.decision][s.verdict] = matrix[s.decision].get(s.verdict, 0) + 1
    agreement = (
        round(sum(1 for s in samples if _agreed(s)) / len(samples), 3) if samples else None
    )

    suggestions = _injury_suggestions(samples, rules, min_samples, threshold)
    sol = _sol_suggestion(samples, rules, min_samples)
    if sol:
        suggestions.append(sol)

    proposed: dict | None = None
    if suggestions:
        refer_out = [i.strip().lower() for i in rules.refer_out_injuries]
        sol_days = rules.statute_of_limitations_days
        for sug in suggestions:
            if sug.kind == "add_refer_out_injury":
                injury = sug.evidence["injury_type"]
                if injury not in refer_out:
                    refer_out.append(injury)
            elif sug.kind == "remove_refer_out_injury":
                refer_out = [i for i in refer_out if i != sug.evidence["injury_type"]]
            elif sug.kind == "tighten_sol_days":
                sol_days = sug.evidence["proposed_sol_days"]
        # Validate through the same model the config PUT enforces, so what we
        # propose is exactly what a human can apply.
        proposed = QualificationRules(
            statute_of_limitations_days=sol_days, refer_out_injuries=refer_out
        ).model_dump()

    return TuningReport(
        reviews=len(samples),
        agreement_rate=agreement,
        matrix=matrix,
        suggestions=suggestions,
        proposed_rules=proposed,
    )
