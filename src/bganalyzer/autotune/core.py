"""AAPS AutotuneCore full tuning algorithm - literal port from AutotuneCore.kt.

Upstream commit: 1393357107a2b27ba153df31d64e745efd771ef2
Reference file: plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/AutotuneCore.kt
"""

from dataclasses import dataclass
from typing import List, Optional
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

from bganalyzer.autotune.models import (
    ATProfile,
    PreppedGlucose,
    BGDatum,
    CRDatum,
    Round,
    LocalInsulin,
    throw_if_cancelled,
)


@dataclass
class TunedProfile:
    """Result of tuning a single day."""
    basal: List[float]
    ic: float
    isf: float
    dia: float
    peak: int
    basal_un_tuned: List[int]
    local_insulin: LocalInsulin


def tune_day(
    prepped: PreppedGlucose,
    previous: ATProfile,
    pump_profile: ATProfile,
    preferences: dict,
    cancelled=None,
) -> TunedProfile:
    """Tune a single day - port of AutotuneCore.tuneAllTheThings.

    Args:
        prepped: PreppedGlucose with categorized data
        previous: Previous day's tuned profile (initial = baseline)
        pump_profile: Original pump profile (for bounds)
        preferences: Dict with autosens_max, autosens_min, etc.
        cancelled: Optional zero-arg callable; raises AutotuneCancelled if True.

    Returns:
        TunedProfile with updated parameters
    """
    # Copy previous day's profile as starting point
    basal_profile = previous.basal.copy()
    isf = previous.isf
    carb_ratio = previous.ic
    dia = previous.dia
    peak = previous.peak
    basal_un_tuned = previous.basalUnTuned.copy()

    pump_basal = pump_profile.basal
    pump_isf = pump_profile.isf
    pump_carb_ratio = pump_profile.ic
    pump_csf = pump_isf / pump_carb_ratio if pump_carb_ratio != 0 else 0

    # Autosens constraints
    autotune_max = preferences.get("autosens_max", 1.2)
    autotune_min = preferences.get("autosens_min", 0.7)
    min_5min_carb_impact = preferences.get("min_5min_carbimpact", 8.0)

    # ========== Tune DIA ==========
    new_dia = dia
    if prepped.diaDeviations:
        current_dia_mean_dev = prepped.diaDeviations[2].meanDeviation
        current_dia_rms_dev = prepped.diaDeviations[2].rmsDeviation

        min_mean_dev = float('inf')
        min_rms_dev = float('inf')
        mean_best = 2
        rms_best = 2

        for i, dev in enumerate(prepped.diaDeviations):
            if dev.meanDeviation < min_mean_dev:
                min_mean_dev = Round.round_to(dev.meanDeviation, 0.001)
                mean_best = i
            if dev.rmsDeviation < min_rms_dev:
                min_rms_dev = Round.round_to(dev.rmsDeviation, 0.001)
                rms_best = i

        if mean_best < 2 and rms_best < 2:
            if (prepped.diaDeviations[1].meanDeviation < current_dia_mean_dev * 0.99 and
                    prepped.diaDeviations[1].rmsDeviation < current_dia_rms_dev * 0.99):
                new_dia = prepped.diaDeviations[1].dia
        elif mean_best > 2 and rms_best > 2:
            if (prepped.diaDeviations[3].meanDeviation < current_dia_mean_dev * 0.99 and
                    prepped.diaDeviations[3].rmsDeviation < current_dia_rms_dev * 0.99):
                new_dia = prepped.diaDeviations[3].dia

        if new_dia > 12.0:
            new_dia = 12.0

    # ========== Tune Peak ==========
    new_peak = peak
    if len(prepped.peakDeviations) > 2:
        current_peak_mean_dev = prepped.peakDeviations[2].meanDeviation
        current_peak_rms_dev = prepped.peakDeviations[2].rmsDeviation

        min_mean_dev = float('inf')
        min_rms_dev = float('inf')
        mean_best = 2
        rms_best = 2

        for i, dev in enumerate(prepped.peakDeviations):
            if dev.meanDeviation < min_mean_dev:
                min_mean_dev = Round.round_to(dev.meanDeviation, 0.001)
                mean_best = i
            if dev.rmsDeviation < min_rms_dev:
                min_rms_dev = Round.round_to(dev.rmsDeviation, 0.001)
                rms_best = i

        if mean_best < 2 and rms_best < 2:
            if (prepped.peakDeviations[1].meanDeviation < current_peak_mean_dev * 0.99 and
                    prepped.peakDeviations[1].rmsDeviation < current_peak_rms_dev * 0.99):
                new_peak = prepped.peakDeviations[1].peak
        elif mean_best > 2 and rms_best > 2:
            if (prepped.peakDeviations[3].meanDeviation < current_peak_mean_dev * 0.99 and
                    prepped.peakDeviations[3].rmsDeviation < current_peak_rms_dev * 0.99):
                new_peak = prepped.peakDeviations[3].peak

    # ========== Calculate Carb Ratio (CR) ==========
    cr_total_carbs = 0.0
    cr_total_insulin = 0.0
    for cr_datum in prepped.crData:
        cr_bg_change = cr_datum.crEndBG - cr_datum.crInitialBG
        cr_insulin_req = cr_bg_change / isf if isf != 0 else 0
        cr_datum.crInsulinTotal = cr_datum.crInitialIOB + cr_datum.crInsulin + cr_insulin_req

        if cr_datum.crInsulinTotal > 0:
            cr_total_carbs += cr_datum.crCarbs
            cr_total_insulin += cr_datum.crInsulinTotal

    cr_total_insulin = Round.round_to(cr_total_insulin, 0.001)
    total_cr = 0.0
    if cr_total_insulin != 0.0:
        total_cr = Round.round_to(cr_total_carbs / cr_total_insulin, 0.001)

    # ========== Basal Tuning ==========
    hourly_basal_profile = basal_profile
    new_hourly_basal = list(hourly_basal_profile)

    # Use profile timezone for hour calculations (AAPS uses local time).
    # Each datum's hour is converted once; the hourly loop below then reuses
    # it instead of repeating one tz-aware conversion per datum per hour.
    tz = ZoneInfo(previous.timezone) if previous.timezone else ZoneInfo("UTC")
    bg_hours = [datetime.fromtimestamp(bg.date / 1000, tz).hour for bg in prepped.basalGlucoseData]

    # Calculate hourly deviations
    for hour in range(24):
        throw_if_cancelled(cancelled)
        deviations = 0.0
        for bg, bg_hour in zip(prepped.basalGlucoseData, bg_hours):
            if hour == bg_hour:
                deviations += bg.deviation

        deviations = Round.round_to(deviations, 0.001)

        # Calculate needed basal adjustment (20% of deviation/ISF)
        basal_needed = 0.2 * deviations / isf if isf != 0 else 0
        basal_needed = Round.round_to(basal_needed, 0.01)

        if basal_needed > 0:
            # Increase prior 3 hours by 1/3 of needed adjustment
            for offset in (-3, -2, -1):
                offset_hour = (hour + offset) % 24
                new_hourly_basal[offset_hour] += basal_needed / 3
                new_hourly_basal[offset_hour] = Round.round_to(new_hourly_basal[offset_hour], 0.001)
        elif basal_needed < 0:
            # Proportional decrease of prior 3 hours
            three_hour_basal = sum(new_hourly_basal[(hour + offset) % 24] for offset in (-3, -2, -1))
            if three_hour_basal == 0:
                continue
            adjustment_ratio = 1.0 + basal_needed / three_hour_basal
            for offset in (-3, -2, -1):
                offset_hour = (hour + offset) % 24
                new_hourly_basal[offset_hour] *= adjustment_ratio
                new_hourly_basal[offset_hour] = Round.round_to(new_hourly_basal[offset_hour], 0.001)

    # Apply autosens bounds
    for hour in range(24):
        max_rate = pump_basal[hour] * autotune_max
        min_rate = pump_basal[hour] * autotune_min

        if new_hourly_basal[hour] > max_rate:
            new_hourly_basal[hour] = max_rate
        elif new_hourly_basal[hour] < min_rate:
            new_hourly_basal[hour] = min_rate

        new_hourly_basal[hour] = Round.round_to(new_hourly_basal[hour], 0.001)

    # Smooth untuned hours
    last_adjusted = 0
    for hour in range(24):
        if hourly_basal_profile[hour] == new_hourly_basal[hour]:
            # Find next adjusted hour
            next_adjusted = 23
            for next_hour in range(hour, 24):
                if hourly_basal_profile[next_hour] != new_hourly_basal[next_hour]:
                    next_adjusted = next_hour
                    break

            new_hourly_basal[hour] = Round.round_to(
                0.8 * hourly_basal_profile[hour] +
                0.1 * new_hourly_basal[last_adjusted] +
                0.1 * new_hourly_basal[next_adjusted],
                0.001
            )
            basal_un_tuned[hour] += 1
        else:
            last_adjusted = hour

    basal_profile = new_hourly_basal

    # ========== CSF and CR Tuning ==========
    csf = isf / carb_ratio if carb_ratio != 0 else 0
    full_new_csf = csf
    total_deviations = 0.0
    meal_carbs = 0
    total_meal_carbs = 0
    deviations = 0.0  # Running deviations for current meal

    for bg in prepped.csfGlucoseData:
        if bg.mealAbsorption == "start":
            deviations = 0.0
            meal_carbs = bg.mealCarbs
        elif bg.mealAbsorption == "end":
            deviations += bg.deviation
            total_meal_carbs += meal_carbs
            total_deviations += deviations
        else:
            deviations += max(0 * min_5min_carb_impact, bg.deviation)
            meal_carbs = max(meal_carbs, bg.mealCarbs)

    # Handle midnight case
    if total_meal_carbs == 0:
        total_meal_carbs += meal_carbs
    if total_deviations == 0.0:
        total_deviations += deviations

    if total_meal_carbs == 0:
        full_new_csf = csf
    else:
        full_new_csf = Round.round_to(total_deviations / total_meal_carbs, 0.01)

    # 20% adjustment
    new_csf = 0.8 * csf + 0.2 * full_new_csf

    # Safety cap CSF
    if pump_csf != 0.0:
        max_csf = pump_csf * autotune_max
        min_csf = pump_csf * autotune_min
        if new_csf > max_csf:
            new_csf = max_csf
        elif new_csf < min_csf:
            new_csf = min_csf

    old_csf = Round.round_to(csf, 0.001)
    new_csf = Round.round_to(new_csf, 0.001)
    total_deviations = Round.round_to(total_deviations, 0.001)

    # CR from CSF calculation
    full_new_cr = carb_ratio if total_cr == 0.0 else total_cr

    # CR bounds
    max_cr = pump_carb_ratio * autotune_max
    if max_cr > 150:
        max_cr = 150.0
    min_cr = pump_carb_ratio * autotune_min
    if min_cr < 3:
        min_cr = 3.0

    if pump_carb_ratio != 0.0:
        if full_new_cr > max_cr:
            full_new_cr = max_cr
        elif full_new_cr < min_cr:
            full_new_cr = min_cr

    # 20% adjustment
    new_cr = 0.8 * carb_ratio + 0.2 * full_new_cr

    if pump_carb_ratio != 0.0:
        if new_cr > max_cr:
            new_cr = max_cr
        elif new_cr < min_cr:
            new_cr = min_cr

    new_cr = Round.round_to(new_cr, 0.001)

    if new_cr != 0.0:
        carb_ratio = new_cr

    # ========== ISF Tuning ==========
    isf_deviations = []
    bgis = []
    avg_deltas = []
    ratios = []

    for bg in prepped.isfGlucoseData:
        isf_deviations.append(bg.deviation)
        bgis.append(bg.bgi)
        avg_deltas.append(bg.avgDelta)
        if bg.bgi != 0:
            ratios.append(1 + bg.deviation / bg.bgi)

    new_isf = isf
    if len(isf_deviations) >= 10:
        # Sort for percentile
        isf_deviations.sort()
        bgis.sort()
        avg_deltas.sort()
        ratios.sort()

        # 50th percentile
        p50_deviation = _percentile(isf_deviations, 0.50)
        p50_bgi = _percentile(bgis, 0.50)
        p50_ratios = Round.round_to(_percentile(ratios, 0.50), 0.001)

        full_new_isf = isf * p50_ratios
        full_new_isf = Round.round_to(full_new_isf, 0.001)

        # Adjustment fraction (default 1.0 in AAPS)
        adjustment_fraction = 1.0

        # Autosens bounds for ISF
        max_isf = pump_isf / autotune_min
        min_isf = pump_isf / autotune_max

        adjusted_isf = full_new_isf if full_new_isf >= 0 else isf
        adjusted_isf = adjustment_fraction * adjusted_isf + (1 - adjustment_fraction) * pump_isf

        if adjusted_isf > max_isf:
            adjusted_isf = max_isf
        elif adjusted_isf < min_isf:
            adjusted_isf = min_isf

        new_isf = 0.8 * isf + 0.2 * adjusted_isf

        if new_isf > max_isf:
            new_isf = max_isf
        elif new_isf < min_isf:
            new_isf = min_isf

        p50_deviation = Round.round_to(p50_deviation, 0.001)
        p50_bgi = Round.round_to(p50_bgi, 0.001)
        adjusted_isf = Round.round_to(adjusted_isf, 0.001)
    else:
        p50_deviation = 0.0
        p50_bgi = 0.0
        p50_ratios = 0.0
        adjusted_isf = isf

    new_isf = Round.round_to(new_isf, 0.001)

    if new_isf != 0.0:
        isf = new_isf

    # Create new local insulin
    new_local_insulin = LocalInsulin(f"Ins_{new_peak}-{new_dia}", new_peak, new_dia)

    return TunedProfile(
        basal=basal_profile,
        ic=carb_ratio,
        isf=isf,
        dia=new_dia,
        peak=new_peak,
        basal_un_tuned=basal_un_tuned,
        local_insulin=new_local_insulin,
    )


