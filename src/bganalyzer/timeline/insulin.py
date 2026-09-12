"""Unvalidated legacy delivery reconstruction prototype; not a verified AAPS port.

Implements resolve_delivery(start_ms, end_ms) -> list[DeliveryInterval]
as specified in IMPLEMENTATION_PLAN.md section 8.

Upstream commit: 1393357107a2b27ba153df31d64e745efd771ef2
Reference target: AAPS AutotuneIob.kt. This module has not passed parity.
Do not infer pump-confirmed delivery from its labels or use it for recommendations.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional
from zoneinfo import ZoneInfo

from bganalyzer.autotune.models import LocalInsulin
from bganalyzer.timeline.profiles import ProfileTimeline, ResolvedProfile


class DeliveryOrigin(str, Enum):
    """Origin of insulin delivery."""

    REPORTED_TEMP = "reported_temp"       # Confirmed temp basal from pump
    SCHEDULED_ASSUMED = "scheduled_assumed"  # Scheduled basal (no temp recorded)
    REPORTED_SUSPEND = "reported_suspend"    # Explicit suspend
    REPORTED_RESUME = "reported_resume"      # Explicit resume
    BOLUS = "bolus"                        # Normal bolus
    SMB = "smb"                            # Super micro bolus
    EXTENDED_BOLUS = "extended_bolus"      # Extended/combo bolus
    UNKNOWN = "unknown"                    # Unresolved/conflicting


@dataclass
class DeliveryInterval:
    """Insulin delivery interval with provenance."""

    start_ms: int
    end_ms: int
    rate_u_hr: float  # For basal: U/hr; for bolus: total U over interval
    origin: DeliveryOrigin
    source_ids: List[str]  # Treatment/event IDs
    quality: str  # "confirmed" | "assumed" | "uncertain" | "conflicted"
    profile_basal_at_start: float = 0.0  # Scheduled basal rate at interval start
    is_percentage: bool = False  # True if temp basal was percentage-based
    percent_value: float = 0.0  # Percentage value if is_percentage

    @property
    def duration_minutes(self) -> int:
        return (self.end_ms - self.start_ms) // 60000

    @property
    def insulin_units(self) -> float:
        """Total insulin delivered in this interval."""
        if self.origin in (DeliveryOrigin.BOLUS, DeliveryOrigin.SMB, DeliveryOrigin.EXTENDED_BOLUS):
            return self.rate_u_hr
        return self.rate_u_hr * self.duration_minutes / 60.0


@dataclass
class BolusDelivery:
    """Discrete bolus delivery event."""

    event_ms: int
    amount_u: float
    origin: DeliveryOrigin
    source_id: str
    is_valid: bool = True
    delivery_status: str = "delivered"  # "delivered" | "cancelled" | "unknown"


class DeliveryTimeline:
    """Reconstructs insulin delivery timeline from treatments and profile.

    Builds boundaries at:
    - Profile transitions
    - Basal schedule transitions
    - Temp basal start/end/cancellation
    - Suspend/resume
    - Pod change
    """

    def __init__(
        self,
        treatments: List[dict],  # Raw treatment records from DB
        profile_timeline: 'ProfileTimeline',
        default_timezone: str = "UTC",
    ):
        self.treatments = treatments
        self.profile_timeline = profile_timeline
        self.default_timezone = default_timezone
        self._delivery_intervals: List[DeliveryInterval] = []
        self._bolus_deliveries: List[BolusDelivery] = []
        self._build()

    def _build(self):
        """Build delivery intervals from treatments."""
        # Separate treatments by type
        temp_basals = [t for t in self.treatments if t.get("kind") == "temp_basal"]
        boluses = [t for t in self.treatments if t.get("kind") in ("bolus", "smb")]
        suspends = [t for t in self.treatments if t.get("kind") == "suspend"]
        resumes = [t for t in self.treatments if t.get("kind") == "resume"]

        # Process temp basals with AAPS splitting logic
        self._process_temp_basals(temp_basals)

        # Process boluses/SMB
        self._process_boluses(boluses)

        # Process suspend/resume
        self._process_suspends(suspends, resumes)

        # Fill gaps with scheduled basal (assumed)
        self._fill_scheduled_gaps()

        # Sort by start time
        self._delivery_intervals.sort(key=lambda x: x.start_ms)

    def _process_temp_basals(self, temp_basals: List[dict]):
        """Process temp basal records with AAPS splitting logic.

        Port of AutotuneIob.toSplittedTimestampTB:
        - Split across hour boundaries
        - Convert percentage to absolute using profile at each boundary
        - Handle cancellations (endId)
        """
        for tb in temp_basals:
            if not tb.get("valid", True):
                continue

            start = tb["event_ms"]
            duration = tb.get("duration", tb.get("durationInMilliseconds", 30 * 60000))
            rate = tb.get("rate", 0.0)
            is_absolute = tb.get("absolute", True) or not tb.get("percent", False)
            percent = tb.get("percent", 0.0)
            end_id = tb.get("endId")
            source_id = tb.get("remote_id", tb.get("id", ""))

            # Handle cancellation
            end = start + duration
            if end_id:
                # Find cancellation record
                cancel = next((t for t in self.treatments
                               if t.get("remote_id") == end_id or t.get("id") == end_id), None)
                if cancel and cancel.get("event_ms"):
                    end = min(end, cancel["event_ms"])

            # Split at hour boundaries (AAPS uses 60-min intervals for accuracy)
            self._split_and_add_temp_basal(start, end, rate, is_absolute, percent, source_id)

    def _split_and_add_temp_basal(
        self,
        start: int,
        end: int,
        rate: float,
        is_absolute: bool,
        percent: float,
        source_id: str,
    ):
        """Split temp basal at hour boundaries and convert to absolute rates."""
        current = start
        cut_ms = 60 * 60 * 1000  # 1 hour in ms

        while current < end:
            # Find hour boundary
            next_boundary = ((current // cut_ms) + 1) * cut_ms
            segment_end = min(end, next_boundary)

            # Get profile basal at this segment start
            resolved = self.profile_timeline.resolve_profile(current)
            profile_basal = 0.0
            if isinstance(resolved, ResolvedProfile):
                # Get basal rate at this hour
                hour = (current % 86400000) // 3600000
                for time_str, val in resolved.basal_schedule:
                    h, m = map(int, time_str.split(":"))
                    if h == hour:
                        profile_basal = val
                        break

            # Convert rate to absolute
            if is_absolute:
                absolute_rate = rate
            else:
                absolute_rate = (percent / 100.0) * profile_basal if profile_basal > 0 else 0.0

            # Net basal = temp basal - scheduled basal (AAPS approach)
            net_basal = absolute_rate - profile_basal

            self._delivery_intervals.append(DeliveryInterval(
                start_ms=current,
                end_ms=segment_end,
                rate_u_hr=net_basal,
                origin=DeliveryOrigin.REPORTED_TEMP,
                source_ids=[source_id],
                quality="confirmed" if net_basal != 0 else "assumed",
                profile_basal_at_start=profile_basal,
                is_percentage=not is_absolute,
                percent_value=percent if not is_absolute else 0.0,
            ))

            current = segment_end

    def _process_boluses(self, boluses: List[dict]):
        """Process bolus and SMB treatments."""
        for bolus in boluses:
            if not bolus.get("valid", True):
                continue

            amount = bolus.get("insulin_u", bolus.get("amount_u", 0.0))
            if amount is None:
                amount = 0.0
            elif isinstance(amount, str):
                try:
                    amount = float(amount)
                except (ValueError, TypeError):
                    amount = 0.0
            if amount <= 0:
                continue

            event_ms = bolus["event_ms"]
            is_smb = bolus.get("kind") == "smb" or bolus.get("isSMB", False)
            source_id = bolus.get("remote_id", bolus.get("id", ""))

            delivery = BolusDelivery(
                event_ms=event_ms,
                amount_u=amount,
                origin=DeliveryOrigin.SMB if is_smb else DeliveryOrigin.BOLUS,
                source_id=source_id,
                is_valid=bolus.get("valid", True),
                delivery_status=bolus.get("delivery_status", "unknown"),
            )
            self._bolus_deliveries.append(delivery)

    def _process_suspends(self, suspends: List[dict], resumes: List[dict]):
        """Process suspend/resume events."""
        # Match suspends with resumes
        for suspend in suspends:
            if not suspend.get("valid", True):
                continue
            start = suspend["event_ms"]
            # Find matching resume
            resume = next((r for r in resumes if r.get("event_ms", 0) > start), None)
            end = resume["event_ms"] if resume else None

            self._delivery_intervals.append(DeliveryInterval(
                start_ms=start,
                end_ms=end or start,
                rate_u_hr=0.0,
                origin=DeliveryOrigin.REPORTED_SUSPEND,
                source_ids=[suspend.get("remote_id", "")],
                quality="confirmed",
            ))

    def _fill_scheduled_gaps(self):
        """Fill gaps with scheduled basal (assumed delivery).

        Only fills where no temp basal is recorded.
        Marks as SCHEDULED_ASSUMED with quality 'assumed'.
        """
        if not self._delivery_intervals:
            return

        # Sort intervals by start time
        self._delivery_intervals.sort(key=lambda x: x.start_ms)

        # Fill gaps between intervals with scheduled basal
        for i in range(len(self._delivery_intervals) - 1):
            current = self._delivery_intervals[i]
            next_interval = self._delivery_intervals[i + 1]

            # Skip if intervals overlap or are adjacent
            if current.end_ms >= next_interval.start_ms:
                continue

            # Skip if current interval is a suspend (no basal during suspend)
            if current.origin == DeliveryOrigin.REPORTED_SUSPEND:
                continue

            # Fill the gap with scheduled basal
            gap_start = current.end_ms
            gap_end = next_interval.start_ms

            # Get profile basal at gap start
            resolved = self.profile_timeline.resolve_profile(gap_start)
            profile_basal = 0.0
            if isinstance(resolved, ResolvedProfile):
                hour = (gap_start % 86400000) // 3600000
                for time_str, val in resolved.basal_schedule:
                    h, m = map(int, time_str.split(":"))
                    if h == hour:
                        profile_basal = val
                        break

            # Only add if there's a meaningful gap and basal rate
            if gap_end - gap_start > 60000 and profile_basal > 0:  # At least 1 minute gap
                self._delivery_intervals.append(DeliveryInterval(
                    start_ms=gap_start,
                    end_ms=gap_end,
                    rate_u_hr=profile_basal,
                    origin=DeliveryOrigin.SCHEDULED_ASSUMED,
                    source_ids=[],
                    quality="assumed",
                    profile_basal_at_start=profile_basal,
                ))

        # Re-sort after adding gap fillers
        self._delivery_intervals.sort(key=lambda x: x.start_ms)

    def resolve_delivery(self, start_ms: int, end_ms: int) -> List[DeliveryInterval]:
        """Get delivery intervals within range."""
        result = []
        for d in self._delivery_intervals:
            if d.start_ms < end_ms and d.end_ms > start_ms:
                # Clip to range
                clipped = DeliveryInterval(
                    start_ms=max(d.start_ms, start_ms),
                    end_ms=min(d.end_ms, end_ms),
                    rate_u_hr=d.rate_u_hr,
                    origin=d.origin,
                    source_ids=d.source_ids.copy(),
                    quality=d.quality,
                    profile_basal_at_start=d.profile_basal_at_start,
                    is_percentage=d.is_percentage,
                    percent_value=d.percent_value,
                )
                result.append(clipped)
        return result

    def get_bolus_deliveries(self, start_ms: int, end_ms: int) -> List[BolusDelivery]:
        """Get bolus deliveries within range."""
        return [b for b in self._bolus_deliveries
                if start_ms <= b.event_ms < end_ms]


def build_delivery_timeline(
    conn,
    source_id: str,
    start_ms: int,
    end_ms: int,
    profile_timeline: 'ProfileTimeline',
) -> DeliveryTimeline:
    """Build DeliveryTimeline from database treatments."""
    treatments = conn.execute("""
        SELECT remote_id, revision_hash, event_ms, end_ms, kind,
               insulin_u, carbs_g, rate_u_h, percent, delivery_status, valid
        FROM treatments
        WHERE source_id = ? AND event_ms >= ? AND event_ms < ?
        ORDER BY event_ms
    """, (source_id, start_ms, end_ms)).fetchall()

    treatment_list = [dict(row) for row in treatments]
    return DeliveryTimeline(treatment_list, profile_timeline)