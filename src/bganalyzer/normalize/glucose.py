"""Glucose normalization utilities."""

from typing import Optional

from bganalyzer.contracts.domain import GlucoseUnit

MGDL_TO_MMOL = 18.0


def mgdl_to_mmol(mgdl: float) -> float:
    """Convert mg/dL to mmol/L."""
    return mgdl / MGDL_TO_MMOL


def mmol_to_mgdl(mmol: float) -> float:
    """Convert mmol/L to mg/dL."""
    return mmol * MGDL_TO_MMOL


def convert_glucose(value: float, from_unit: GlucoseUnit, to_unit: GlucoseUnit) -> float:
    """Convert glucose value between units."""
    if from_unit == to_unit:
        return value
    if from_unit == GlucoseUnit.MGDL and to_unit == GlucoseUnit.MMOL_L:
        return mgdl_to_mmol(value)
    if from_unit == GlucoseUnit.MMOL_L and to_unit == GlucoseUnit.MGDL:
        return mmol_to_mgdl(value)
    raise ValueError(f"Unknown unit conversion: {from_unit} -> {to_unit}")


def validate_glucose_mgdl(value: float) -> bool:
    """Validate glucose value in mg/dL is within physiological range."""
    return 0 < value <= 1000


def validate_glucose_mmol(value: float) -> bool:
    """Validate glucose value in mmol/L is within physiological range."""
    return 0 < value <= 55.5


def is_valid_sgv(sgv: Optional[int]) -> bool:
    """Check if SGV value is valid."""
    return sgv is not None and sgv > 0


def classify_glucose_mgdl(
    value: float, low: float = 70, high: float = 180, very_low: float = 54, very_high: float = 250
) -> str:
    """Classify glucose value into range band."""
    if value < very_low:
        return "very_low"
    elif value < low:
        return "low"
    elif value <= high:
        return "in_range"
    elif value <= very_high:
        return "high"
    else:
        return "very_high"
