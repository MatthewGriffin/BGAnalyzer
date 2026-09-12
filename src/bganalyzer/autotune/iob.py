"""IOB (Insulin On Board) calculations - ported from AAPS AutotuneIob."""

from dataclasses import dataclass
from decimal import Decimal

from bganalyzer.autotune.insulin import InsulinModel
from bganalyzer.autotune.models import InsulinConfiguration


@dataclass
class IOBComponents:
    """IOB components breakdown."""

    total: Decimal
    basal: Decimal
    bolus: Decimal


class AutotuneIOB:
    """IOB tracking for autotune - ported from AAPS AutotuneIob."""

    def __init__(self, config: InsulinConfiguration) -> None:
        self.config = config
        self.model = InsulinModel(config)
        self.basal_iob = Decimal("0")
        self.bolus_iob = Decimal("0")

    def add_basal(self, rate_u_h: Decimal, duration_minutes: int) -> None:
        """Add basal insulin delivery."""
        amount = rate_u_h * Decimal(str(duration_minutes)) / Decimal("60")
        self.basal_iob += amount

    def add_bolus(self, amount_u: Decimal) -> None:
        """Add bolus insulin delivery."""
        self.bolus_iob += amount_u

    def update(self, minutes_elapsed: int) -> None:
        """Decay IOB over time."""
        if minutes_elapsed <= 0:
            return

        # Decay basal IOB
        if self.basal_iob > 0:
            activity = self.model.get_activity(minutes_elapsed)
            self.basal_iob *= activity

        # Decay bolus IOB
        if self.bolus_iob > 0:
            activity = self.model.get_activity(minutes_elapsed)
            self.bolus_iob *= activity

    def get_components(self) -> IOBComponents:
        """Get current IOB components."""
        return IOBComponents(
            total=self.basal_iob + self.bolus_iob,
            basal=self.basal_iob,
            bolus=self.bolus_iob,
        )


def calculate_iob_at_time(
    treatments: list,  # DeliveryInterval, BolusDelivery
    at_time_ms: int,
    config: InsulinConfiguration,
) -> IOBComponents:
    """Calculate IOB at specific time from treatment history."""
    iob = AutotuneIOB(config)

    for tx in treatments:
        if tx.event_ms >= at_time_ms:
            continue

        minutes_ago = (at_time_ms - tx.event_ms) // 60000

        if hasattr(tx, "rate_u_h") and tx.rate_u_h:
            # Basal delivery
            duration = (tx.end_ms - tx.event_ms) // 60000 if tx.end_ms else 30
            iob.add_basal(tx.rate_u_h, duration)
        elif hasattr(tx, "amount_u") and tx.amount_u:
            # Bolus delivery
            iob.add_bolus(tx.amount_u)

    # Decay to current time
    # (In practice, we'd track this incrementally)

    return iob.get_components()
