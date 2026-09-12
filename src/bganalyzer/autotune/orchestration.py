"""Autotune orchestration - builds analysis snapshots and runs autotune.

Port of AAPS AutotunePlugin.kt day boundaries and iteration order.
Reference: plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/AutotunePlugin.kt
"""

from dataclasses import dataclass, field
import json
from bisect import bisect_left
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from bganalyzer.autotune.models import (
    ATProfile,
    PreppedGlucose,
    LocalInsulin,
    throw_if_cancelled,
)
from bganalyzer.autotune.categorize import categorize_day, Treatment, CarbEntry, TempBasal
from bganalyzer.autotune.core import run_autotune, TunedProfile
from bganalyzer.timeline.profiles import ProfileTimeline, build_profile_timeline
from bganalyzer.timeline.insulin import DeliveryTimeline, build_delivery_timeline


@dataclass
class AnalysisDay:
    """Single day of analysis data for autotune."""

    date_ms: int  # Local midnight for this day
    glucose: List[dict]  # {"timestamp": int, "value": float}
    treatments: List[Treatment]
    carb_entries: List[CarbEntry]
    temp_basals: List[TempBasal]
    profile: ATProfile
    local_insulin: LocalInsulin


@dataclass
class AutotuneInput:
    """Input for full autotune run."""

    baseline_profile: ATProfile
    pump_profile: ATProfile
    analysis_days: List[AnalysisDay]
    preferences: dict


@dataclass
class AutotuneOutput:
    """Complete autotune run result."""

    tuned_days: List[TunedProfile]
    final_profile: ATProfile
    baseline_profile: ATProfile
    eligibility: dict
    day_stats: List[dict] = field(default_factory=list)
    prepped_days: List[PreppedGlucose] = field(default_factory=list)
    preferences: dict = field(default_factory=dict)
    pump_profile: Optional[ATProfile] = None


