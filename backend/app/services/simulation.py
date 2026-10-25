"""Aggregate future-case scenario simulation (ILLUSTRATIVE).

Estimates how often a procedural issue might recur for a *case type* under
different interventions, using the observed recurrence in the selected scope
and illustrative intervention effects. It does not predict any individual's
intent or behaviour, and synthetic demo data cannot demonstrate accuracy.
"""

import random
from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Finding, MistakeRule, ServiceCase

SCENARIO_CODE = "aggregate_recurrence_v0"
DRAWS = 4000

# Illustrative relative-risk reductions (low, high). Not validated effect sizes.
INTERVENTIONS: dict[str, dict] = {
    "none": {"reduction": (0.0, 0.0), "driver": None},
    "coaching": {"reduction": (0.10, 0.35), "driver": "individual_action"},
    "job_aid": {"reduction": (0.05, 0.25), "driver": "individual_action"},
    "policy_clarification": {"reduction": (0.05, 0.45), "driver": "policy_ambiguity"},
    "system_fix": {"reduction": (0.10, 0.60), "driver": "system_issue"},
    "process_redesign": {"reduction": (0.05, 0.50), "driver": "process_design"},
}

LIMITATIONS = [
    "illustrative_only",
    "synthetic_data_no_accuracy_claim",
    "aggregate_not_individual",
    "effects_not_validated",
    "case_mix_not_fully_adjusted",
    "model_in_development",
]


def _quantile(sorted_values: list[float], q: float) -> float:
    idx = min(len(sorted_values) - 1, max(0, int(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


def _band(rate: float) -> str:
    if rate < 0.05:
        return "low"
    if rate < 0.12:
        return "moderate"
    return "elevated"


def run(
    db: Session,
    *,
    case_type: str,
    interventions: list[str],
    org_unit_ids: set[str] | None,
    horizon_days: int = 90,
    lookback_days: int = 180,
) -> dict:
    since = utcnow() - timedelta(days=lookback_days)
    case_stmt = select(ServiceCase.id).where(ServiceCase.case_type == case_type, ServiceCase.occurred_at >= since)
    if org_unit_ids is not None:
        case_stmt = case_stmt.where(ServiceCase.org_unit_id.in_(org_unit_ids))
    case_ids = list(db.scalars(case_stmt))
    n_cases = len(case_ids)

    rows = []
    if case_ids:
        rows = db.execute(
            select(Finding.contributing_factor, MistakeRule.category)
            .join(MistakeRule, MistakeRule.id == Finding.rule_id)
            .where(Finding.case_id.in_(case_ids), Finding.status.in_(("CONFIRMED", "AMENDED")))
        ).all()
    k = len(rows)
    factors = Counter(r.contributing_factor for r in rows)
    factor_share = {f: round(c / k, 3) for f, c in factors.most_common()} if k else {}

    # Beta(1 + k, 1 + n - k) posterior for the issue rate per case (uniform prior).
    rng = random.Random(f"{case_type}:{n_cases}:{k}")
    base_draws = [rng.betavariate(1 + k, 1 + n_cases - k) for _ in range(DRAWS)]

    options = []
    for code in ["none", *[i for i in interventions if i != "none"]]:
        spec = INTERVENTIONS[code]
        low, high = spec["reduction"]
        # An intervention only acts on the share of findings driven by the factor it addresses.
        share = 1.0 if spec["driver"] is None else factor_share.get(spec["driver"], 0.0)
        draws = sorted(b * (1 - rng.uniform(low, high) * share) for b in base_draws)
        median = _quantile(draws, 0.5)
        options.append(
            {
                "intervention": code,
                "estimated_rate": round(median, 4),
                "interval_90": [round(_quantile(draws, 0.05), 4), round(_quantile(draws, 0.95), 4)],
                "risk_band": _band(median),
                "addressable_share": round(share, 3),
                "expected_cases_per_1000": round(median * 1000, 1),
            }
        )

    best = min(options[1:], key=lambda o: o["estimated_rate"], default=None)
    warnings = []
    if n_cases < 30:
        warnings.append("small_sample")
    if k < 5:
        warnings.append("few_confirmed_findings")

    return {
        "scenario_code": SCENARIO_CODE,
        "illustrative": True,
        "case_type": case_type,
        "horizon_days": horizon_days,
        "lookback_days": lookback_days,
        "sample": {"cases": n_cases, "confirmed_findings": k},
        "contributing_factors": factor_share,
        "options": options,
        "recommended_next_step": ({"intervention": best["intervention"], "note": "for_human_review"} if best else None),
        "warnings": warnings,
        "limitations": LIMITATIONS,
    }
