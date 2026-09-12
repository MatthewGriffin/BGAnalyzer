"""Analysis contracts - models for analytical results and recommendations."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from bganalyzer.contracts.domain import (
    EvidenceKind,
    RecommendationFamily,
    RecommendationState,
)


class MetricBand(BaseModel):
    """Glucose metric band definition."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    name: str
    low_mgdl: Optional[float] = None
    high_mgdl: Optional[float] = None
    inclusive_low: bool = True
    inclusive_high: bool = False


class TimeInRangeMetrics(BaseModel):
    """Time in range metrics for a period."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    period_start_ms: int
    period_end_ms: int
    total_readings: int
    covered_minutes: float
    total_minutes: float
    coverage_percent: float
    very_low_minutes: float = 0
    low_minutes: float = 0
    in_range_minutes: float = 0
    high_minutes: float = 0
    very_high_minutes: float = 0
    mean_mgdl: Optional[float] = None
    sd_mgdl: Optional[float] = None
    cv_percent: Optional[float] = None
    gmi_percent: Optional[float] = None


class DailyPercentileOverlay(BaseModel):
    """Daily percentile overlay data."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    bin_start_minutes: int
    p5: Optional[float] = None
    p25: Optional[float] = None
    p50: Optional[float] = None
    p75: Optional[float] = None
    p95: Optional[float] = None
    sample_count: int = 0
    days_contributing: int = 0


class MealEpisode(BaseModel):
    """Meal episode with glucose response."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    start_ms: int
    end_ms: int
    carbs_g: Optional[Decimal] = None
    carbs_source: str = "treatment"
    notes: str = ""
    premeal_median_mgdl: Optional[float] = None
    peak_mgdl: Optional[float] = None
    peak_time_minutes: Optional[int] = None
    glucose_2h_mgdl: Optional[float] = None
    glucose_4h_mgdl: Optional[float] = None
    time_above_range_minutes: float = 0
    insulin_before_bolus_u: Optional[Decimal] = None
    insulin_after_bolus_u: Optional[Decimal] = None
    temp_basal_u: Optional[Decimal] = None
    confounders: list[str] = Field(default_factory=list)
    completeness: str = "unknown"


class PatternFinding(BaseModel):
    """Detected pattern finding."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    rule_version: str
    rule_name: str
    description: str
    severity: str
    contributing_days: list[int] = Field(default_factory=list)
    conflicting_days: list[int] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    exclusion_codes: list[str] = Field(default_factory=list)
    metadata_json: str = "{}"


class AnalysisRun(BaseModel):
    """Analysis run record."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    data_revision: int
    source_id: Optional[str] = None
    start_ms: int
    end_ms: Optional[int] = None
    profile_hash: str
    algorithm_version: str
    policy_hash: str
    input_hash: str
    state: str = "pending"
    metrics_json: str = "{}"
    created_ms: int = Field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    error_code: Optional[str] = None


class EvidenceRecord(BaseModel):
    """Evidence record for a recommendation."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    kind: EvidenceKind
    start_ms: int
    end_ms: int
    payload_json: str
    source_refs_json: str
    content_hash: str


class ContributionRecord(BaseModel):
    """Algorithmic contribution record."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    candidate_ids: list[UUID] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    interval_start_ms: int
    interval_end_ms: int
    category: str
    input_values_json: str
    intermediate_values_json: str
    formula_or_reference_step: str
    output_contribution_json: str


class ExclusionRecord(BaseModel):
    """Exclusion record with reason."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    source_refs: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    interval_start_ms: Optional[int] = None
    interval_end_ms: Optional[int] = None


class ContradictionRecord(BaseModel):
    """Contradictory evidence record."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    candidate_id: UUID
    episode_summary: str
    source_refs: list[str] = Field(default_factory=list)
    reason: str


class SensitivityRerunRecord(BaseModel):
    """Leave-one-day-out sensitivity rerun."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    excluded_day_ms: int
    candidate_id: UUID
    baseline_value: Decimal
    full_run_value: Decimal
    rerun_value: Decimal
    direction_same: bool
    valid: bool


class RecommendationCandidate(BaseModel):
    """Individual parameter recommendation candidate."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    family: RecommendationFamily
    segment: Optional[str] = None
    baseline_value: Decimal
    raw_value: Decimal
    display_value: Decimal
    unit: str
    direction: str
    status: RecommendationState
    reason_codes: list[str] = Field(default_factory=list)
    sensitivity_min: Optional[Decimal] = None
    sensitivity_max: Optional[Decimal] = None
    segment_coverage_days: int = 0


class RecommendationRecord(BaseModel):
    """Full recommendation record."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    family: RecommendationFamily
    state: RecommendationState
    baseline_profile_hash: str
    candidate_json: str
    evidence_ids_json: str
    eligibility_json: str
    created_ms: int = Field(default_factory=lambda: int(datetime.now().timestamp() * 1000))


class RecommendationEvent(BaseModel):
    """Recommendation lifecycle event."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    recommendation_id: UUID
    event_ms: int
    event_type: str
    payload_json: str


class EligibilityResult(BaseModel):
    """Eligibility check result."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    status: str
    reason_codes: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    supported_families: list[RecommendationFamily] = Field(default_factory=list)
    details_json: str = "{}"


class EvidenceBundle(BaseModel):
    """Complete evidence bundle for explanation generation."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    run_id: UUID
    input_hash: str
    data_revision: int
    algorithm_version: str
    policy_version: str
    analysis_window_start_ms: int
    analysis_window_end_ms: int
    timezone: str
    baseline_profile_hash: str
    activation_evidence_json: str
    metrics: list[dict] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    contributions: list[dict] = Field(default_factory=list)
    exclusions: list[dict] = Field(default_factory=list)
    contradictions: list[dict] = Field(default_factory=list)
    sensitivity_reruns: list[dict] = Field(default_factory=list)
    annotations: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ExplanationRequest(BaseModel):
    """Request for local AI explanation."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    evidence_bundle: EvidenceBundle
    model_hash: str
    prompt_version: str


class ExplanationResponse(BaseModel):
    """Structured explanation response from local AI."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    summary: str
    observations: list[dict] = Field(default_factory=list)
    alternatives: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence_ids_referenced: list[UUID] = Field(default_factory=list)


class ExplanationRecord(BaseModel):
    """Stored explanation record."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    evidence_hash: str
    model_hash: str
    prompt_version: str
    validated_json: str
    status: str
    created_ms: int = Field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