def build_analysis_snapshot(
    conn,
    source_id: str,
    start_ms: int,
    end_ms: int,
    timezone: str,
    cancelled=None,
) -> Optional[AutotuneInput]:
    """Build complete autotune input from database.

    Implements the full pipeline:
    1. Build ProfileTimeline from profile_versions and activations
    2. Build DeliveryTimeline from treatments
    3. Split into analysis days (local midnight boundaries)
    4. Categorize each day
    5. Prepare autotune input

    cancelled is an optional zero-arg callable; AutotuneCancelled is raised
    promptly when it returns True.
    """
    # Build timelines
    profile_timeline = build_profile_timeline(conn, source_id, end_ms, start_ms)
    delivery_timeline = build_delivery_timeline(conn, source_id, start_ms, end_ms, profile_timeline)

    # Load glucose readings
    glucose_rows = conn.execute("""
        SELECT event_ms, sgv_mgdl, valid
        FROM glucose
        WHERE source_id = ? AND event_ms >= ? AND event_ms < ? AND valid = 1
        ORDER BY event_ms
    """, (source_id, start_ms, end_ms)).fetchall()

    glucose_readings = [
        {"timestamp": row["event_ms"], "value": row["sgv_mgdl"]}
        for row in glucose_rows
    ]

    # Load treatments
    treatment_rows = conn.execute("""
        SELECT remote_id, event_ms, end_ms, kind, insulin_u, carbs_g,
               rate_u_h, percent, delivery_status, valid
        FROM treatments
        WHERE source_id = ? AND event_ms >= ? AND event_ms < ?
        ORDER BY event_ms
    """, (source_id, start_ms, end_ms)).fetchall()

    # Convert to typed structures
    treatments = []
    carb_entries = []
    temp_basals = []

    for row in treatment_rows:
        insulin_u = row["insulin_u"]
        if isinstance(insulin_u, str):
            try:
                insulin_u = float(insulin_u)
            except (ValueError, TypeError):
                insulin_u = 0.0
        elif insulin_u is None:
            insulin_u = 0.0

        carbs_g = row["carbs_g"]
        if isinstance(carbs_g, str):
            try:
                carbs_g = float(carbs_g)
            except (ValueError, TypeError):
                carbs_g = 0.0
        elif carbs_g is None:
            carbs_g = 0.0

        rate_u_h = row["rate_u_h"]
        if isinstance(rate_u_h, str):
            try:
                rate_u_h = float(rate_u_h)
            except (ValueError, TypeError):
                rate_u_h = 0.0
        elif rate_u_h is None:
            rate_u_h = 0.0

        t = Treatment(
            timestamp=row["event_ms"],
            amount=insulin_u,
            is_valid=row["valid"],
            type=row["kind"],
        )
        if row["kind"] in ("bolus", "smb"):
            t.is_bolus = True
            t.amount = insulin_u
            treatments.append(t)
        elif row["kind"] == "temp_basal":
            temp_basals.append(TempBasal(
                timestamp=row["event_ms"],
                duration=row["end_ms"] - row["event_ms"] if row["end_ms"] else 30 * 60000,
                rate=rate_u_h,
                is_absolute=not bool(row["percent"]),
                is_valid=row["valid"],
            ))
        elif row["kind"] == "carbs" or row["carbs_g"]:
            carb_entries.append(CarbEntry(
                timestamp=row["event_ms"],
                amount=carbs_g,
                is_valid=row["valid"],
            ))

    # Get baseline profile (earliest profile in range)
    baseline_rows = conn.execute("""
        SELECT normalized_json FROM profile_versions
        WHERE source_id = ? AND effective_from_ms <= ?
        ORDER BY effective_from_ms
        LIMIT 1
    """, (source_id, start_ms)).fetchone()

    if not baseline_rows:
        return None

    baseline_data = baseline_rows["normalized_json"]
    if isinstance(baseline_data, str):
        baseline_data = json.loads(baseline_data)
    baseline_profile = _parse_atprofile(baseline_data, timezone)

    # Get current pump profile (latest)
    pump_rows = conn.execute("""
        SELECT normalized_json FROM profile_versions
        WHERE source_id = ? AND effective_from_ms <= ?
        ORDER BY effective_from_ms DESC
        LIMIT 1
    """, (source_id, end_ms)).fetchone()

    pump_profile = baseline_profile
    if pump_rows:
        pump_data = pump_rows["normalized_json"]
        if isinstance(pump_data, str):
            pump_data = json.loads(pump_data)
        pump_profile = _parse_atprofile(pump_data, timezone)

    # Split into local days
    analysis_days = _split_into_days(
        glucose_readings, treatments, carb_entries, temp_basals,
        baseline_profile, profile_timeline, delivery_timeline,
        start_ms, end_ms, timezone, cancelled
    )

    preferences = _load_preferences(conn, source_id)

    return AutotuneInput(
        baseline_profile=baseline_profile,
        pump_profile=pump_profile,
        analysis_days=analysis_days,
        preferences=preferences,
    )


def _parse_atprofile(data: dict, timezone: str) -> ATProfile:
    """Parse normalized profile JSON into ATProfile.

    Basal schedules expand to 24 hourly rates by wall-time lookup so
    half-hour boundaries are honored. Missing DIA/peak stay 0 (unknown) so
    eligibility flags INSULIN_DIA_UNKNOWN/INSULIN_PEAK_UNKNOWN instead of
    silently substituting library defaults.
    """
    profile = ATProfile(profileName=data.get("name", ""), timezone=timezone)

    # Parse basal (24 hourly values, wall-time expansion)
    basal = data.get("basal", [])
    schedule = []
    for entry in basal:
        try:
            time_str = entry.get("time", "00:00")[:5]
            value = float(entry.get("value", entry.get("rate", 0.0)))
        except (ValueError, TypeError, AttributeError):
            continue
        schedule.append((time_str, value))
    schedule.sort(key=lambda x: x[0])
    for h in range(24):
        profile.basal[h] = _schedule_value_at(schedule, f"{h:02d}:00") if schedule else 0.0

    # Parse IC (carb ratio)
    ic = data.get("carbratio", data.get("carb_ratio", []))
    if ic:
        try:
            profile.ic = float(ic[0].get("value", 10.0)) if isinstance(ic[0], dict) else float(ic[0])
        except (ValueError, TypeError):
            profile.ic = 0.0

    # Parse ISF
    sens = data.get("sens", data.get("isf", []))
    if sens:
        try:
            profile.isf = float(sens[0].get("value", 50.0)) if isinstance(sens[0], dict) else float(sens[0])
        except (ValueError, TypeError):
            profile.isf = 0.0

    # DIA and peak: unknown stays 0, never a silent default.
    try:
        profile.dia = float(data.get("dia", 0.0) or 0.0)
    except (ValueError, TypeError):
        profile.dia = 0.0
    try:
        profile.peak = int(data.get("peak", 0) or 0)
    except (ValueError, TypeError):
        profile.peak = 0
    profile.isValid = True

    # Create LocalInsulin
    profile.localInsulin = LocalInsulin(None, profile.peak, profile.dia)

    return profile


