"""Profile timeline resolution - ported from AAPS profile resolution logic.

Implements resolve_profile(at_ms) -> ResolvedProfile | UnknownProfile
as specified in IMPLEMENTATION_PLAN.md section 8.

Upstream commit: 1393357107a2b27ba153df31d64e745efd771ef2
Reference: AAPS Profile implementation and customization semantics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo
import json

from bganalyzer.autotune.models import ATProfile, LocalInsulin


@dataclass
class ProfileVersion:
    """Stored profile version from Nightscout."""

    remote_id: str
    revision_hash: str
    effective_from_ms: int
    profile_name: str
    timezone: str
    units_original: str
    normalized_json: dict  # Parsed profile with basal, ic, isf, targets, dia, peak
    content_hash: str


@dataclass
class ProfileActivation:
    """Profile activation record with evidence."""

    start_ms: int
    end_ms: Optional[int]
    certainty: str  # "confirmed" | "inferred" | "unknown"
    origin: str  # "profile_store" | "effective_note" | "device_status"
    evidence_json: dict
    profile_version: ProfileVersion
    percentage: float = 100.0
    time_shift_minutes: int = 0


@dataclass
class ResolvedProfile:
    """Fully resolved profile at a specific timestamp."""

    source_profile_id: str
    profile_hash: str
    basal_schedule: List[Tuple[str, float]]  # (time, rate_u_hr)
    ic_schedule: List[Tuple[str, float]]
    isf_schedule: List[Tuple[str, float]]
    target_low_schedule: List[Tuple[str, float]]
    target_high_schedule: List[Tuple[str, float]]
    dia_hours: float
    peak_minutes: int
    timezone: str
    percentage: float
    time_shift_minutes: int
    activation_evidence: ProfileActivation
    is_customized: bool  # True if profile was already customized when uploaded


@dataclass
class UnknownProfile:
    """No profile could be resolved for this timestamp."""

    reason: str


class ProfileTimeline:
    """Reconstructs active profile timeline from stored versions and activations.

    Produces immutable ResolvedProfile for any timestamp.
    """

    def __init__(
        self,
        profile_versions: List[ProfileVersion],
        activations: List[ProfileActivation],
        default_timezone: str = "UTC",
    ):
        self.profile_versions = {pv.remote_id: pv for pv in profile_versions}
        self.activations = sorted(activations, key=lambda a: a.start_ms)
        self.default_timezone = default_timezone

    def resolve_profile(self, at_ms: int) -> ResolvedProfile | UnknownProfile:
        """Resolve the active profile at a specific timestamp.

        Implements AAPS profile customization semantics:
        - Profile store upload ≠ activation
        - Effective Note uploads with originalCustomizedName are activation evidence
        - Already-customized schedules are NOT rescaled by percentage/timeShift
        - Zero basal values are preserved
        """
        # Find active activation
        activation = None
        for act in self.activations:
            if act.start_ms <= at_ms and (act.end_ms is None or act.end_ms > at_ms):
                activation = act
                break

        if activation is None:
            return UnknownProfile("No profile activation covering this timestamp")

        pv = activation.profile_version
        profile_data = pv.normalized_json

        # Parse schedule from profile JSON
        basal_schedule = self._parse_schedule(profile_data.get("basal", []), "rate")
        ic_schedule = self._parse_schedule(profile_data.get("carbratio", []), "value")
        isf_schedule = self._parse_schedule(profile_data.get("sens", []), "value")
        target_low_schedule = self._parse_schedule(profile_data.get("target_low", []), "value")
        target_high_schedule = self._parse_schedule(profile_data.get("target_high", []), "value")

        # Apply percentage and time shift ONLY if profile is not already customized
        is_customized = activation.origin == "effective_note"
        percentage = activation.percentage if not is_customized else 100.0
        time_shift = activation.time_shift_minutes if not is_customized else 0

        if percentage != 100.0 or time_shift != 0:
            basal_schedule = self._apply_customization(basal_schedule, "basal", percentage, time_shift)
            ic_schedule = self._apply_customization(ic_schedule, "ic", percentage, time_shift)
            isf_schedule = self._apply_customization(isf_schedule, "isf", percentage, time_shift)
            target_low_schedule = self._apply_customization(target_low_schedule, "target", percentage, time_shift)
            target_high_schedule = self._apply_customization(target_high_schedule, "target", percentage, time_shift)

        dia = profile_data.get("dia", 5.0)
        peak = profile_data.get("peak", 75)

        return ResolvedProfile(
            source_profile_id=pv.remote_id,
            profile_hash=pv.content_hash,
            basal_schedule=basal_schedule,
            ic_schedule=ic_schedule,
            isf_schedule=isf_schedule,
            target_low_schedule=target_low_schedule,
            target_high_schedule=target_high_schedule,
            dia_hours=dia,
            peak_minutes=peak,
            timezone=pv.timezone,
            percentage=percentage,
            time_shift_minutes=time_shift,
            activation_evidence=activation,
            is_customized=is_customized,
        )

    def _parse_schedule(self, schedule: list, value_key: str) -> List[Tuple[str, float]]:
        """Parse schedule array into (time_str, value) tuples.

        Nightscout/AAPS profile schedules key entries with "value"; accept the
        legacy "rate" spelling as a fallback when the requested key is absent
        (and vice versa) rather than silently resolving real rates to 0.0.
        """
        alternate = {"rate": "value", "value": "rate"}.get(value_key)
        result = []
        for entry in schedule:
            time_str = entry.get("time", "00:00")
            value = entry.get(value_key, None)
            if value is None and alternate is not None:
                value = entry.get(alternate, 0.0)
            if value is None:
                value = 0.0
            if isinstance(value, (int, float)):
                result.append((time_str, float(value)))
        return sorted(result, key=lambda x: x[0])

    def _apply_customization(
        self,
        schedule: List[Tuple[str, float]],
        kind: str,
        percentage: float,
        time_shift_minutes: int,
    ) -> List[Tuple[str, float]]:
        """Apply percentage scaling and time shift to schedule.

        Port of AAPS blockValueBySeconds/shiftBlock semantics (verified against
        the pinned ProfileSealed/BlockExtension sources): basal scales with
        percentage/100, IC/ISF scale inversely with 100/percentage, and
        targets shift in time without scaling. Entry times shift forward by
        the time shift (equivalent to AAPS looking up schedule time minus
        shift), wrapping around midnight. Zero values stay zero naturally.
        """
        if percentage == 100.0 and time_shift_minutes == 0:
            return schedule

        result = []
        for time_str, value in schedule:
            if not isinstance(value, (int, float)):
                result.append((time_str, value))
                continue
            shifted = time_str
            if time_shift_minutes != 0:
                h, m = map(int, time_str.split(":"))
                total_minutes = (h * 60 + m + time_shift_minutes) % 1440
                shifted = f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"
            # Operation order mirrors the pinned source bit-for-bit:
            # basal `amount * percentage / 100.0`, IC/ISF `amount * 100.0 /
            # percentage`, targets shift without scaling.
            if kind == "basal":
                value = value * percentage / 100.0
            elif kind in ("ic", "isf"):
                if percentage == 0:
                    result.append((shifted, float(value)))
                    continue
                value = value * 100.0 / percentage
            result.append((shifted, float(value)))

        return sorted(result, key=lambda x: x[0])

    def get_activations_in_range(self, start_ms: int, end_ms: int) -> List[ProfileActivation]:
        """Get all activations overlapping the given range."""
        result = []
        for act in self.activations:
            act_start = act.start_ms
            act_end = act.end_ms or float('inf')
            if act_start < end_ms and act_end > start_ms:
                result.append(act)
        return result


def build_profile_timeline(
    conn,
    source_id: str,
    end_ms: int,
    start_ms: int = 0,
) -> ProfileTimeline:
    """Build ProfileTimeline from database.

    Queries profile_versions and profile_activations tables. Activations
    overlapping [start_ms, end_ms) load — including ones that already ended,
    which history resolution needs. (An older predicate required end_ms past
    the range end and hid every closed activation.)
    """
    # Load profile versions
    versions = conn.execute("""
        SELECT remote_id, revision_hash, effective_from_ms, profile_name,
               timezone, units_original, normalized_json, content_hash
        FROM profile_versions
        WHERE source_id = ? AND effective_from_ms < ?
        ORDER BY effective_from_ms
    """, (source_id, end_ms)).fetchall()

    profile_versions = []
    for row in versions:
        normalized = row["normalized_json"]
        if isinstance(normalized, str):
            try:
                normalized = json.loads(normalized)
            except (ValueError, TypeError):
                continue
        profile_versions.append(ProfileVersion(
            remote_id=row["remote_id"],
            revision_hash=row["revision_hash"],
            effective_from_ms=row["effective_from_ms"],
            profile_name=row["profile_name"],
            timezone=row["timezone"],
            units_original=row["units_original"],
            normalized_json=normalized,
            content_hash=row["content_hash"],
        ))

    # Load activations
    activations = conn.execute("""
        SELECT a.start_ms, a.end_ms, a.certainty, a.origin, a.evidence_json,
               a.percentage, a.time_shift_minutes, p.remote_id
        FROM profile_activations a
        JOIN profile_versions p ON p.id = a.profile_version_id
        WHERE p.source_id = ? AND a.start_ms < ? AND (a.end_ms IS NULL OR a.end_ms > ?)
    """, (source_id, end_ms, start_ms)).fetchall()

    activation_list = []
    for row in activations:
        pv = None
        for pv_check in profile_versions:
            if pv_check.remote_id == row["remote_id"]:
                pv = pv_check
                break
        if pv is None:
            continue
        try:
            percentage = float(row["percentage"]) if row["percentage"] not in (None, "") else 100.0
        except (ValueError, TypeError):
            percentage = 100.0
        try:
            time_shift = int(row["time_shift_minutes"]) if row["time_shift_minutes"] not in (None, "") else 0
        except (ValueError, TypeError):
            time_shift = 0
        activation_list.append(ProfileActivation(
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            certainty=row["certainty"],
            origin=row["origin"],
            evidence_json=row["evidence_json"] if row["evidence_json"] else {},
            profile_version=pv,
            percentage=percentage,
            time_shift_minutes=time_shift,
        ))

    # Derive continuous profile activations from store versions when
    # explicit profile_activations leave gaps (clinical G3 gate).
    if not activation_list and profile_versions:
        sorted_versions = sorted(profile_versions, key=lambda pv: pv.effective_from_ms)
        for idx, pv in enumerate(sorted_versions):
            act_start = pv.effective_from_ms
            act_end = sorted_versions[idx + 1].effective_from_ms if idx + 1 < len(sorted_versions) else None
            if act_start < end_ms and (act_end is None or act_end > start_ms):
                activation_list.append(ProfileActivation(
                    start_ms=act_start,
                    end_ms=act_end,
                    certainty="inferred",
                    origin="profile_store",
                    evidence_json={"derived_from_store_version": pv.remote_id, "revision": pv.revision_hash},
                    profile_version=pv,
                    percentage=100.0,
                    time_shift_minutes=0,
                ))
    else:
        # Supplement with inferred store-derived intervals for any uncovered gap
        # between explicit activations, using latest version to cover tail
        if profile_versions:
            last_version = max(profile_versions, key=lambda pv: pv.effective_from_ms)
            has_open_store = any(a.origin == "profile_store" and a.end_ms is None for a in activation_list)
            if not has_open_store:
                # If interval extends past all explicit activations, extend from last version
                last_end = max((a.end_ms or float('inf') for a in activation_list), default=0)
                if last_end < end_ms:
                    activation_list.append(ProfileActivation(
                        start_ms=last_version.effective_from_ms,
                        end_ms=None,
                        certainty="inferred",
                        origin="profile_store",
                        evidence_json={"derived_from_store_version": last_version.remote_id},
                        profile_version=last_version,
                        percentage=100.0,
                        time_shift_minutes=0,
                    ))

    return ProfileTimeline(profile_versions, activation_list)