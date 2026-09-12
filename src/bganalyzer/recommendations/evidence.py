"""Evidence bundle construction for recommendations."""

from uuid import UUID

from bganalyzer.autotune.models import AutotuneRun
from bganalyzer.contracts.analysis import EvidenceBundle


def build_evidence_bundle(
    run: AutotuneRun,
    candidates: list,
    eligibility: dict,
    exclusions: list,
    contradictions: list,
    sensitivity_reruns: list,
    annotations: list,
    limitations: list,
) -> EvidenceBundle:
    """Build complete evidence bundle for a recommendation run."""
    import hashlib
    import json

    # Create input hash
    input_data = {
        "tuned_days": len(run.tuned_days),
        "baseline_hash": run.baseline_profile.__dict__
        if hasattr(run.baseline_profile, "__dict__")
        else str(run.baseline_profile),
    }
    input_hash = hashlib.sha256(json.dumps(input_data, sort_keys=True).encode()).hexdigest()[:16]

    # Build candidate objects
    candidate_objects = []
    for cand in candidates:
        candidate_objects.append(
            {
                "id": str(cand.id),
                "family": cand.family.value,
                "segment": cand.segment,
                "baseline_value": str(cand.baseline_value),
                "raw_value": str(cand.raw_value),
                "display_value": str(cand.display_value),
                "unit": cand.unit,
                "direction": cand.direction,
                "status": cand.status,
                "reason_codes": cand.reason_codes,
            }
        )

    # Build contributions
    contributions = []
    for day in run.tuned_days:
        if day.excluded:
            continue
        for hour, adj in day.basal_adjustments:
            contributions.append(
                {
                    "candidate_ids": [],
                    "source_refs": [],
                    "interval_start_ms": day.date,
                    "interval_end_ms": day.date + 86400000,
                    "category": "basal_adjustment",
                    "input_values": {"hour": hour, "adjustment": str(adj)},
                    "intermediate_values": {},
                    "formula_or_reference_step": "median_of_daily_adjustments",
                    "output_contribution": {"adjustment": str(adj)},
                }
            )

    return EvidenceBundle(
        run_id=UUID("00000000-0000-0000-0000-000000000000"),  # Would be actual run ID
        input_hash=input_hash,
        data_revision=0,
        algorithm_version="autotune-v1",
        policy_version="policy-v1",
        analysis_window_start_ms=min(d.date for d in run.tuned_days) if run.tuned_days else 0,
        analysis_window_end_ms=max(d.date for d in run.tuned_days) + 86400000
        if run.tuned_days
        else 0,
        timezone="UTC",
        baseline_profile_hash="",
        activation_evidence_json="{}",
        metrics=[],
        candidates=candidate_objects,
        contributions=contributions,
        exclusions=exclusions,
        contradictions=contradictions,
        sensitivity_reruns=sensitivity_reruns,
        annotations=annotations,
        limitations=limitations,
    )


def select_evidence_for_explanation(
    bundle: EvidenceBundle, max_supporting: int = 20, max_contradictory: int = 10
) -> EvidenceBundle:
    """Select representative evidence for explanation generation."""
    # Return bundle with limited evidence for token budget
    return EvidenceBundle(
        run_id=bundle.run_id,
        input_hash=bundle.input_hash,
        data_revision=bundle.data_revision,
        algorithm_version=bundle.algorithm_version,
        policy_version=bundle.policy_version,
        analysis_window_start_ms=bundle.analysis_window_start_ms,
        analysis_window_end_ms=bundle.analysis_window_end_ms,
        timezone=bundle.timezone,
        baseline_profile_hash=bundle.baseline_profile_hash,
        activation_evidence_json=bundle.activation_evidence_json,
        metrics=bundle.metrics,
        candidates=bundle.candidates[:max_supporting],
        contributions=bundle.contributions[:max_supporting],
        exclusions=bundle.exclusions,
        contradictions=bundle.contradictions[:max_contradictory],
        sensitivity_reruns=bundle.sensitivity_reruns,
        annotations=bundle.annotations,
        limitations=bundle.limitations,
    )