def _split_into_days(
    glucose_readings: List[dict],
    treatments: List[Treatment],
    carb_entries: List[CarbEntry],
    temp_basals: List[TempBasal],
    baseline_profile: ATProfile,
    profile_timeline: ProfileTimeline,
    delivery_timeline: DeliveryTimeline,
    start_ms: int,
    end_ms: int,
    timezone: str,
    cancelled=None,
) -> List[AnalysisDay]:
    """Split data into local calendar days for autotune.

    AAPS uses local midnight boundaries with DST handling. Day membership is
    the same half-open [day_start, day_end) window as a per-day scan; inputs
    arrive time-ordered from the database, so each day's slice is located with
    binary search instead of rescanning every list for every day.
    """
    days = []
    tz = ZoneInfo(timezone)

    glucose_ts = [g["timestamp"] for g in glucose_readings]
    treatment_ts = [t.timestamp for t in treatments]
    carb_ts = [c.timestamp for c in carb_entries]
    temp_ts = [tb.timestamp for tb in temp_basals]

    # Find local midnight boundaries
    current = start_ms
    while current < end_ms:
        throw_if_cancelled(cancelled)
        dt = datetime.fromtimestamp(current / 1000, tz)
        local_midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = int(local_midnight.timestamp() * 1000)
        day_end = day_start + 86400000

        # Slice each time-ordered list to this day (same membership as a scan).
        glo, ghi = bisect_left(glucose_ts, day_start), bisect_left(glucose_ts, day_end)
        tlo, thi = bisect_left(treatment_ts, day_start), bisect_left(treatment_ts, day_end)
        clo, chi = bisect_left(carb_ts, day_start), bisect_left(carb_ts, day_end)
        blo, bhi = bisect_left(temp_ts, day_start), bisect_left(temp_ts, day_end)
        day_glucose = glucose_readings[glo:ghi]
        day_treatments = treatments[tlo:thi]
        day_carbs = carb_entries[clo:chi]
        day_temp = temp_basals[blo:bhi]

        # Resolve profile for this day. Days without a validated resolved
        # profile are skipped rather than silently falling back to baseline:
        # tuning them against the wrong schedule would be dishonest.
        # (Advance first: skipping must not stall the day loop.)
        day_profile = profile_timeline.resolve_profile(day_start + 43200000)  # Noon
        current = day_end
        if day_profile is None or not hasattr(day_profile, 'basal_schedule'):
            continue
        # Convert ResolvedProfile to ATProfile
        day_profile_at = _resolved_to_atprofile(day_profile)

        if day_glucose:
            days.append(AnalysisDay(
                date_ms=day_start,
                glucose=day_glucose,
                treatments=day_treatments,
                carb_entries=day_carbs,
                temp_basals=day_temp,
                profile=day_profile_at,
                local_insulin=day_profile_at.localInsulin or LocalInsulin(),
            ))

    return days


def _schedule_value_at(schedule, time_str: str) -> float:
    """Return schedule value active at a HH:MM wall time."""
    value = schedule[0][1] if schedule else 0.0
    for start, val in sorted(schedule, key=lambda x: x[0]):
        if start <= time_str:
            value = val
        else:
            break
    return float(value)


