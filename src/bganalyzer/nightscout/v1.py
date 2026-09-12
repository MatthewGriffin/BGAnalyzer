"""Nightscout v1 API models and utilities."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class V1Status(BaseModel):
    """Nightscout v1 status response."""

    model_config = ConfigDict(extra="allow")
    version: str
    name: str
    apiEnabled: bool = True
    enableAutotune: bool = False
    enableBolusCalc: bool = False
    features: str = ""


class V1Entry(BaseModel):
    """Nightscout v1 glucose entry."""

    model_config = ConfigDict(extra="allow")
    _id: str
    sgv: Optional[int] = None
    date: int
    dateString: str
    type: str = "sgv"
    device: Optional[str] = None
    direction: Optional[str] = None
    filtered: Optional[float] = None
    unfiltered: Optional[float] = None
    rssi: Optional[int] = None
    noise: Optional[int] = None


class V1Treatment(BaseModel):
    """Nightscout v1 treatment record."""

    model_config = ConfigDict(extra="allow")
    _id: str
    eventType: str
    created_at: str
    enteredBy: Optional[str] = None
    insulin: Optional[float] = None
    carbs: Optional[float] = None
    carbsInput: Optional[float] = None
    fat: Optional[float] = None
    protein: Optional[float] = None
    duration: Optional[int] = None
    absolute: Optional[float] = None
    rate: Optional[float] = None
    percent: Optional[float] = None
    isSMB: Optional[bool] = None
    bolusCalculatorResult: Optional[dict] = None
    notes: Optional[str] = None
    pumpId: Optional[str] = None
    endId: Optional[str] = None


class V1Profile(BaseModel):
    """Nightscout v1 profile store."""

    model_config = ConfigDict(extra="allow")
    _id: str
    stores: list[dict]
    defaultProfile: Optional[str] = None
    startDate: Optional[str] = None
    units: str = "mg/dL"
    timezone: str = "UTC"


class V1DeviceStatus(BaseModel):
    """Nightscout v1 device status."""

    model_config = ConfigDict(extra="allow")
    _id: str
    created_at: str
    device: Optional[str] = None
    openaps: Optional[dict] = None
    loop: Optional[dict] = None
    pump: Optional[dict] = None
    iob: Optional[float] = None
    cob: Optional[float] = None
    activity: Optional[float] = None
    sensitivityRatio: Optional[float] = None
    basaliob: Optional[float] = None
    bolusiob: Optional[float] = None
    netbasalinsulin: Optional[float] = None
    bolusinsulin: Optional[float] = None


class V1Food(BaseModel):
    """Nightscout v1 food catalog entry."""

    model_config = ConfigDict(extra="allow")
    _id: str
    name: str
    carbs: float
    fat: Optional[float] = None
    protein: Optional[float] = None
    servingSize: Optional[float] = None
    units: str = "grams"


V1_COLLECTION_MODELS = {
    "entries": V1Entry,
    "treatments": V1Treatment,
    "profile": V1Profile,
    "devicestatus": V1DeviceStatus,
    "food": V1Food,
}


def parse_v1_collection(collection: str, data: list[dict]) -> list[BaseModel]:
    """Parse v1 collection data into typed models."""
    model = V1_COLLECTION_MODELS.get(collection)
    if model is None:
        return [BaseModel.model_validate(item) for item in data]
    return [model.model_validate(item) for item in data]


def validate_v1_entry(entry: dict) -> bool:
    """Validate required fields for v1 entry."""
    return all(key in entry for key in ("_id", "date", "dateString", "type"))


def validate_v1_treatment(treatment: dict) -> bool:
    """Validate required fields for v1 treatment."""
    return all(key in treatment for key in ("_id", "eventType", "created_at"))


def validate_v1_profile(profile: dict) -> bool:
    """Validate required fields for v1 profile."""
    return "_id" in profile and "stores" in profile
