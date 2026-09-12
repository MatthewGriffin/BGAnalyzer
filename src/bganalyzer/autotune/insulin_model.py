"""Insulin activity model - ported from AAPS LocalInsulin.kt.

This is a literal translation of the pinned AAPS insulin model.
Upstream commit: 1393357107a2b27ba153df31d64e745efd771ef2
Reference file: plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/data/LocalInsulin.kt
"""

from dataclasses import dataclass
from math import exp, pow


@dataclass
class IOBComponents:
    """IOB components breakdown matching AAPS Iob class."""

    iob_contrib: float = 0.0
    activity_contrib: float = 0.0


class LocalInsulin:
    """Insulin activity model - ported from AAPS LocalInsulin.

    Uses exponential decay model with tau parameter calculation.
    This is the exact algorithm used by AAPS for IOB calculations.
    """

    MIN_DIA = 5.0
    DEFAULT_DIA = 6.0
    DEFAULT_PEAK = 75

    def __init__(self, peak_minutes: int = DEFAULT_PEAK, dia_hours: float = DEFAULT_DIA):
        self.peak = peak_minutes
        self._user_defined_dia = dia_hours

    @property
    def dia(self) -> float:
        """Get DIA (duration of insulin action) in hours."""
        dia = self._user_defined_dia
        return dia if dia >= self.MIN_DIA else self.MIN_DIA

    @property
    def duration_ms(self) -> int:
        """Get duration in milliseconds."""
        return int(60 * 60 * 1000 * self.dia)

    def iob_calc_for_treatment(self, bolus_amount: float, bolus_timestamp_ms: int, current_time_ms: int) -> IOBComponents:
        """Calculate IOB for a treatment at given time.

        Port of AAPS LocalInsulin.iobCalcForTreatment.

        Args:
            bolus_amount: Insulin amount in units
            bolus_timestamp_ms: Timestamp of bolus in milliseconds
            current_time_ms: Current timestamp in milliseconds

        Returns:
            IOBComponents with iob_contrib and activity_contrib
        """
        result = IOBComponents()
        if bolus_amount != 0.0:
            t = (current_time_ms - bolus_timestamp_ms) / 1000.0 / 60.0  # minutes
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


def calculate_iob_at_time(
    treatments: list,  # list of (event_ms, amount_u, is_bolus)
    current_time_ms: int,
    peak_minutes: int,
    dia_hours: float,
) -> IOBComponents:
    """Calculate total IOB from all treatments at a specific time.

    Args:
        treatments: List of (event_ms, amount_u, is_bolus) tuples
        current_time_ms: Current timestamp in milliseconds
        peak_minutes: Insulin peak time in minutes
        dia_hours: Insulin duration of action in hours

    Returns:
        Total IOBComponents from all treatments
    """
    model = LocalInsulin(peak_minutes, dia_hours)
    total = IOBComponents()

    for event_ms, amount_u, is_bolus in treatments:
        if amount_u > 0 and event_ms < current_time_ms:
            components = model.iob_calc_for_treatment(amount_u, event_ms, current_time_ms)
            total.iob_contrib += components.iob_contrib
            total.activity_contrib += components.activity_contrib

    return total