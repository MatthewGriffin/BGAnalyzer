"""Data quality assessment."""

from dataclasses import dataclass

from bganalyzer.contracts.domain import DeviceStatusRecord, GlucoseReading, TreatmentEvent


@dataclass
class QualityReport:
    """Data quality report for a time range."""

    glucose_coverage_percent: float = 0.0
    glucose_gaps: list[tuple[int, int]] = None
    treatment_gaps: list[tuple[int, int]] = None
    missing_profile_periods: list[tuple[int, int]] = None
    unknown_event_types: list[str] = None
    ambiguous_units: bool = False
    clock_skew_ms: int = 0
    stale_data: bool = False

    def __post_init__(self):
        if self.glucose_gaps is None:
            self.glucose_gaps = []
        if self.treatment_gaps is None:
            self.treatment_gaps = []
        if self.missing_profile_periods is None:
            self.missing_profile_periods = []
        if self.unknown_event_types is None:
            self.unknown_event_types = []


def assess_glucose_quality(
    glucose: list[GlucoseReading], start_ms: int, end_ms: int, max_gap_minutes: int = 5
) -> QualityReport:
    """Assess glucose data quality."""
    if not glucose:
        return QualityReport(
            glucose_coverage_percent=0.0,
            glucose_gaps=[(start_ms, end_ms)],
        )

    valid_glucose = [g for g in glucose if g.valid]
    valid_glucose.sort(key=lambda g: g.event_ms)

    total_duration = end_ms - start_ms
    covered_duration = 0
    gaps = []

    if not valid_glucose:
        return QualityReport(
            glucose_coverage_percent=0.0,
            glucose_gaps=[(start_ms, end_ms)],
        )

    prev_end = start_ms
    for g in valid_glucose:
        if g.event_ms > prev_end + max_gap_minutes * 60 * 1000:
            gaps.append((prev_end, g.event_ms))
        prev_end = g.event_ms + 5 * 60 * 1000

    if prev_end < end_ms:
        gaps.append((prev_end, end_ms))

    for gap_start, gap_end in gaps:
        covered_duration += gap_end - gap_start

    coverage = (
        max(0, (total_duration - covered_duration) / total_duration * 100)
        if total_duration > 0
        else 0
    )

    return QualityReport(
        glucose_coverage_percent=coverage,
        glucose_gaps=gaps,
    )


def assess_treatment_quality(
    treatments: list[TreatmentEvent], start_ms: int, end_ms: int
) -> QualityReport:
    """Assess treatment data quality."""
    unknown_types = set()
    for tx in treatments:
        if tx.kind.name == "UNKNOWN":
            unknown_types.add(tx.remote_id)

    return QualityReport(
        treatment_gaps=[],
        unknown_event_types=list(unknown_types),
    )


def assess_device_quality(devicestatus: list[DeviceStatusRecord]) -> QualityReport:
    """Assess device status quality."""
    has_config = any(d.configuration_json != "{}" for d in devicestatus)
    has_loop = any(d.loop_json != "{}" for d in devicestatus)
    has_iob = any("iob" in d.loop_json for d in devicestatus)

    return QualityReport(
        ambiguous_units=False,
    )


def combine_quality_reports(*reports: QualityReport) -> QualityReport:
    """Combine multiple quality reports."""
    combined = QualityReport()
    for report in reports:
        combined.glucose_gaps.extend(report.glucose_gaps)
        combined.treatment_gaps.extend(report.treatment_gaps)
        combined.missing_profile_periods.extend(report.missing_profile_periods)
        combined.unknown_event_types.extend(report.unknown_event_types)
        combined.ambiguous_units = combined.ambiguous_units or report.ambiguous_units
        combined.clock_skew_ms = max(combined.clock_skew_ms, report.clock_skew_ms)
        combined.stale_data = combined.stale_data or report.stale_data
    return combined
