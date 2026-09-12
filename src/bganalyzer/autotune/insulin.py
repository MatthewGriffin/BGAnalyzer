"""Unvalidated legacy triangular prototype; NOT an AAPS LocalInsulin port.

Do not use for numerical recommendations. The executable reference comparison is
isolated in reference/run_insulin_parity.py and is not integrated here.
"""

from decimal import Decimal
from typing import Optional

from bganalyzer.autotune.models import InsulinConfiguration


class InsulinModel:
    """Legacy approximation; its activity and IOB semantics are not validated."""

    def __init__(self, config: InsulinConfiguration) -> None:
        self.config = config
        self._activity_cache: dict[tuple, Decimal] = {}

    def get_activity(
        self, minutes: int, peak_minutes: Optional[int] = None, dia_minutes: Optional[int] = None
    ) -> Decimal:
        """Get insulin activity at given minutes after injection."""
        peak = peak_minutes or self.config.peak_minutes
        dia = dia_minutes or int(self.config.dia_hours * 60)

        cache_key = (minutes, peak, dia)
        if cache_key in self._activity_cache:
            return self._activity_cache[cache_key]

        if minutes <= 0:
            return Decimal("0")
        if minutes >= dia:
            return Decimal("0")

        # Triangular model (rapid-acting approximation)
        if minutes <= peak:
            activity = Decimal(str(minutes)) / Decimal(str(peak))
        else:
            activity = Decimal(str(dia - minutes)) / Decimal(str(dia - peak))

        activity = max(Decimal("0"), min(Decimal("1"), activity))
        self._activity_cache[cache_key] = activity
        return activity

    def iob_for_treatment(
        self,
        amount_u: Decimal,
        minutes_ago: int,
        peak_minutes: Optional[int] = None,
        dia_minutes: Optional[int] = None,
    ) -> Decimal:
        """Calculate IOB for a treatment at given minutes ago."""
        activity = self.get_activity(minutes_ago, peak_minutes, dia_minutes)
        return amount_u * activity

    def get_iob_curve(
        self,
        amount_u: Decimal,
        peak_minutes: Optional[int] = None,
        dia_minutes: Optional[int] = None,
    ) -> list[tuple[int, Decimal]]:
        """Get full IOB curve for a bolus."""
        dia = dia_minutes or int(self.config.dia_hours * 60)
        curve = []
        for m in range(0, dia + 1, 5):
            iob = self.iob_for_treatment(amount_u, m, peak_minutes, dia_minutes)
            if iob > 0:
                curve.append((m, iob))
        return curve


def iob_for_treatment(amount_u: Decimal, minutes_ago: int, config: InsulinConfiguration) -> Decimal:
    """Standalone IOB calculation for a treatment."""
    model = InsulinModel(config)
    return model.iob_for_treatment(amount_u, minutes_ago)


def calculate_total_iob(
    treatments: list, current_time_ms: int, config: InsulinConfiguration
) -> Decimal:
    """Calculate total IOB from all treatments."""
    model = InsulinModel(config)
    total = Decimal("0")

    for tx in treatments:
        if tx.amount_u and tx.amount_u > 0:
            minutes_ago = (current_time_ms - tx.event_ms) // 60000
            if minutes_ago > 0:
                total += model.iob_for_treatment(tx.amount_u, minutes_ago)

    return total
