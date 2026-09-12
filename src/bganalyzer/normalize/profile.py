"""Profile normalization utilities."""

import json
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class BasalSchedule(BaseModel):
    """Basal rate schedule entry."""

    time: str  # HH:MM format
    rate: Decimal


class CarbRatioSchedule(BaseModel):
    """Carb ratio schedule entry."""

    time: str
    ratio: Decimal


class InsulinSensitivitySchedule(BaseModel):
    """Insulin sensitivity schedule entry."""

    time: str
    sensitivity: Decimal


class TargetRangeSchedule(BaseModel):
    """Target range schedule entry."""

    time: str
    low: Decimal
    high: Decimal


class NormalizedProfile(BaseModel):
    """Normalized profile structure."""

    model_config = ConfigDict(extra="forbid")
    basal: list[BasalSchedule] = []
    carb_ratio: list[CarbRatioSchedule] = []
    insulin_sensitivity: list[InsulinSensitivitySchedule] = []
    target_range: list[TargetRangeSchedule] = []
    dia_hours: Decimal = Decimal("5")
    timezone: str = "UTC"
    units: str = "mg/dL"


def parse_aaps_profile(store: dict) -> NormalizedProfile:
    """Parse AAPS profile store into normalized format."""
    profile = NormalizedProfile()

    # Parse basal
    for entry in store.get("basal", []):
        if "time" in entry and "value" in entry:
            profile.basal.append(
                BasalSchedule(time=entry["time"], rate=Decimal(str(entry["value"])))
            )

    # Parse carb ratio
    for entry in store.get("carbratio", []):
        if "time" in entry and "value" in entry:
            profile.carb_ratio.append(
                CarbRatioSchedule(time=entry["time"], ratio=Decimal(str(entry["value"])))
            )

    # Parse insulin sensitivity
    for entry in store.get("sens", []):
        if "time" in entry and "value" in entry:
            profile.insulin_sensitivity.append(
                InsulinSensitivitySchedule(
                    time=entry["time"], sensitivity=Decimal(str(entry["value"]))
                )
            )

    # Parse targets
    for entry in store.get("targets", []):
        if "time" in entry and "low" in entry and "high" in entry:
            profile.target_range.append(
                TargetRangeSchedule(
                    time=entry["time"],
                    low=Decimal(str(entry["low"])),
                    high=Decimal(str(entry["high"])),
                )
            )

    # Parse DIA
    if "dia" in store:
        profile.dia_hours = Decimal(str(store["dia"]))

    profile.timezone = store.get("timezone", "UTC")
    profile.units = store.get("units", "mg/dL")

    return profile


def serialize_profile(profile: NormalizedProfile) -> str:
    """Serialize normalized profile to JSON."""
    data = {
        "basal": [{"time": b.time, "value": str(b.rate)} for b in profile.basal],
        "carbratio": [{"time": c.time, "value": str(c.ratio)} for c in profile.carb_ratio],
        "sens": [
            {"time": s.time, "value": str(s.sensitivity)} for s in profile.insulin_sensitivity
        ],
        "targets": [
            {"time": t.time, "low": str(t.low), "high": str(t.high)} for t in profile.target_range
        ],
        "dia": str(profile.dia_hours),
        "timezone": profile.timezone,
        "units": profile.units,
    }
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def get_basal_at(profile: NormalizedProfile, time_str: str) -> Decimal:
    """Get basal rate at specific time (HH:MM)."""
    for i in range(len(profile.basal) - 1, -1, -1):
        if profile.basal[i].time <= time_str:
            return profile.basal[i].rate
    return profile.basal[0].rate if profile.basal else Decimal("0")


def get_carb_ratio_at(profile: NormalizedProfile, time_str: str) -> Decimal:
    """Get carb ratio at specific time."""
    for i in range(len(profile.carb_ratio) - 1, -1, -1):
        if profile.carb_ratio[i].time <= time_str:
            return profile.carb_ratio[i].ratio
    return profile.carb_ratio[0].ratio if profile.carb_ratio else Decimal("10")


def get_isf_at(profile: NormalizedProfile, time_str: str) -> Decimal:
    """Get insulin sensitivity at specific time."""
    for i in range(len(profile.insulin_sensitivity) - 1, -1, -1):
        if profile.insulin_sensitivity[i].time <= time_str:
            return profile.insulin_sensitivity[i].sensitivity
    return (
        profile.insulin_sensitivity[0].sensitivity if profile.insulin_sensitivity else Decimal("50")
    )


def get_target_at(profile: NormalizedProfile, time_str: str) -> tuple[Decimal, Decimal]:
    """Get target range at specific time."""
    for i in range(len(profile.target_range) - 1, -1, -1):
        if profile.target_range[i].time <= time_str:
            return (profile.target_range[i].low, profile.target_range[i].high)
    if profile.target_range:
        return (profile.target_range[0].low, profile.target_range[0].high)
    return (Decimal("70"), Decimal("180"))
