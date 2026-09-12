"""AAPS AutotunePrep categorization logic - literal port from AutotunePrep.kt.

Upstream commit: 1393357107a2b27ba153df31d64e745efd771ef2
Reference file: plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/AutotunePrep.kt
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
from math import fabs

from bganalyzer.autotune.models import (
    ATProfile,
    BGDatum,
    CRDatum,
    PreppedGlucose,
    LocalInsulin,
    IOBComponents,
    IobTotal,
    DiaDeviation,
    PeakDeviation,
    Round,
    AutotuneCancelled,
    throw_if_cancelled,
)


# Configuration keys (matching AAPS)
class AutotuneConfig:
    """Configuration constants from AAPS preferences."""

    AUTOTUNE_TUNE_INSULIN_CURVE = "AutotuneTuneInsulinCurve"
    AUTOTUNE_CATEGORIZE_UAM_AS_BASAL = "AutotuneCategorizeUamAsBasal"
    AUTOTUNE_ADDITIONAL_LOG = "AutotuneAdditionalLog"
    APS_SMB_MIN_5MIN_CARBS_IMPACT = "ApsSmbMin5MinCarbsImpact"
    AUTOTUNE_INSULIN_CURVE = "InsulinOrefPeak"


@dataclass
class Treatment:
    """Normalized treatment record for autotune."""

    timestamp: int
    amount: float
    is_valid: bool = True
    type: str = "NORMAL"  # NORMAL, SMB, PRIMING
    is_bolus: bool = True


@dataclass
class CarbEntry:
    """Normalized carb entry for autotune."""

    timestamp: int
    amount: float
    is_valid: bool = True


@dataclass
class TempBasal:
    """Normalized temp basal for autotune."""

    timestamp: int
    duration: int
    rate: float
    is_absolute: bool
    is_valid: bool = True


@dataclass
class AutotuneIobData:
    """Container for IOB calculation data - port of AutotuneIob internal state."""

    boluses: List[Treatment] = None
    meals: List[CarbEntry] = None
    glucose: List[dict] = None  # raw glucose readings
    temp_basals: List[TempBasal] = None
    start_bg: int = 0
    end_bg: int = 0
    dia: float = 6.0

    def __post_init__(self):
        if self.boluses is None:
            self.boluses = []
        if self.meals is None:
            self.meals = []
        if self.glucose is None:
            self.glucose = []
        if self.temp_basals is None:
            self.temp_basals = []


class AutotuneIob:
    """IOB calculation for autotune - port of AAPS AutotuneIob."""

    def __init__(self, config: AutotuneIobData):
        self.config = config
        self._boluses_sorted = sorted(config.boluses, key=lambda x: -x.timestamp)
        self._meals_sorted = sorted(config.meals, key=lambda x: -x.timestamp)
        self._temp_basals_sorted = sorted(config.temp_basals, key=lambda x: -x.timestamp)

    def getIOB(self, time: int, local_insulin: LocalInsulin) -> IobTotal:
        """Get IOB at specific time - port of AutotuneIob.getIOB."""
        total = IobTotal(time)
        duration_ms = local_insulin.duration

        for bolus in self._boluses_sorted:
            if not bolus.is_valid or bolus.type == "PRIMING":
                continue
            if bolus.timestamp > time or bolus.timestamp < time - duration_ms:
                continue

            components = local_insulin.iobCalcForTreatment(bolus.amount, bolus.timestamp, time)
            total.iob += components.iob_contrib
            total.activity += components.activity_contrib

        return total.round()

    def dosed(self, start: int, end: int) -> float:
        """Calculate insulin dosed between start and end - port of AutotunePrep.dosed."""
        insulin_dosed = 0.0
        if not self._boluses_sorted:
            return 0.0

        for bolus in self._boluses_sorted:
            if bolus.amount != 0.0 and bolus.timestamp > start and bolus.timestamp <= end:
                insulin_dosed += bolus.amount

        return Round.round_to(insulin_dosed, 0.001)


def categorize_day(
    glucose_readings: List[dict],  # list of {"timestamp": int, "value": float}
    treatments: List[Treatment],
    carb_entries: List[CarbEntry],
    temp_basals: List[TempBasal],
    profile: ATProfile,
    preferences: dict,
    local_insulin: Optional[LocalInsulin] = None,
    verbose: bool = False,
    cancelled=None,
) -> Optional[PreppedGlucose]:
    """Categorize a day's glucose data for autotune - port of AutotunePrep.categorizeBGDatums.

    Args:
        glucose_readings: List of glucose readings with timestamp and value (mg/dL)
        treatments: List of insulin treatments (boluses, SMB)
        carb_entries: List of carb entries
        temp_basals: List of temp basal records
        profile: ATProfile with current settings
        preferences: Dict of preference keys
        local_insulin: LocalInsulin model (uses profile's if not provided)
        verbose: Whether to log debug output

    Returns:
        PreppedGlucose with categorized data, or None if insufficient data
    """
    if local_insulin is None:
        local_insulin = profile.localInsulin or LocalInsulin(profile.peak, profile.dia)

    # Filter valid glucose > 39 mg/dL
    glucose_data = [g for g in glucose_readings if g["value"] > 39]
    if not glucose_readings or not glucose_data:
        if verbose:
            print("[Prep] No BG value received")
        return None

    # Sort by timestamp descending (newest first)
    glucose_data.sort(key=lambda x: -x["timestamp"])

    # Bucket glucose readings (5-minute buckets)
    bucketed = _bucket_glucose(glucose_data)

    if len(bucketed) < 6:  # Need at least 6 points for i+4 lookahead
        if verbose:
            print("[Prep] Insufficient glucose data after bucketing")
        return None

    # Prepare IOB calculator
    iob_data = AutotuneIobData(
        boluses=[t for t in treatments if t.is_bolus],
        meals=carb_entries,
        glucose=glucose_readings,
        temp_basals=temp_basals,
    )
    iob_calc = AutotuneIob(iob_data)

    # Main categorization loop
    throw_if_cancelled(cancelled)
    return _categorize_loop(
        bucketed, iob_calc, profile, local_insulin, preferences, verbose, cancelled
    )


def _bucket_glucose(glucose_data: List[dict]) -> List[BGDatum]:
    """Bucket glucose readings into 5-minute intervals - port of AutotunePrep bucketing."""
    if not glucose_data:
        return []

    bucketed = []
    bucketed.append(BGDatum(date=glucose_data[0]["timestamp"], value=glucose_data[0]["value"]))
    k = 0

    for i in range(1, len(glucose_data)):
        bg_time = glucose_data[i]["timestamp"]
        last_bg_time = glucose_data[k]["timestamp"]
        elapsed_minutes = (bg_time - last_bg_time) / 60000.0

        if fabs(elapsed_minutes) >= 2:
            k = i
            bucketed.append(BGDatum(date=glucose_data[i]["timestamp"], value=glucose_data[i]["value"]))
        else:
            # Average readings within 2-minute window
            avg = bucketed[-1]
            for l in range(k, i + 1):
                avg.value += glucose_data[l]["value"]
            avg.value /= (i - k + 1)
            bucketed.append(BGDatum(date=glucose_data[i]["timestamp"], value=avg.value))

    return bucketed


def _categorize_loop(
    bucketed: List[BGDatum],
    iob_calc: AutotuneIob,
    profile: ATProfile,
    local_insulin: LocalInsulin,
    preferences: dict,
    verbose: bool,
    cancelled=None,
) -> PreppedGlucose:
    """Main categorization loop - port of AutotunePrep categorizeBGDatums main loop."""
    csf_data: List[BGDatum] = []
    isf_data: List[BGDatum] = []
    basal_data: List[BGDatum] = []
    uam_data: List[BGDatum] = []
    cr_data: List[CRDatum] = []

    min_5min_carbimpact = preferences.get(AutotuneConfig.APS_SMB_MIN_5MIN_CARBS_IMPACT, 8.0)

    meal_cob = 0.0
    meal_carbs = 0.0
    cr_carbs = 0.0
    calculating_cr = False
    absorbing = False
    uam = False
    cr_initial_iob = 0.0
    cr_initial_bg = 0.0
    cr_initial_carb_time = 0
    type_ = ""

    # Process from oldest to newest (reverse of bucketed order)
    for pos, idx in enumerate(range(len(bucketed) - 5, 0, -1)):
        if pos % 512 == 0:
            throw_if_cancelled(cancelled)
        datum = bucketed[idx]
        bg_time = datum.date

        # Process carb entries before this BG
        my_carbs = 0.0
        while iob_calc.config.meals and iob_calc.config.meals[-1].timestamp < bg_time:
            meal = iob_calc.config.meals.pop()
            if meal.amount > 0:
                meal_cob += meal.amount
                meal_carbs += meal.amount
                my_carbs = meal.amount

        # Calculate avgDelta (5-point slope)
        bg = 0.0
        avg_delta = 0.0
        if datum.value != 0.0 and bucketed[idx + 4].value != 0.0:
            bg = datum.value
            if bg < 40 or bucketed[idx + 4].value < 40:
                continue
            avg_delta = (bg - bucketed[idx + 4].value) / 4

        avg_delta = Round.round_to(avg_delta, 0.01)
        datum.avgDelta = avg_delta

        # Get ISF and current basal
        sens = profile.isf
        current_basal = profile.getBasal(bg_time)
        basal_bgi = Round.round_to(current_basal * sens / 60 * 5, 0.01)

        # Get IOB
        iob_total = iob_calc.getIOB(bg_time, local_insulin)
        bgi = Round.round_to(-iob_total.activity * sens * 5, 0.01)
        datum.bgi = bgi

        # Calculate deviation
        deviation = avg_delta - bgi

        # Set positive deviations to zero if BG < 80
        if bg < 80 and deviation > 0:
            deviation = 0.0

        deviation = Round.round_to(deviation, 0.01)
        datum.deviation = deviation

        # Carb absorption
        if meal_cob > 0:
            ci = max(deviation, min_5min_carbimpact)
            absorbed = ci * profile.ic / sens
            meal_cob = max(0.0, meal_cob - absorbed)

        # Carb ratio calculation
        if meal_cob > 0 or calculating_cr:
            cr_carbs += my_carbs
            if not calculating_cr:
                cr_initial_iob = iob_total.iob
                cr_initial_bg = datum.value
                cr_initial_carb_time = datum.date
                if verbose:
                    print(f"[Prep] CRInitialIOB: {cr_initial_iob} CRInitialBG: {cr_initial_bg} CRInitialCarbTime: {cr_initial_carb_time}")

            if meal_cob > 0 and idx > 1:
                calculating_cr = True
            elif iob_total.iob > current_basal / 2 and idx > 1:
                calculating_cr = True
            else:
                # End of CR period
                cr_end_iob = iob_total.iob
                cr_end_bg = datum.value
                cr_end_time = datum.date
                if verbose:
                    print(f"[Prep] CREndIOB: {cr_end_iob} CREndBG: {cr_end_bg} CREndTime: {cr_end_time}")

                cr_datum = CRDatum()
                cr_datum.crInitialBG = cr_initial_bg
                cr_datum.crInitialIOB = cr_initial_iob
                cr_datum.crInitialCarbTime = cr_initial_carb_time
                cr_datum.crEndBG = cr_end_bg
                cr_datum.crEndIOB = cr_end_iob
                cr_datum.crEndTime = cr_end_time
                cr_datum.crCarbs = cr_carbs

                cr_elapsed_minutes = round((cr_end_time - cr_initial_carb_time) / 60000.0)

                if cr_elapsed_minutes < 60 or (idx == 1 and meal_cob > 0):
                    if verbose:
                        print(f"[Prep] Ignoring {cr_elapsed_minutes} m CR period.")
                else:
                    cr_data.append(cr_datum)

                cr_carbs = 0.0
                calculating_cr = False

        # Categorize glucose
        if meal_cob > 0 or absorbing or meal_carbs > 0:
            # Carb absorption phase
            absorbing = (iob_total.iob < current_basal / 2) if not (deviation > 0) else True
            if not absorbing and meal_cob == 0.0:
                meal_carbs = 0.0

            if type_ != "csf":
                datum.mealAbsorption = "start"
                if verbose:
                    print(f"[Prep] start carb absorption")
            type_ = "csf"
            datum.mealCarbs = round(meal_carbs)
            csf_data.append(datum)
        else:
            # Non-carb phase
            if type_ == "csf":
                if csf_data:
                    csf_data[-1].mealAbsorption = "end"
                    if verbose:
                        print(f"[Prep] end carb absorption")

            # UAM detection
            if iob_total.iob > 2 * current_basal or deviation > 6 or uam:
                uam = deviation > 0
                if type_ != "uam":
                    datum.uamAbsorption = "start"
                    if verbose:
                        print(f"[Prep] {datum.uamAbsorption} unannounced meal absorption")
                type_ = "uam"
                uam_data.append(datum)
            else:
                if type_ == "uam":
                    if verbose:
                        print(f"[Prep] end unannounced meal absorption")

                # Basal vs ISF categorization
                if basal_bgi > -4 * bgi:
                    type_ = "basal"
                    basal_data.append(datum)
                else:
                    if avg_delta > 0 and avg_delta > -2 * bgi:
                        type_ = "basal"
                        basal_data.append(datum)
                    else:
                        type_ = "ISF"
                        isf_data.append(datum)

        if verbose:
            print(f"[Prep] mealCOB: {Round.round_to(meal_cob, 0.1)} mealCarbs: {round(meal_carbs)} "
                  f"basalBGI: {Round.round_to(basal_bgi, 0.1)} BGI: {Round.round_to(bgi, 0.1)} "
                  f"IOB: {iob_total.iob} Activity: {iob_total.activity} "
                  f"dev: {deviation} avgDelta: {avg_delta} {type_}")

    # Post-process CR data with bolus insulin
    for cr_datum in cr_data:
        cr_datum.crInsulin = iob_calc.dosed(cr_datum.crInitialCarbTime, cr_datum.crEndTime)

    # UAM categorization policy
    categorize_uam_as_basal = preferences.get(AutotuneConfig.AUTOTUNE_CATEGORIZE_UAM_AS_BASAL, False)
    if categorize_uam_as_basal:
        if verbose:
            print("[Prep] Categorizing all UAM data as basal.")
        basal_data.extend(uam_data)
    elif len(csf_data) > 12:
        if verbose:
            print("[Prep] Found at least 1h of carb: assuming meals were announced, and categorizing UAM data as basal.")
        basal_data.extend(uam_data)
    else:
        basal_len = len(basal_data)
        uam_len = len(uam_data)
        isf_len = len(isf_data)

        if 2 * basal_len < uam_len:
            if verbose:
                print(f"[Prep] Warning: too many deviations categorized as UnAnnounced Meals")
                print(f"[Prep] Adding {uam_len} UAM deviations to {basal_len} basal ones")
            basal_data.extend(uam_data)
            # Sort by deviation and keep lowest 50%
            basal_data.sort(key=lambda d: d.deviation)
            basal_data = basal_data[:len(basal_data) // 2]
            if verbose:
                print(f"[Prep] and selecting the lowest 50%, leaving {len(basal_data)} basal+UAM ones")

        if 2 * isf_len < uam_len:
            if verbose:
                print(f"[Prep] Adding {uam_len} UAM deviations to {isf_len} ISF ones")
            isf_data.extend(uam_data)
            isf_data.sort(key=lambda d: d.deviation)
            isf_data = isf_data[:len(isf_data) // 2]
            if verbose:
                print(f"[Prep] and selecting the lowest 50%, leaving {len(isf_data)} ISF+UAM ones")

    # Re-check CSF vs ISF balance
    basal_len = len(basal_data)
    isf_len = len(isf_data)
    csf_len = len(csf_data)

    if 4 * basal_len + isf_len < csf_len and isf_len < 10:
        if verbose:
            print(f"[Prep] Warning: too many deviations categorized as meals")
            print(f"[Prep] Adding {csf_len} CSF deviations to {isf_len} ISF ones")
        isf_data.extend(csf_data)
        csf_data = []

    if verbose:
        print(f"[Prep] CRData: {len(cr_data)} CSFGlucoseData: {len(csf_data)} ISFGlucoseData: {len(isf_data)} BasalGlucoseData: {len(basal_data)}")

    # Calculate insulin curve deviations if enabled
    dia_deviations = []
    peak_deviations = []

    if preferences.get(AutotuneConfig.AUTOTUNE_TUNE_INSULIN_CURVE, False):
        dia_deviations, peak_deviations = _calculate_insulin_curve_deviations(
            profile, preferences, verbose
        )

    return PreppedGlucose(
        startBG=bucketed[0].date if bucketed else 0,
        crData=cr_data,
        csfGlucoseData=csf_data,
        isfGlucoseData=isf_data,
        basalGlucoseData=basal_data,
        diaDeviations=dia_deviations,
        peakDeviations=peak_deviations,
    )


def _calculate_insulin_curve_deviations(
    profile: ATProfile,
    preferences: dict,
    verbose: bool,
) -> Tuple[List[DiaDeviation], List[PeakDeviation]]:
    """Calculate DIA and peak deviations for insulin curve tuning."""
    # This is a simplified version - full implementation would re-categorize with different curves
    # For now, return empty lists as this requires full day re-categorization
    return [], []