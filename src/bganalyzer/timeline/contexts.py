"""Analysis context and episode building."""

from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from bganalyzer.contracts.analysis import MealEpisode
from bganalyzer.contracts.domain import Annotation, GlucoseReading, TreatmentEvent, TreatmentKind


@dataclass
class AnalysisContext:
    """Context for a single analysis day."""

    date_ms: int
    glucose: list[GlucoseReading] = field(default_factory=list)
    treatments: list[TreatmentEvent] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    profile_hash: str = ""
    timezone: str = "UTC"


def build_analysis_snapshot(
    glucose: list[GlucoseReading],
    treatments: list[TreatmentEvent],
    annotations: list[Annotation],
    profile_hash: str,
    start_ms: int,
    end_ms: int,
    timezone: str,
) -> AnalysisContext:
    """Build analysis snapshot for a time range."""
    ctx = AnalysisContext(
        date_ms=start_ms,
        glucose=[g for g in glucose if start_ms <= g.event_ms < end_ms],
        treatments=[t for t in treatments if start_ms <= (t.event_ms or 0) < end_ms],
        annotations=[
            a
            for a in annotations
            if a.start_ms < end_ms and (a.end_ms is None or a.end_ms > start_ms)
        ],
        profile_hash=profile_hash,
        timezone=timezone,
    )
    return ctx


def find_meal_episodes(
    treatments: list[TreatmentEvent], glucose: list[GlucoseReading], max_group_minutes: int = 20
) -> list[MealEpisode]:
    """Find meal episodes from carb treatments."""
    carb_treatments = [
        t for t in treatments if t.kind == TreatmentKind.CARBS and t.carbs_g and t.carbs_g > 0
    ]

    if not carb_treatments:
        return []

    episodes = []
    current_group: list[TreatmentEvent] = []

    for tx in sorted(carb_treatments, key=lambda t: t.event_ms or 0):
        if not current_group:
            current_group.append(tx)
        else:
            last_tx = current_group[-1]
            gap_minutes = (
                (tx.event_ms - last_tx.event_ms) / 60000 if tx.event_ms and last_tx.event_ms else 0
            )
            if gap_minutes <= max_group_minutes:
                current_group.append(tx)
            else:
                episodes.append(_create_meal_episode(current_group, glucose))
                current_group = [tx]

    if current_group:
        episodes.append(_create_meal_episode(current_group, glucose))

    return episodes


def _create_meal_episode(
    treatments: list[TreatmentEvent], glucose: list[GlucoseReading]
) -> MealEpisode:
    """Create meal episode from grouped carb treatments."""
    if not treatments:
        return MealEpisode(start_ms=0, end_ms=0)

    start_ms = min(t.event_ms for t in treatments if t.event_ms)
    end_ms = max(t.event_ms for t in treatments if t.event_ms) + 6 * 60 * 60 * 1000
    total_carbs = sum(t.carbs_g for t in treatments if t.carbs_g)

    premeal_window = start_ms - 15 * 60 * 1000
    premeal_glucose = [g for g in glucose if premeal_window <= g.event_ms < start_ms and g.valid]
    premeal_median = (
        sorted([g.sgv_mgdl for g in premeal_glucose])[len(premeal_glucose) // 2]
        if premeal_glucose
        else None
    )

    postmeal_glucose = [g for g in glucose if start_ms <= g.event_ms < end_ms and g.valid]
    peak = max((g.sgv_mgdl for g in postmeal_glucose), default=None)

    glucose_2h = _find_glucose_at(glucose, start_ms + 2 * 60 * 60 * 1000, 5 * 60 * 1000)
    glucose_4h = _find_glucose_at(glucose, start_ms + 4 * 60 * 60 * 1000, 5 * 60 * 1000)

    high_threshold = 180
    time_above = sum(
        5
        for g in postmeal_glucose
        if 60 * 60 * 1000 <= (g.event_ms - start_ms) < 3 * 60 * 60 * 1000
        and g.sgv_mgdl > high_threshold
    )

    bolus_insulin = sum(
        t.insulin_u
        for t in treatments
        if t.kind in (TreatmentKind.BOLUS, TreatmentKind.SMB) and t.insulin_u
    )

    return MealEpisode(
        id=uuid4(),
        start_ms=start_ms,
        end_ms=end_ms,
        carbs_g=total_carbs,
        premeal_median_mgdl=premeal_median,
        peak_mgdl=peak,
        glucose_2h_mgdl=glucose_2h,
        glucose_4h_mgdl=glucose_4h,
        time_above_range_minutes=time_above,
        insulin_before_bolus_u=bolus_insulin,
    )


def _find_glucose_at(
    glucose: list[GlucoseReading], target_ms: int, tolerance_ms: int
) -> Optional[float]:
    """Find glucose reading near target time."""
    candidates = [g for g in glucose if abs(g.event_ms - target_ms) <= tolerance_ms and g.valid]
    if not candidates:
        return None
    return min(candidates, key=lambda g: abs(g.event_ms - target_ms)).sgv_mgdl