def _percentile(sorted_list: List[float], percentile: float) -> float:
    """Calculate percentile from sorted list - port of AAPS Percentile.percentile."""
    if not sorted_list:
        return 0.0
    return sorted_list[int(len(sorted_list) * percentile)]


def run_autotune(
    analysis_days: List[PreppedGlucose],
    baseline_profile: ATProfile,
    pump_profile: ATProfile,
    preferences: dict,
    cancelled=None,
    progress=None,
) -> List[TunedProfile]:
    """Run full autotune over multiple days - port of AutotunePlugin.kt iteration.

    Args:
        analysis_days: List of PreppedGlucose for each day (chronological order)
        baseline_profile: Baseline pump profile (immutable bounds)
        pump_profile: Current pump profile (for bounds)
        preferences: Algorithm settings
        cancelled: Optional zero-arg callable; raises AutotuneCancelled if True.
        progress: Optional callable receiving (done_days, total_days).

    Returns:
        List of TunedProfile for each day
    """
    tuned_days = []
    previous = baseline_profile.copy()

    for day in analysis_days:
        throw_if_cancelled(cancelled)
        tuned = tune_day(day, previous, pump_profile, preferences, cancelled)
        tuned_days.append(tuned)
        if progress is not None:
            progress(len(tuned_days), len(analysis_days))
        # Update previous for next day
        previous = ATProfile(
            basal=tuned.basal,
            basalUnTuned=tuned.basal_un_tuned,
            ic=tuned.ic,
            isf=tuned.isf,
            dia=tuned.dia,
            peak=tuned.peak,
            isValid=True,
            from_=day.startBG,
            localInsulin=tuned.local_insulin,
            profileName=baseline_profile.profileName,
        )

    return tuned_days