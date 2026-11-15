"""Eligibility checks for numerical candidate generation.

Implements section 11 of IMPLEMENTATION_PLAN.md - all thresholds are explicit
engineering selection rules, NOT validated medical safety guarantees.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bganalyzer.autotune.models import ATProfile
from bganalyzer.autotune.orchestration import AutotuneOutput


class EligibilityStatus(str, Enum):
    """Eligibility status codes."""

    ELIGIBLE = "eligible"
    INSUFFICIENT_DATA = "insufficient_data"
    UNSUPPORTED_CONFIGURATION = "unsupported_configuration"
    UNRESOLVED_HISTORY = "unresolved_history"
    STALE = "stale"
    VALIDATION_UNAVAILABLE = "validation_unavailable"


class ReasonCode(str, Enum):
    """Specific reason codes for eligibility decisions."""

    # Connection freshness
    CONNECTION_STALE = "CONNECTION_STALE"

    # Data completeness
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    CGM_COVERAGE_INSUFFICIENT = "CGM_COVERAGE_INSUFFICIENT"
    CGM_GAP_EXCEEDS_LIMIT = "CGM_GAP_EXCEEDS_LIMIT"
    TREATMENT_BACKFILL_INCOMPLETE = "TREATMENT_BACKFILL_INCOMPLETE"
    DELIVERY_HISTORY_UNRESOLVED = "DELIVERY_HISTORY_UNRESOLVED"
    PROFILE_HISTORY_UNRESOLVED = "PROFILE_HISTORY_UNRESOLVED"
    INSULIN_LOOKBACK_INCOMPLETE = "INSULIN_LOOKBACK_INCOMPLETE"

    # Configuration
    INSULIN_PLUGIN_UNKNOWN = "INSULIN_PLUGIN_UNKNOWN"
    INSULIN_PEAK_UNKNOWN = "INSULIN_PEAK_UNKNOWN"
    INSULIN_DIA_UNKNOWN = "INSULIN_DIA_UNKNOWN"
    AUTOTUNE_MODE_UNKNOWN = "AUTOTUNE_MODE_UNKNOWN"
    DYNAMIC_ISF_ENABLED = "DYNAMIC_ISF_ENABLED"
    UAM_MODE_UNSUPPORTED = "UAM_MODE_UNSUPPORTED"

    # Data quality
    DUPLICATE_DOSING_UNRESOLVED = "DUPLICATE_DOSING_UNRESOLVED"
    EXTENDED_BOLUS_UNSUPPORTED = "EXTENDED_BOLUS_UNSUPPORTED"
    INSULIN_SOURCE_MISMATCH = "INSULIN_SOURCE_MISMATCH"
    OFFLINE_DELIVERY_GAP = "OFFLINE_DELIVERY_GAP"
    AMBIGUOUS_PROFILE = "AMBIGUOUS_PROFILE"

    # User confirmations
    MEAL_CONFIRMATION_MISSING = "MEAL_CONFIRMATION_MISSING"
    EXCLUSION_DAY_PRESENT = "EXCLUSION_DAY_PRESENT"
    PROFILE_CHANGE_UNCONFIRMED = "PROFILE_CHANGE_UNCONFIRMED"

    # Episode support
    INSUFFICIENT_BASAL_EPISODES = "INSUFFICIENT_BASAL_EPISODES"
    INSUFFICIENT_IC_EPISODES = "INSUFFICIENT_IC_EPISODES"
    INSUFFICIENT_ISF_EPISODES = "INSUFFICIENT_ISF_EPISODES"

    # Safety
    LOW_GLUCOSE_CONTRADICTION = "LOW_GLUCOSE_CONTRADICTION"
    SENSITIVITY_UNSTABLE = "SENSITIVITY_UNSTABLE"

    # Loop-mode state unknown (descriptive-only until confirmed)
    DYNAMIC_ISF_UNKNOWN = "DYNAMIC_ISF_UNKNOWN"

    # Policy
    NO_VALIDATED_POLICY = "NO_VALIDATED_POLICY"
    POLICY_BOUNDS_EXCEEDED = "POLICY_BOUNDS_EXCEEDED"


@dataclass
class EligibilityResult:
    """Result of eligibility check."""

    status: EligibilityStatus
    reason_codes: List[ReasonCode]
    evidence_ids: List[str]
    supported_families: List[str] = field(default_factory=list)  # "basal", "ic", "isf"
    details: dict = field(default_factory=dict)


class EligibilityChecker:
    """Checks eligibility for numerical candidate generation."""

    # Thresholds from section 11
    MIN_ELIGIBLE_DAYS = 7
    MIN_CGM_COVERAGE_PCT = 90.0
    MAX_CGM_GAP_MINUTES = 20
    MIN_BASAL_EPISODE_DAYS = 5
    MIN_IC_EPISODE_DAYS = 3
    MIN_IC_EPISODES = 5
    MIN_ISF_EPISODE_DAYS = 3
    MIN_ISF_EPISODES = 5
    MAX_BG_AGE_MINUTES = 15
    LOW_GLUCOSE_THRESHOLD_MGDL = 54

    def __init__(self, config: dict = None):
        self.config = config or {}

    def check_eligibility(
        self,
        autotune_output: AutotuneOutput,
        profile_timeline,
        delivery_timeline,
        sync_quality: dict,
        glucose_readings: List[dict],
        user_confirmations: dict,
        current_time_ms: int,
        start_ms: int = None,
        end_ms: int = None,
        device_config: dict = None,
    ) -> EligibilityResult:
        """Run all eligibility checks.

        start_ms/end_ms bound the analysis interval for delivery/profile
        coverage sampling; without them those histories cannot be verified.
        glucose_readings should span the whole interval (valid readings);
        device_config carries tri-state loop modes (True/False/None unknown)
        plus the insulin plugin name when the uploads state one.
        """
        reason_codes = []
        evidence_ids = []
        supported_families = []
        details = {}
        device_config = device_config or {}

        # Check 1: Current connection freshness
        if not self._check_connection_fresh(sync_quality, current_time_ms):
            reason_codes.append(ReasonCode.CONNECTION_STALE)
            details["connection"] = "Connection not fresh enough"
        else:
            try:
                last = (sync_quality or {}).get("entries", {}).get("last_event_ms")
                details["bg_age_min"] = round((current_time_ms - last) / 60000, 1)
            except Exception:
                pass

        # Per-window CGM coverage over tuned-day windows clipped to the range.
        day_stats = list(getattr(autotune_output, "day_stats", None) or [])
        coverage = self._coverage_by_window(glucose_readings, day_stats, start_ms, end_ms)
        eligible_day_ms = sorted(
            ms
            for ms, stat in ((d["date_ms"], d) for d in day_stats)
            if stat.get("tuned") and self._window_eligible(coverage.get(ms))
        )
        if day_stats:
            details["eligible_day_starts"] = eligible_day_ms

        # Check 2: Minimum eligible days with coverage
        if day_stats and start_ms is not None and end_ms is not None:
            eligible_days = len(eligible_day_ms)
        else:
            eligible_days = self._count_eligible_days(
                autotune_output, glucose_readings, delivery_timeline, profile_timeline
            )
        details["eligible_days"] = eligible_days
        if eligible_days < self.MIN_ELIGIBLE_DAYS:
            reason_codes.append(ReasonCode.INSUFFICIENT_DATA)
            details["eligible_days"] = eligible_days

        # Check 3: CGM coverage and gaps per tuned day
        coverage_issues = self._check_cgm_coverage(day_stats, coverage)
        if coverage_issues:
            reason_codes.extend(coverage_issues)
            details["cgm_coverage"] = coverage_issues
            details["cgm_day_stats"] = {
                str(ms): {
                    "coverage_pct": round(stat["coverage_pct"], 1),
                    "max_gap_min": (
                        round(stat["max_gap_min"], 1)
                        if stat["max_gap_min"] is not None
                        else None
                    ),
                    "n": stat["n"],
                }
                for ms, stat in sorted(coverage.items())
            }

        # Check 4: Insulin configuration known
        config_issues = self._check_insulin_config(
            autotune_output.baseline_profile, device_config.get("insulin_plugin")
        )
        if config_issues:
            reason_codes.extend(config_issues)
            details["insulin_config"] = config_issues

        # Check 5: Delivery reconstruction complete
        delivery_issues = self._check_delivery_reconstruction(
            delivery_timeline, start_ms, end_ms
        )
        if delivery_issues:
            reason_codes.extend(delivery_issues)
            details["delivery"] = delivery_issues

        # Check 6: Profile activation resolved
        profile_issues = self._check_profile_resolution(
            profile_timeline, start_ms, end_ms
        )
        if profile_issues:
            reason_codes.extend(profile_issues)
            details["profile"] = profile_issues

        # Check 7: Dynamic ISF off and autosens mode known
        mode_issues = self._check_device_modes(device_config)
        if mode_issues:
            reason_codes.extend(mode_issues)
            details["device_modes"] = mode_issues
        details["device_mode_values"] = {
            "autosens_enabled": device_config.get("autosens_enabled"),
            "autosens_source": device_config.get("autosens_source"),
            "dynamic_isf": device_config.get("dynamic_isf"),
            "dynamic_isf_source": device_config.get("dynamic_isf_source"),
            "insulin_plugin": device_config.get("insulin_plugin"),
        }

        # Check 8: User meal confirmations
        if not user_confirmations.get("meals_recorded", False):
            reason_codes.append(ReasonCode.MEAL_CONFIRMATION_MISSING)

        # Check 9: Exclusion days
        exclusion_issues = self._check_exclusion_days(user_confirmations)
        if exclusion_issues:
            reason_codes.extend(exclusion_issues)

        # Check 10: Unconfirmed profile changes
        if self._has_unconfirmed_profile_changes(profile_timeline):
            reason_codes.append(ReasonCode.PROFILE_CHANGE_UNCONFIRMED)

        # Check 11: Episode support per family from reference categorization
        episode_support = self._check_episode_support(
            autotune_output, set(eligible_day_ms) if day_stats else None
        )
        details["episode_support"] = {
            key: value for key, value in episode_support.items() if isinstance(value, bool)
        }
        day_stats_all = list(getattr(autotune_output, "day_stats", None) or [])
        if day_stats_all:
            details["episode_counts"] = self._support_counts(
                day_stats_all, set(eligible_day_ms)
            )
            isf_note = episode_support.get("isf_limitation")
            if isf_note:
                details["isf_limitation"] = isf_note
        details["episode_support"] = episode_support
        if episode_support.get("basal", False):
            supported_families.append("basal")
        if episode_support.get("ic", False):
            supported_families.append("ic")
        if episode_support.get("isf", False):
            supported_families.append("isf")

        # Check 12: Low glucose contradiction
        if self._check_low_glucose_contradiction(autotune_output, glucose_readings):
            reason_codes.append(ReasonCode.LOW_GLUCOSE_CONTRADICTION)
            values = [
                reading["value"]
                for reading in glucose_readings or []
                if reading.get("value") is not None
            ]
            if values:
                details["min_glucose_mgdl"] = min(values)

        # Check 13: Leave-one-day-out sensitivity
        sensitivity_result = self._check_sensitivity_stability(autotune_output)
        if sensitivity_result["unstable"]:
            reason_codes.append(ReasonCode.SENSITIVITY_UNSTABLE)
        details["sensitivity_ranges"] = sensitivity_result

        # Check 14: Validated policy exists
        if not self._has_validated_policy():
            reason_codes.append(ReasonCode.NO_VALIDATED_POLICY)

        # Determine overall status
        status = self._determine_status(reason_codes, eligible_days, supported_families)

        return EligibilityResult(
            status=status,
            reason_codes=reason_codes,
            evidence_ids=evidence_ids,
            supported_families=supported_families,
            details=details,
        )

    def _check_connection_fresh(self, sync_quality: dict, current_time_ms: int) -> bool:
        """Check 1: newest cached glucose is at most 15 minutes old.

        Fail closed on missing timestamps or clock skew (future-dated newest
        reading). Historical reports are viewable but never current advice.
        """
        try:
            last = (sync_quality or {}).get("entries", {}).get("last_event_ms")
            if not isinstance(last, (int, float)):
                return False
            age_min = (current_time_ms - last) / 60000
            return 0 <= age_min <= self.MAX_BG_AGE_MINUTES
        except Exception:
            return False

    @staticmethod
    def _window_coverage(readings: List[dict], lo_ms: int, hi_ms: int) -> dict:
        """5-minute carry-forward coverage inside one clipped day window.

        Each valid reading covers forward until the next reading, five
        minutes, or the window end, matching the report metrics model. Days
        without readings score 0%; gaps are consecutive-reading gaps, so a
        leading/trailing data void shows up in coverage instead.
        """
        if hi_ms <= lo_ms:
            return {"coverage_pct": 0.0, "max_gap_min": None, "n": 0}
        ts = sorted(r["timestamp"] for r in readings if lo_ms <= r["timestamp"] < hi_ms)
        if not ts:
            return {"coverage_pct": 0.0, "max_gap_min": None, "n": 0}
        covered_ms = 0.0
        max_gap_min = 0.0
        for i, t in enumerate(ts):
            nxt = ts[i + 1] if i + 1 < len(ts) else hi_ms
            if i:
                max_gap_min = max(max_gap_min, (t - ts[i - 1]) / 60000)
            covered_ms += max(0.0, min(nxt, t + 5 * 60000, hi_ms) - t)
        span_ms = hi_ms - lo_ms
        return {
            "coverage_pct": 100.0 * covered_ms / span_ms if span_ms > 0 else 0.0,
            "max_gap_min": max_gap_min,
            "n": len(ts),
        }

    def _coverage_by_window(
        self, glucose_readings: List[dict], day_stats: List[dict],
        start_ms: int, end_ms: int,
    ) -> dict:
        """Coverage per tuned-day window clipped to the analysis range."""
        if not day_stats or start_ms is None or end_ms is None:
            return {}
        coverage = {}
        for stat in day_stats:
            if not stat.get("tuned"):
                continue
            lo = max(start_ms, stat["date_ms"])
            hi = min(end_ms, stat.get("end_ms", stat["date_ms"] + 86400000))
            coverage[stat["date_ms"]] = self._window_coverage(glucose_readings, lo, hi)
        return coverage

    def _window_eligible(self, stat) -> bool:
        """A tuned day counts when coverage is known-sufficient.

        Conservative scope note: the gap rule is applied day-wide, while the
        plan scopes it to contributing episodes. Whole-day application can
        only withhold more, never less.
        """
        if not stat:
            return False
        if stat["coverage_pct"] < self.MIN_CGM_COVERAGE_PCT:
            return False
        if stat["max_gap_min"] is not None and stat["max_gap_min"] > self.MAX_CGM_GAP_MINUTES:
            return False
        return True

    def _count_eligible_days(
        self,
        output: AutotuneOutput,
        glucose: List[dict],
        delivery,
        profile_timeline,
    ) -> int:
        """Check 2 (legacy): count tuned days without coverage gating.

        Kept for outputs without per-day statistics. Real runs carry
        day_stats, and check_eligibility gates those on measured coverage.
        """
        return len(output.tuned_days)

    def _check_cgm_coverage(self, day_stats: List[dict], coverage: dict) -> List[ReasonCode]:
        """Check 3: flag tuned days failing coverage or gap limits."""
        issues = []
        for stat in day_stats or []:
            if not stat.get("tuned"):
                continue
            window = coverage.get(stat["date_ms"])
            if window is None:
                continue
            if window["coverage_pct"] < self.MIN_CGM_COVERAGE_PCT:
                if ReasonCode.CGM_COVERAGE_INSUFFICIENT not in issues:
                    issues.append(ReasonCode.CGM_COVERAGE_INSUFFICIENT)
            if (
                window["max_gap_min"] is not None
                and window["max_gap_min"] > self.MAX_CGM_GAP_MINUTES
            ):
                if ReasonCode.CGM_GAP_EXCEEDS_LIMIT not in issues:
                    issues.append(ReasonCode.CGM_GAP_EXCEEDS_LIMIT)
        return issues

    def _check_insulin_config(
        self, profile: ATProfile, plugin_name=None
    ) -> List[ReasonCode]:
        """Check 4: insulin plugin/peak/DIA stated by evidence, never defaulted."""
        issues = []
        if profile.dia <= 0:
            issues.append(ReasonCode.INSULIN_DIA_UNKNOWN)
        if profile.peak <= 0:
            issues.append(ReasonCode.INSULIN_PEAK_UNKNOWN)
        if not plugin_name:
            issues.append(ReasonCode.INSULIN_PLUGIN_UNKNOWN)
        return issues

    def _check_delivery_reconstruction(
        self, delivery, start_ms: int = None, end_ms: int = None
    ) -> List[ReasonCode]:
        """Check 5: fail closed on unverified delivery history.

        The delivery timeline is an explicitly unverified prototype, so this
        check can only withhold, never confirm: a missing timeline or range,
        or any unknown/conflicted interval in the range, blocks numerical use.
        Assumed scheduled delivery (no temp recorded) is reported, not a
        blocker by itself; gaps in uploads are a sync-coverage matter.
        """
        from bganalyzer.timeline.insulin import DeliveryOrigin

        if delivery is None or start_ms is None or end_ms is None:
            return [ReasonCode.DELIVERY_HISTORY_UNRESOLVED]
        if end_ms <= start_ms:
            return [ReasonCode.DELIVERY_HISTORY_UNRESOLVED]
        day_ms = 86400000
        cursor = start_ms
        while cursor < end_ms:
            day_end = min(cursor + day_ms, end_ms)
            try:
                intervals = delivery.resolve_delivery(cursor, day_end)
            except Exception:
                return [ReasonCode.DELIVERY_HISTORY_UNRESOLVED]
            covered_until = cursor
            for interval in sorted(intervals, key=lambda interval: interval.start_ms):
                if interval.start_ms > covered_until:
                    return [ReasonCode.DELIVERY_HISTORY_UNRESOLVED]
                covered_until = max(covered_until, interval.end_ms)
                if interval.origin == DeliveryOrigin.UNKNOWN or interval.quality in (
                    "uncertain",
                    "conflicted",
                ):
                    return [ReasonCode.DELIVERY_HISTORY_UNRESOLVED]
            if covered_until < day_end:
                return [ReasonCode.DELIVERY_HISTORY_UNRESOLVED]
            cursor = day_end
        return []

    def _check_profile_resolution(
        self, profile_timeline, start_ms: int = None, end_ms: int = None
    ) -> List[ReasonCode]:
        """Check 6: activation evidence must cover the analysis range exactly.

        Uses the timeline's activation intervals (not sampling) so even a
        short gap in the evidence blocks numerical use.
        """
        if profile_timeline is None or start_ms is None or end_ms is None:
            return [ReasonCode.PROFILE_HISTORY_UNRESOLVED]
        if end_ms <= start_ms:
            return [ReasonCode.PROFILE_HISTORY_UNRESOLVED]
        try:
            spans = sorted(
                (max(start_ms, act.start_ms), min(end_ms, act.end_ms or end_ms))
                for act in profile_timeline.get_activations_in_range(start_ms, end_ms)
            )
        except Exception:
            return [ReasonCode.PROFILE_HISTORY_UNRESOLVED]
        cursor = start_ms
        for lo, hi in spans:
            if hi <= lo:
                continue
            if lo > cursor:
                return [ReasonCode.PROFILE_HISTORY_UNRESOLVED]
            cursor = max(cursor, hi)
        if cursor < end_ms:
            return [ReasonCode.PROFILE_HISTORY_UNRESOLVED]
        return []

    def _check_device_modes(self, device_config: dict) -> List[ReasonCode]:
        """Check 7: autosens mode known, dynamic ISF off and known.

        Unknown modes abstain per plan: dynamic ISF on or unknown stays
        descriptive-only in v1, and an unknown autosens mode abstains.
        device_config carries tri-state values (True/False/None unknown).
        """
        issues = []
        config = device_config or {}
        if config.get("autosens_enabled") is None:
            issues.append(ReasonCode.AUTOTUNE_MODE_UNKNOWN)
        dynamic_isf = config.get("dynamic_isf")
        if dynamic_isf is True:
            issues.append(ReasonCode.DYNAMIC_ISF_ENABLED)
        elif dynamic_isf is None:
            issues.append(ReasonCode.DYNAMIC_ISF_UNKNOWN)
        return issues

    def _is_dynamic_isf_enabled(self) -> bool:
        """Legacy dynamic-ISF probe, superseded by _check_device_modes."""
        return False

    def _check_exclusion_days(self, user_confirmations: dict) -> List[ReasonCode]:
        """Check 9: Exclusion days for illness, steroids, etc."""
        issues = []
        if user_confirmations.get("illness_days"):
            issues.append(ReasonCode.EXCLUSION_DAY_PRESENT)
        return issues

    def _has_unconfirmed_profile_changes(self, profile_timeline) -> bool:
        """Check 10: Unconfirmed profile changes."""
        return False  # Placeholder

    @staticmethod
    def _support_counts(day_stats: List[dict], eligible_day_ms) -> dict:
        """Reference-categorized support counts over eligible tuned days."""
        pool = [
            stat
            for stat in day_stats
            if stat.get("tuned")
            and (eligible_day_ms is None or stat["date_ms"] in eligible_day_ms)
        ]
        basal_days = {stat["date_ms"] for stat in pool if stat.get("n_basal_data", 0) > 0}
        cr_days = {stat["date_ms"] for stat in pool if stat.get("n_cr_data", 0) > 0}
        return {
            "basal_days": len(basal_days),
            "cr_episodes": sum(stat.get("n_cr_data", 0) for stat in pool),
            "cr_days": len(cr_days),
            "isf_datums": sum(stat.get("n_isf_data", 0) for stat in pool),
        }

    def _check_episode_support(self, output: AutotuneOutput, eligible_day_ms=None) -> dict:
        """Check 11: per-family support from reference categorization.

        Basal needs basal-classified observations on five distinct days;
        scalar IC needs five carb episodes (reference CRDatum periods) on
        three days. Support is assessed on coverage-eligible days when the
        eligible set is known. ISF is never supported: the reference defines
        no correction episodes, so numeric ISF is withheld with that stated
        limitation (plan section 11).
        """
        support = {"basal": False, "ic": False, "isf": False}
        stats = list(getattr(output, "day_stats", None) or [])
        if stats:
            counts = self._support_counts(stats, eligible_day_ms)
            support["basal"] = counts["basal_days"] >= self.MIN_BASAL_EPISODE_DAYS
            support["ic"] = (
                counts["cr_episodes"] >= self.MIN_IC_EPISODES
                and counts["cr_days"] >= self.MIN_IC_EPISODE_DAYS
            )
            support["isf"] = False
            support["isf_limitation"] = (
                "reference defines no correction episodes; numeric ISF withheld"
            )
        else:
            # Legacy fallback for outputs without per-day statistics.
            num_tuned_days = len(output.tuned_days)
            support["basal"] = num_tuned_days >= self.MIN_BASAL_EPISODE_DAYS
            support["ic"] = num_tuned_days >= self.MIN_IC_EPISODE_DAYS
            support["isf"] = num_tuned_days >= self.MIN_ISF_EPISODE_DAYS
        return support

    def _check_low_glucose_contradiction(
        self, output: AutotuneOutput, glucose: List[dict]
    ) -> bool:
        """Check 12: withhold insulin increases after lows.

        An increase in insulin exposure (any basal hour up, IC down, ISF
        down versus baseline) is withheld when the range includes any valid
        BG below 54 mg/dL. Reductions pass this check; all other gates still
        apply.
        """
        try:
            final = output.final_profile
            baseline = output.baseline_profile
            increase = any(
                tuned - base > 0.001 for tuned, base in zip(final.basal, baseline.basal)
            )
            increase = increase or (final.ic < baseline.ic - 0.001)
            increase = increase or (final.isf < baseline.isf - 0.001)
        except Exception:
            return False
        if not increase:
            return False
        values = [
            reading["value"] for reading in glucose or [] if reading.get("value") is not None
        ]
        return bool(values) and min(values) < self.LOW_GLUCOSE_THRESHOLD_MGDL

    def _check_sensitivity_stability(self, output: AutotuneOutput) -> dict:
        """Check 13: Leave-one-day-out sensitivity.

        Repeats the complete algorithm excluding each included day, with the
        original baseline and chronological order. For a proposed parameter,
        every supported rerun must move in the same direction as the full run;
        if any crosses baseline or inverts direction, returns unstable=True.
        Returns unstable=False if stable (or if fewer than 2 days are present).

        Also collects per-parameter min/max ranges across all LOO reruns so
        that candidates can advertise evidence bounds.

        Returns a dict:
            {
                "unstable": bool,
                "n_reruns": int,
                "basal_ranges": {hour: {"min": float, "max": float}},
                "ic_range": {"min": float, "max": float} | None,
                "isf_range": {"min": float, "max": float} | None,
            }
        """
        _no_data = {"unstable": False, "n_reruns": 0,
                    "basal_ranges": {}, "ic_range": None, "isf_range": None}

        prepped = getattr(output, "prepped_days", None)
        baseline = getattr(output, "baseline_profile", None)
        pump = getattr(output, "pump_profile", None) or baseline
        prefs = getattr(output, "preferences", None) or {}
        final = getattr(output, "final_profile", None)

        if not prepped or not baseline or not final or len(prepped) < 2:
            return _no_data

        from bganalyzer.autotune.core import run_autotune

        # Identify which parameters changed in full run
        basal_changes = []
        for hour in range(24):
            diff = final.basal[hour] - baseline.basal[hour]
            if diff > 0.001:
                basal_changes.append((hour, 1))
            elif diff < -0.001:
                basal_changes.append((hour, -1))

        ic_change = (
            1 if (final.ic - baseline.ic > 0.001) else (-1 if (final.ic - baseline.ic < -0.001) else 0)
        )
        isf_change = (
            1 if (final.isf - baseline.isf > 0.001) else (-1 if (final.isf - baseline.isf < -0.001) else 0)
        )

        if not basal_changes and ic_change == 0 and isf_change == 0:
            return _no_data

        # Accumulate LOO basal values for range computation
        basal_loo: dict[int, list[float]] = {hour: [] for hour, _ in basal_changes}
        ic_loo: list[float] = [] if ic_change != 0 else []
        isf_loo: list[float] = [] if isf_change != 0 else []

        unstable = False

        # Every omitted day must be checked; partial reruns cannot establish stability.
        n_reruns = 0
        try:
            for i in range(len(prepped)):
                sub_prepped = [p for j, p in enumerate(prepped) if j != i]
                sub_tuned = run_autotune(sub_prepped, baseline, pump, prefs)
                if not sub_tuned:
                    unstable = True
                    continue
                sub_final = sub_tuned[-1]
                n_reruns += 1

                for hour, direction in basal_changes:
                    basal_loo[hour].append(sub_final.basal[hour])
                    sub_diff = sub_final.basal[hour] - baseline.basal[hour]
                    if direction * sub_diff < -0.001:
                        unstable = True

                if ic_change != 0:
                    ic_loo.append(sub_final.ic)
                    if ic_change * (sub_final.ic - baseline.ic) < -0.001:
                        unstable = True

                if isf_change != 0:
                    isf_loo.append(sub_final.isf)
                    if isf_change * (sub_final.isf - baseline.isf) < -0.001:
                        unstable = True
        except Exception:
            # A failed sensitivity calculation is not evidence of stability.
            unstable = True
        if n_reruns != len(prepped):
            unstable = True

        # Build per-parameter ranges from LOO values
        basal_ranges: dict = {}
        for hour, vals in basal_loo.items():
            if vals:
                basal_ranges[hour] = {"min": min(vals), "max": max(vals)}

        ic_range = None
        if ic_loo:
            ic_range = {"min": min(ic_loo), "max": max(ic_loo)}

        isf_range = None
        if isf_loo:
            isf_range = {"min": min(isf_loo), "max": max(isf_loo)}

        return {
            "unstable": unstable,
            "n_reruns": n_reruns,
            "basal_ranges": basal_ranges,
            "ic_range": ic_range,
            "isf_range": isf_range,
        }


    def _has_validated_policy(self) -> bool:
        """Check 14: Validated policy exists.

        Returns True only if a clinically validated policy is available.
        Clinical validation requires external review per IMPLEMENTATION_PLAN.md §11 / docs/CLINICAL_POLICY_REVIEW.md.
        Until review sign-off exists (policy_review.json or validated audit file), this remains False.
        """
        from bganalyzer.recommendations.policy import get_policy, validated_policy_audit
        policy = get_policy("policy-v1")
        return policy is not None and validated_policy_audit(policy)

    def _determine_status(
        self,
        reason_codes: List[ReasonCode],
        eligible_days: int,
        supported_families: List[str],
    ) -> EligibilityStatus:
        """Determine overall eligibility status."""
        if not reason_codes:
            if supported_families:
                return EligibilityStatus.ELIGIBLE
            return EligibilityStatus.INSUFFICIENT_DATA

        # Priority order
        if ReasonCode.NO_VALIDATED_POLICY in reason_codes:
            return EligibilityStatus.VALIDATION_UNAVAILABLE
        if ReasonCode.CONNECTION_STALE in reason_codes:
            return EligibilityStatus.STALE
        # Check for unsupported configuration reason codes
        unsupported_config_codes = {
            ReasonCode.INSULIN_PLUGIN_UNKNOWN,
            ReasonCode.INSULIN_PEAK_UNKNOWN,
            ReasonCode.INSULIN_DIA_UNKNOWN,
            ReasonCode.AUTOTUNE_MODE_UNKNOWN,
            ReasonCode.DYNAMIC_ISF_ENABLED,
            ReasonCode.DYNAMIC_ISF_UNKNOWN,
            ReasonCode.UAM_MODE_UNSUPPORTED,
        }
        if any(rc in unsupported_config_codes for rc in reason_codes):
            return EligibilityStatus.UNSUPPORTED_CONFIGURATION
        # Check for unresolved history reason codes
        unresolved_history_codes = {
            ReasonCode.DELIVERY_HISTORY_UNRESOLVED,
            ReasonCode.PROFILE_HISTORY_UNRESOLVED,
            ReasonCode.INSULIN_LOOKBACK_INCOMPLETE,
        }
        if any(rc in unresolved_history_codes for rc in reason_codes):
            return EligibilityStatus.UNRESOLVED_HISTORY
        if ReasonCode.CGM_COVERAGE_INSUFFICIENT in reason_codes:
            return EligibilityStatus.INSUFFICIENT_DATA
        if ReasonCode.INSUFFICIENT_DATA in reason_codes:
            return EligibilityStatus.INSUFFICIENT_DATA
        if eligible_days < self.MIN_ELIGIBLE_DAYS:
            return EligibilityStatus.INSUFFICIENT_DATA

        return EligibilityStatus.INSUFFICIENT_DATA


def check_eligibility(*args, **kwargs) -> EligibilityResult:
    """Compatibility function for legacy interface.

    Always returns validation_unavailable with no supported families
    until full eligibility pipeline is validated.
    """
    return EligibilityResult(
        status=EligibilityStatus.VALIDATION_UNAVAILABLE,
        reason_codes=[ReasonCode.NO_VALIDATED_POLICY],
        evidence_ids=[],
        supported_families=[],
        details={"note": "Full eligibility pipeline not yet validated"},
    )