def _resolved_to_atprofile(resolved) -> ATProfile:
    """Convert ResolvedProfile to ATProfile for autotune.

    ATProfile carries 24 hourly basal rates plus scalar IC/ISF. Hourly basal
    is expanded from the wall-time schedule; scalar IC/ISF use the noon value
    because the pinned Autotune port tunes scalars only (see plan section 10).
    """
    hourly_basal = [_schedule_value_at(resolved.basal_schedule, f"{h:02d}:00") for h in range(24)]
    profile = ATProfile(
        basal=hourly_basal,
        ic=_schedule_value_at(resolved.ic_schedule, "12:00"),
        isf=_schedule_value_at(resolved.isf_schedule, "12:00"),
        dia=float(resolved.dia_hours),
        peak=int(resolved.peak_minutes),
        timezone=resolved.timezone,
    )
    profile.localInsulin = LocalInsulin(None, resolved.peak_minutes, resolved.dia_hours)
    profile.isValid = True
    return profile


def _load_preferences(conn, source_id: str) -> dict:
    """Load autotune preferences from settings."""
    # Default AAPS autotune settings
    return {
        "autosens_max": 1.2,
        "autosens_min": 0.7,
        "min_5min_carbimpact": 8.0,
        "autotune_tune_insulin_curve": False,
        "autotune_categorize_uam_as_basal": False,
    }


def run_full_autotune(
    input_data: AutotuneInput, cancelled=None, progress=None
) -> AutotuneOutput:
    """Run complete autotune analysis.

    1. Categorize each day's glucose data
    2. Run multi-day tuning with chronological iteration
    3. Return final profile and per-day results

    cancelled is an optional zero-arg callable; AutotuneCancelled is raised
    promptly when it returns True. progress, if given, receives
    (done_days, total_days) after each tuned day.
    """
    # Categorize each day, keeping (day, prepped) pairs so per-day support
    # statistics stay aligned even when some days fail categorization.
    paired: List[tuple] = []
    day_stats: List[dict] = []
    total = len(input_data.analysis_days)
    for pos, day in enumerate(input_data.analysis_days):
        throw_if_cancelled(cancelled)
        prepped = categorize_day(
            day.glucose,
            day.treatments,
            day.carb_entries,
            day.temp_basals,
            day.profile,
            input_data.preferences,
            day.local_insulin,
            cancelled=cancelled,
        )
        if prepped is None:
            day_stats.append(
                {
                    "date_ms": day.date_ms,
                    "tuned": False,
                    "n_basal_data": 0,
                    "n_isf_data": 0,
                    "n_cr_data": 0,
                }
            )
        else:
            paired.append((day, prepped))
        if progress is not None:
            progress(f"Categorizing day {pos + 1}/{total}…")

    # Run multi-day autotune
    tuned_days = run_autotune(
        [prepped for _, prepped in paired],
        input_data.baseline_profile,
        input_data.pump_profile,
        input_data.preferences,
        cancelled=cancelled,
        progress=(lambda done, n: progress(f"Tuning day {done}/{n}…")) if progress else None,
    )

    for (day, prepped), _tuned in zip(paired, tuned_days):
        day_stats.append(
            {
                "date_ms": day.date_ms,
                "tuned": True,
                "n_basal_data": len(prepped.basalGlucoseData),
                "n_isf_data": len(prepped.isfGlucoseData),
                "n_cr_data": len(prepped.crData),
            }
        )
    day_stats.sort(key=lambda stat: stat["date_ms"])

    # Build final profile
    if tuned_days:
        last = tuned_days[-1]
        final_profile = ATProfile(
            basal=last.basal,
            basalUnTuned=last.basal_un_tuned,
            ic=last.ic,
            isf=last.isf,
            dia=last.dia,
            peak=last.peak,
            isValid=True,
            from_=paired[-1][1].startBG if paired else 0,
            localInsulin=last.local_insulin,
            profileName=input_data.baseline_profile.profileName,
        )
    else:
        final_profile = input_data.baseline_profile.copy()

    return AutotuneOutput(
        tuned_days=tuned_days,
        final_profile=final_profile,
        baseline_profile=input_data.baseline_profile,
        eligibility={},
        day_stats=day_stats,
        prepped_days=[prepped for _, prepped in paired],
        preferences=input_data.preferences,
        pump_profile=input_data.pump_profile,
    )