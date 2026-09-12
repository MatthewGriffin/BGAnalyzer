"""AAPS Autotune data models - ported from ATProfile, BGDatum, CRDatum, PreppedGlucose, etc.

Upstream commit: 1393357107a2b27ba153df31d64e745efd771ef2
Reference files: 
- plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/data/ATProfile.kt
- plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/data/BGDatum.kt
- plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/data/CRDatum.kt
- plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/data/PreppedGlucose.kt
- plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/data/DiaDeviation.kt
- plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/data/PeakDeviation.kt
"""

from dataclasses import dataclass, field
from decimal import Decimal
from math import floor, isfinite
from typing import Optional, List
from enum import Enum


class AutotuneCancelled(Exception):
    """Raised when cooperative cancellation was requested mid-computation."""

    pass


def throw_if_cancelled(cancelled) -> None:
    """Raise AutotuneCancelled if the optional zero-arg callable returns True."""
    if cancelled is not None and cancelled():
        raise AutotuneCancelled()


class Round:
    """Port of AAPS Round.kt rounding utilities."""

    @staticmethod
    def round_to(value: float, step: float) -> float:
        if not isfinite(value):
            raise ValueError("Parameter is NaN or nonfinite")
        if value == 0.0:
            return 0.0
        return float(Decimal(floor(value / step + 0.5)) * Decimal(str(step)))

    @staticmethod
    def floor_to(value: float, step: float) -> float:
        if value != 0.0:
            return (value // step) * step
        return 0.0

    @staticmethod
    def ceil_to(value: float, step: float) -> float:
        if value != 0.0:
            return -((-value) // step) * step
        return 0.0


@dataclass
class BGDatum:
    """Port of AAPS BGDatum - glucose reading with metadata for autotune."""

    date: int  # timestamp in milliseconds
    value: float  # glucose value in mg/dL
    avgDelta: float = 0.0
    bgi: float = 0.0
    deviation: float = 0.0
    mealAbsorption: str = ""
    uamAbsorption: str = ""
    mealCarbs: int = 0


@dataclass
class CRDatum:
    """Port of AAPS CRDatum - carb ratio datum."""

    crInitialBG: float = 0.0
    crInitialIOB: float = 0.0
    crInitialCarbTime: int = 0
    crEndBG: float = 0.0
    crEndIOB: float = 0.0
    crEndTime: int = 0
    crCarbs: float = 0.0
    crInsulin: float = 0.0
    crInsulinTotal: float = 0.0


@dataclass
class DiaDeviation:
    """Port of AAPS DiaDeviation."""

    dia: float
    meanDeviation: float
    smrDeviation: float
    rmsDeviation: float


@dataclass
class PeakDeviation:
    """Port of AAPS PeakDeviation."""

    peak: int
    meanDeviation: float
    smrDeviation: float
    rmsDeviation: float


@dataclass
class PreppedGlucose:
    """Port of AAPS PreppedGlucose - prepared glucose data for autotune."""

    startBG: int
    crData: List[CRDatum]
    csfGlucoseData: List[BGDatum]
    isfGlucoseData: List[BGDatum]
    basalGlucoseData: List[BGDatum]
    diaDeviations: List[DiaDeviation] = field(default_factory=list)
    peakDeviations: List[PeakDeviation] = field(default_factory=list)


@dataclass
class ATProfile:
    """Port of AAPS ATProfile - profile for autotune."""

    basal: list[float] = field(default_factory=lambda: [0.0] * 24)
    basalUnTuned: list[int] = field(default_factory=lambda: [0] * 24)
    ic: float = 0.0
    isf: float = 0.0
    dia: float = 6.0
    peak: int = 75
    isValid: bool = False
    from_: int = 0
    localInsulin: Optional["LocalInsulin"] = None
    profileName: str = ""
    timezone: str = "UTC"

    def getBasal(self, timestamp: int) -> float:
        """Get basal rate at timestamp (milliseconds since epoch)."""
        hour = (timestamp % 86400000) // 3600000
        return self.basal[hour]

    def copy(self) -> "ATProfile":
        """Create a deep copy."""
        return ATProfile(
            basal=self.basal.copy(),
            basalUnTuned=self.basalUnTuned.copy(),
            ic=self.ic,
            isf=self.isf,
            dia=self.dia,
            peak=self.peak,
            isValid=self.isValid,
            from_=self.from_,
            localInsulin=self.localInsulin,
            profileName=self.profileName,
            timezone=self.timezone,
        )


class LocalInsulin:
    """Insulin activity model - ported from AAPS LocalInsulin.

    Uses exponential decay model with tau parameter calculation.
    This is the exact algorithm used by AAPS for IOB calculations.
    """

    MIN_DIA = 5.0
    DEFAULT_DIA = 6.0
    DEFAULT_PEAK = 75

    def __init__(self, name: Optional[str] = None, peak: int = DEFAULT_PEAK, dia_hours: float = DEFAULT_DIA):
        self.name = name
        self.peak = peak
        self._user_defined_dia = dia_hours

    @property
    def dia(self) -> float:
        """Get DIA (duration of insulin action) in hours."""
        dia = self._user_defined_dia
        return dia if dia >= self.MIN_DIA else self.MIN_DIA

    @property
    def duration(self) -> int:
        """Get duration in milliseconds."""
        return int(60 * 60 * 1000 * self.dia)

    def iobCalcForTreatment(self, bolus_amount: float, bolus_timestamp: int, current_time: int) -> "IOBComponents":
        """Calculate IOB for a treatment at given time.

        Port of AAPS LocalInsulin.iobCalcForTreatment.

        Args:
            bolus_amount: Insulin amount in units
            bolus_timestamp: Timestamp of bolus in milliseconds
            current_time: Current timestamp in milliseconds

        Returns:
            IOBComponents with iob_contrib and activity_contrib
        """
        from math import exp, pow

        result = IOBComponents()
        if bolus_amount != 0.0:
            t = (current_time - bolus_timestamp) / 1000.0 / 60.0  # minutes
            td = self.dia * 60  # DIA in minutes
            tp = float(self.peak)

            if t < td:
                tau = tp * (1 - tp / td) / (1 - 2 * tp / td)
                a = 2 * tau / td
                s = 1 / (1 - a + (1 + a) * exp(-td / tau))
                result.activity_contrib = bolus_amount * (s / pow(tau, 2.0)) * t * (1 - t / td) * exp(-t / tau)
                result.iob_contrib = bolus_amount * (1 - s * (1 - a) * (
                    (pow(t, 2.0) / (tau * td * (1 - a)) - t / tau - 1) * exp(-t / tau) + 1
                ))
        return result


@dataclass
class IOBComponents:
    """IOB components breakdown matching AAPS Iob class."""

    iob_contrib: float = 0.0
    activity_contrib: float = 0.0


@dataclass
class IobTotal:
    """Total IOB and activity at a given time."""

    time: int
    iob: float = 0.0
    activity: float = 0.0

    def round(self) -> "IobTotal":
        """Round to 3 decimal places."""
        self.iob = Round.round_to(self.iob, 0.001)
        self.activity = Round.round_to(self.activity, 0.001)
        return self