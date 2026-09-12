"""Comparison and before/after analysis."""

from dataclasses import dataclass

from bganalyzer.contracts.analysis import TimeInRangeMetrics
from bganalyzer.contracts.domain import GlucoseReading


@dataclass
class ComparisonResult:
    """Result of before/after comparison."""

    before_metrics: TimeInRangeMetrics
    after_metrics: TimeInRangeMetrics
    tir_change: float
    tbr_change: float
    tar_change: float
    mean_change_mgdl: float
    cv_change: float
    coverage_before: float
    coverage_after: float
    notes: list[str]


def compare_periods(
    before_glucose: list[GlucoseReading],
    after_glucose: list[GlucoseReading],
    before_start: int,
    before_end: int,
    after_start: int,
    after_end: int,
    bands,
) -> ComparisonResult:
    """Compare two glucose periods."""
    from bganalyzer.analytics.metrics import calculate_tir_metrics

    before = calculate_tir_metrics(before_glucose, before_start, before_end, bands)
    after = calculate_tir_metrics(after_glucose, after_start, after_end, bands)

    notes = []

    if before.coverage_percent < 70:
        notes.append(f"Before period coverage low: {before.coverage_percent:.1f}%")
    if after.coverage_percent < 70:
        notes.append(f"After period coverage low: {after.coverage_percent:.1f}%")

    tir_before = (
        before.in_range_minutes / before.covered_minutes * 100 if before.covered_minutes > 0 else 0
    )
    tir_after = (
        after.in_range_minutes / after.covered_minutes * 100 if after.covered_minutes > 0 else 0
    )

    tbr_before = (
        (before.very_low_minutes + before.low_minutes) / before.covered_minutes * 100
        if before.covered_minutes > 0
        else 0
    )
    tbr_after = (
        (after.very_low_minutes + after.low_minutes) / after.covered_minutes * 100
        if after.covered_minutes > 0
        else 0
    )

    tar_before = (
        (after.high_minutes + after.very_high_minutes) / before.covered_minutes * 100
        if before.covered_minutes > 0
        else 0
    )
    tar_after = (
        (after.high_minutes + after.very_high_minutes) / after.covered_minutes * 100
        if after.covered_minutes > 0
        else 0
    )

    return ComparisonResult(
        before_metrics=before,
        after_metrics=after,
        tir_change=tir_after - tir_before,
        tbr_change=tbr_after - tbr_before,
        tar_change=tar_after - tar_before,
        mean_change_mgdl=(after.mean_mgdl or 0) - (before.mean_mgdl or 0),
        cv_change=(after.cv_percent or 0) - (before.cv_percent or 0),
        coverage_before=before.coverage_percent,
        coverage_after=after.coverage_percent,
        notes=notes,
    )


def compare_profiles(before_profile: dict, after_profile: dict) -> dict:
    """Compare two profile configurations."""
    changes = {
        "basal_changes": [],
        "ic_changes": [],
        "isf_changes": [],
        "target_changes": [],
        "dia_change": None,
    }

    return changes
