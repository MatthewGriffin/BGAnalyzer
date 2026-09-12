"""Domain contracts - core data models for BGAnalyzer."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GlucoseUnit(str, Enum):
    """Glucose measurement units."""

    MGDL = "mg/dL"
    MMOL_L = "mmol/L"


class InsulinUnit(str, Enum):
    """Insulin measurement units."""

    UNITS = "units"
    UNITS_PER_HOUR = "units/hour"


class CarbUnit(str, Enum):
    """Carbohydrate measurement units."""

    GRAMS = "grams"


class Timezone(str, Enum):
    """Supported timezones."""

    EUROPE_LONDON = "Europe/London"
    UTC = "UTC"


class TreatmentKind(str, Enum):
    """Normalized treatment event kinds."""

    TEMP_BASAL = "temp_basal"
    BOLUS = "bolus"
    SMB = "smb"
    CARBS = "carbs"
    SUSPEND = "suspend"
    RESUME = "resume"
    PROFILE_SWITCH = "profile_switch"
    TEMP_TARGET = "temp_target"
    SITE_CHANGE = "site_change"
    INSULIN_CHANGE = "insulin_change"
    EXERCISE = "exercise"
    ANNOUNCEMENT = "announcement"
    BOLUS_WIZARD = "bolus_wizard"
    UNKNOWN = "unknown"


class DeliveryStatus(str, Enum):
    """Insulin delivery status."""

    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class ProfileSource(str, Enum):
    """Profile activation source."""

    AAPS_UPLOAD = "aaps_upload"
    USER_CONFIRMED = "user_confirmed"
    INFERRED = "inferred"
    EFFECTIVE_NOTE = "effective_note"
    PROFILE_SWITCH = "profile_switch"
    UNKNOWN = "unknown"


class AnalysisState(str, Enum):
    """Analysis run states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RecommendationState(str, Enum):
    """Recommendation lifecycle states."""

    DRAFT = "draft"
    WITHHELD = "withheld"
    READY_FOR_REVIEW = "ready_for_review"
    DISCUSSED = "discussed"
    DISMISSED = "dismissed"
    USER_REPORTS_APPLIED = "user_reports_applied"
    OBSERVED_PROFILE_CHANGE = "observed_profile_change"
    SUPERSEDED = "superseded"
    STALE = "stale"


class RecommendationFamily(str, Enum):
    """Recommendation parameter families."""

    BASAL = "basal"
    IC = "ic"
    ISF = "isf"


class EvidenceKind(str, Enum):
    """Evidence types."""

    GLUCOSE = "glucose"
    INSULIN = "insulin"
    CARBS = "carbs"
    PROFILE = "profile"
    PATTERN = "pattern"
    METRICS = "metrics"
    ANNOTATION = "annotation"
    EXCLUSION = "exclusion"
    CONTRADICTION = "contradiction"
    SENSITIVITY = "sensitivity"


class SyncCollection(str, Enum):
    """Nightscout collection names."""

    ENTRIES = "entries"
    TREATMENTS = "treatments"
    PROFILE = "profile"
    DEVICESTATUS = "devicestatus"
    FOOD = "food"
    STATUS = "status"


class BaseModelConfig(BaseModel):
    """Base configuration for all models."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        validate_assignment=True,
        use_enum_values=True,
        arbitrary_types_allowed=False,
    )


class TimestampMixin(BaseModel):
    """Mixin for UTC millisecond timestamps."""

    event_ms: int = Field(..., description="Event timestamp in UTC milliseconds")

    @field_validator("event_ms", mode="before")
    @classmethod
    def validate_timestamp(cls, v: Any) -> int:
        if isinstance(v, datetime):
            return int(v.timestamp() * 1000)
        if isinstance(v, (int, float)):
            return int(v)
        raise ValueError("Timestamp must be int, float, or datetime")


class SourceRefMixin(BaseModel):
    """Mixin for source references."""

    source_id: str = Field(..., description="Source identifier")
    remote_id: str = Field(..., description="Remote record identifier")
    revision_hash: str = Field(..., description="Content hash for revision tracking")


class GlucoseReading(BaseModel):
    """Normalized glucose reading."""

    id: UUID = Field(default_factory=uuid4)
    source_id: str
    remote_id: str
    revision_hash: str
    event_ms: int
    sgv_mgdl: float = Field(..., ge=0, le=1000)
    valid: bool = True
    quality_json: str = "{}"

    @property
    def sgv_mmol(self) -> float:
        """Convert to mmol/L."""
        return self.sgv_mgdl / 18.0


class TreatmentEvent(BaseModel):
    """Normalized treatment event."""

    id: UUID = Field(default_factory=uuid4)
    source_id: str
    remote_id: str
    revision_hash: str
    event_ms: int
    end_ms: Optional[int] = None
    kind: TreatmentKind
    insulin_u: Optional[Decimal] = None
    carbs_g: Optional[Decimal] = None
    rate_u_h: Optional[Decimal] = None
    percent: Optional[Decimal] = None
    delivery_status: DeliveryStatus = DeliveryStatus.UNKNOWN
    pump_event_key: Optional[str] = None
    valid: bool = True
    attributes_json: str = "{}"


class ProfileVersion(BaseModel):
    """Stored profile version."""

    id: UUID = Field(default_factory=uuid4)
    source_id: str
    remote_id: str
    revision_hash: str
    profile_name: str
    effective_from_ms: int
    timezone: str
    units_original: str
    normalized_json: str
    content_hash: str


class ProfileActivation(BaseModel):
    """Profile activation period."""

    id: UUID = Field(default_factory=uuid4)
    profile_version_id: UUID
    start_ms: int
    end_ms: Optional[int] = None
    percentage: Optional[Decimal] = None
    time_shift_minutes: int = 0
    origin: ProfileSource = ProfileSource.UNKNOWN
    evidence_json: str = "{}"
    certainty: str = "unknown"


class DeviceStatusRecord(BaseModel):
    """Device status record."""

    id: UUID = Field(default_factory=uuid4)
    source_id: str
    remote_id: str
    revision_hash: str
    event_ms: int
    configuration_json: str = "{}"
    loop_json: str = "{}"
    quality_json: str = "{}"


class Annotation(BaseModel):
    """Local user annotation."""

    id: UUID = Field(default_factory=uuid4)
    start_ms: int
    end_ms: Optional[int] = None
    kind: str
    text: str
    attributes_json: str = "{}"
    created_ms: int = Field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    updated_ms: int = Field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    deleted_ms: Optional[int] = None


class DataRevision(BaseModel):
    """Data revision checkpoint."""

    revision: int
    source_id: Optional[str] = None
    committed_ms: int
    affected_start_ms: int
    affected_end_ms: int
    reason: str


class SyncStateRecord(BaseModel):
    """Sync state for a collection."""

    source_id: str
    collection: SyncCollection
    cursor_json: str = "{}"
    backfill_start_ms: Optional[int] = None
    backfill_end_ms: Optional[int] = None
    last_success_ms: Optional[int] = None
    last_error_code: Optional[str] = None


class SourceRecord(BaseModel):
    """Data source configuration."""

    id: str
    origin: str
    api_mode: str = "v1"
    server_version: Optional[str] = None
    capabilities_json: str = "{}"
    created_ms: int = Field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
