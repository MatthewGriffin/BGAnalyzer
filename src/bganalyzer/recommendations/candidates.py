"""Recommendation candidate generation and quantization."""

from decimal import ROUND_HALF_EVEN, Decimal

from bganalyzer.autotune.models import ATProfile, TunedDay
from bganalyzer.contracts.analysis import EligibilityResult, RecommendationCandidate
from bganalyzer.contracts.domain import RecommendationFamily


def generate_candidates(
    tuned_days: list[TunedDay], baseline: ATProfile, eligibility: EligibilityResult, policy: dict
) -> list[RecommendationCandidate]:
    """Generate recommendation candidates from tuned days."""
    # No verified engine or validated release policy exists in this build.
    return []


def _generate_basal_candidates(
    tuned_days: list[TunedDay], baseline: ATProfile, policy: dict
) -> list[RecommendationCandidate]:
    """Generate basal candidates."""
    candidates = []

    # Aggregate adjustments by hour
    hour_adjustments: dict[str, list[Decimal]] = {}
    for day in tuned_days:
        if day.excluded:
            continue
        for hour, adj in day.basal_adjustments:
            if hour not in hour_adjustments:
                hour_adjustments[hour] = []
            hour_adjustments[hour].append(adj)

    for hour, adjustments in hour_adjustments.items():
        if len(adjustments) < 5:  # Need 5+ days support
            continue

        # Median adjustment
        sorted_adj = sorted(adjustments)
        median_adj = sorted_adj[len(sorted_adj) // 2]

        baseline_rate = baseline.get_basal_at(hour)
        if baseline_rate <= 0:
            continue

        raw_value = baseline_rate + median_adj

        # Quantize to pump increment
        increment = Decimal(policy.get("basal_increment", "0.025"))
        quantized = _quantize_to_increment(raw_value, increment)

        if quantized == baseline_rate:
            continue

        # Check bounds
        max_change = baseline_rate * Decimal(policy.get("basal_max_change", "0.2"))
        if abs(quantized - baseline_rate) > max_change:
            continue

        candidate = RecommendationCandidate(
            family=RecommendationFamily.BASAL,
            segment=hour,
            baseline_value=baseline_rate,
            raw_value=raw_value,
            display_value=quantized,
            unit="U/h",
            direction="increase" if quantized > baseline_rate else "decrease",
            status="ready_for_review",
            reason_codes=[],
            sensitivity_min=min(adjustments),
            sensitivity_max=max(adjustments),
            segment_coverage_days=len(adjustments),
        )
        candidates.append(candidate)

    return candidates


def _generate_ic_candidates(
    tuned_days: list[TunedDay], baseline: ATProfile, policy: dict
) -> list[RecommendationCandidate]:
    """Generate IC (carb ratio) candidates."""
    candidates = []

    # Aggregate IC adjustments
    ic_adjustments = []
    for day in tuned_days:
        if day.excluded or day.ic_adjustment is None:
            continue
        ic_adjustments.append(day.ic_adjustment)

    if len(ic_adjustments) < 5:
        return candidates

    median_adj = sorted(ic_adjustments)[len(ic_adjustments) // 2]
    baseline_ic = baseline.get_carb_ratio_at("12:00")

    if baseline_ic <= 0:
        return candidates

    raw_value = baseline_ic + median_adj
    increment = Decimal(policy.get("ic_increment", "0.5"))
    quantized = _quantize_to_increment(raw_value, increment)

    if quantized == baseline_ic:
        return candidates

    max_change = baseline_ic * Decimal(policy.get("ic_max_change", "0.2"))
    if abs(quantized - baseline_ic) > max_change:
        return candidates

    candidate = RecommendationCandidate(
        family=RecommendationFamily.IC,
        segment="global",
        baseline_value=baseline_ic,
        raw_value=raw_value,
        display_value=quantized,
        unit="g/U",
        direction="decrease"
        if quantized < baseline_ic
        else "increase",  # Lower ratio = more insulin
        status="ready_for_review",
        reason_codes=[],
        sensitivity_min=min(ic_adjustments),
        sensitivity_max=max(ic_adjustments),
        segment_coverage_days=len(ic_adjustments),
    )
    candidates.append(candidate)

    return candidates


def _generate_isf_candidates(
    tuned_days: list[TunedDay], baseline: ATProfile, policy: dict
) -> list[RecommendationCandidate]:
    """Generate ISF candidates."""
    candidates = []

    isf_adjustments = []
    for day in tuned_days:
        if day.excluded or day.isf_adjustment is None:
            continue
        isf_adjustments.append(day.isf_adjustment)

    if len(isf_adjustments) < 5:
        return candidates

    median_adj = sorted(isf_adjustments)[len(isf_adjustments) // 2]
    baseline_isf = baseline.get_isf_at("12:00")

    if baseline_isf <= 0:
        return candidates

    raw_value = baseline_isf + median_adj
    increment = Decimal(policy.get("isf_increment", "1"))
    quantized = _quantize_to_increment(raw_value, increment)

    if quantized == baseline_isf:
        return candidates

    max_change = baseline_isf * Decimal(policy.get("isf_max_change", "0.2"))
    if abs(quantized - baseline_isf) > max_change:
        return candidates

    candidate = RecommendationCandidate(
        family=RecommendationFamily.ISF,
        segment="global",
        baseline_value=baseline_isf,
        raw_value=raw_value,
        display_value=quantized,
        unit="mg/dL/U",
        direction="decrease" if quantized < baseline_isf else "increase",
        status="ready_for_review",
        reason_codes=[],
        sensitivity_min=min(isf_adjustments),
        sensitivity_max=max(isf_adjustments),
        segment_coverage_days=len(isf_adjustments),
    )
    candidates.append(candidate)

    return candidates


def _quantize_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    """Quantize value to nearest increment."""
    if increment <= 0:
        return value
    # Round to nearest increment
    quantized = (value / increment).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN) * increment
    return quantized


def apply_quantization(
    candidates: list[RecommendationCandidate], policy: dict
) -> list[RecommendationCandidate]:
    """Apply quantization and bounds checking to all candidates."""
    result = []
    for cand in candidates:
        increment = Decimal(policy.get(f"{cand.family.value}_increment", "0.025"))
        quantized = _quantize_to_increment(cand.raw_value, increment)

        # Re-check bounds after quantization
        max_change_key = f"{cand.family.value}_max_change"
        max_change = cand.baseline_value * Decimal(policy.get(max_change_key, "0.2"))

        if abs(quantized - cand.baseline_value) > max_change:
            cand.status = "withheld"
            cand.reason_codes.append("EXCEEDS_MAX_CHANGE_AFTER_QUANTIZATION")
        elif quantized == cand.baseline_value:
            cand.status = "withheld"
            cand.reason_codes.append("NO_REPRESENTABLE_CHANGE")
        else:
            cand.display_value = quantized

        result.append(cand)

    return result
