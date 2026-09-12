"""Day preparation for autotune - ported from AAPS AutotunePrep."""

from dataclasses import dataclass
from decimal import Decimal

from bganalyzer.autotune.iob import AutotuneIOB
from bganalyzer.autotune.models import ATProfile, BGDatum, CRDatum, LocalAnalysisDay, PreppedGlucose


@dataclass
class PreppedDay:
    """Prepared day for autotune."""

    date_ms: int
    glucose_data: list[PreppedGlucose]
    carb_data: list[CRDatum]
    profile: ATProfile
    excluded: bool = False
    exclusion_reason: str = ""


def categorize_day(day: LocalAnalysisDay, profile: ATProfile) -> PreppedDay:
    """Categorize a day's data for autotune - ported from categorizeDay."""
    from bganalyzer.autotune.insulin import InsulinModel

    insulin_model = InsulinModel(day.insulin_configuration)
    iob_tracker = AutotuneIOB(day.insulin_configuration)

    # Build IOB timeline
    glucose_data = []

    for bg in day.glucose:
        if not bg.is_valid:
            continue

        # Calculate IOB at this timestamp
        minutes_since_midnight = (bg.timestamp % 86400000) // 60000

        # Get IOB from treatments
        iob = Decimal("0")
        cob = Decimal("0")

        for tx in day.treatments:
            if tx.event_ms > bg.timestamp:
                continue
            minutes_ago = (bg.timestamp - tx.event_ms) // 60000

            if hasattr(tx, "rate_u_h") and tx.rate_u_h:
                duration = (tx.end_ms - tx.event_ms) // 60000 if tx.end_ms else 30
                iob += insulin_model.iob_for_treatment(
                    tx.rate_u_h * Decimal(str(duration)) / Decimal("60"), minutes_ago
                )
            elif hasattr(tx, "amount_u") and tx.amount_u:
                iob += insulin_model.iob_for_treatment(tx.amount_u, minutes_ago)

        # Calculate deviation from target
        time_str = _ms_to_time_str(bg.timestamp, profile.timezone)
        target_low, target_high = profile.get_target_at(time_str)
        target_mid = (target_low + target_high) / Decimal("2")
        deviation = float(bg.glucose_mgdl) - float(target_mid)

        prepped = PreppedGlucose(
            timestamp=bg.timestamp,
            glucose_mgdl=bg.glucose_mgdl,
            iob=iob,
            cob=cob,
            basal_iob=Decimal("0"),
            bolus_iob=iob,
            deviation=deviation / float(target_mid) if target_mid > 0 else 0,
            deviation_mgdl=deviation,
        )
        glucose_data.append(prepped)

    # Categorize carb entries
    carb_data = []
    for tx in day.treatments:
        if hasattr(tx, "carbs_g") and tx.carbs_g and tx.carbs_g > 0:
            if hasattr(tx, "insulin_u") and tx.insulin_u and tx.insulin_u > 0:
                ratio = tx.carbs_g / tx.insulin_u
                carb_data.append(
                    CRDatum(
                        timestamp=tx.event_ms,
                        carbs=tx.carbs_g,
                        insulin=tx.insulin_u,
                        ratio=ratio,
                    )
                )

    return PreppedDay(
        date_ms=day.date_ms,
        glucose_data=glucose_data,
        carb_data=carb_data,
        profile=profile,
    )


def categorize_bg_datums(
    glucose: list[BGDatum], profile: ATProfile, treatments: list, insulin_config
) -> list[PreppedGlucose]:
    """Categorize BG datums for autotune."""
    day = LocalAnalysisDay(
        date_ms=glucose[0].timestamp if glucose else 0,
        glucose=glucose,
        treatments=treatments,
        profile=profile,
        insulin_configuration=insulin_config,
    )
    prepped = categorize_day(day, profile)
    return prepped.glucose_data


def _ms_to_time_str(ms: int, timezone: str) -> str:
    """Convert milliseconds to HH:MM time string."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    dt = datetime.fromtimestamp(ms / 1000, ZoneInfo(timezone))
    return f"{dt.hour:02d}:{dt.minute:02d}"
