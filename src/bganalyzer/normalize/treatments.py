"""Treatment normalization utilities."""

from decimal import Decimal
from typing import Optional

from bganalyzer.contracts.domain import TreatmentKind


def normalize_insulin(value: Optional[float]) -> Optional[Decimal]:
    """Normalize insulin value to Decimal."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def normalize_carbs(value: Optional[float]) -> Optional[Decimal]:
    """Normalize carbs value to Decimal."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.1"))


def normalize_rate(value: Optional[float]) -> Optional[Decimal]:
    """Normalize basal rate to Decimal."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def normalize_percent(value: Optional[float]) -> Optional[Decimal]:
    """Normalize percentage to Decimal."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def map_event_type(event_type: str, is_smb: Optional[bool] = None) -> TreatmentKind:
    """Map Nightscout eventType to TreatmentKind."""
    if is_smb:
        return TreatmentKind.SMB

    mapping = {
        "Temp Basal": TreatmentKind.TEMP_BASAL,
        "Meal Bolus": TreatmentKind.BOLUS,
        "Correction Bolus": TreatmentKind.BOLUS,
        "Bolus Wizard": TreatmentKind.BOLUS_WIZARD,
        "Carb Correction": TreatmentKind.CARBS,
        "Suspend": TreatmentKind.SUSPEND,
        "Resume": TreatmentKind.RESUME,
        "Profile Switch": TreatmentKind.PROFILE_SWITCH,
        "Temporary Target": TreatmentKind.TEMP_TARGET,
        "Site Change": TreatmentKind.SITE_CHANGE,
        "Insulin Change": TreatmentKind.INSULIN_CHANGE,
        "Exercise": TreatmentKind.EXERCISE,
        "Announcement": TreatmentKind.ANNOUNCEMENT,
    }

    return mapping.get(event_type, TreatmentKind.UNKNOWN)


def is_delivered_bolus(event_type: str, is_smb: Optional[bool] = None) -> bool:
    """Determine if event represents delivered insulin."""
    if is_smb:
        return True
    delivered_types = {"Meal Bolus", "Correction Bolus", "Temp Basal"}
    return event_type in delivered_types


def is_calculator_event(event_type: str) -> bool:
    """Determine if event is a calculator proposal only."""
    return event_type == "Bolus Wizard"


def is_temp_basal(event_type: str) -> bool:
    """Determine if event is a temp basal."""
    return event_type == "Temp Basal"
