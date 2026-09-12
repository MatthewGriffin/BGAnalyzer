"""Reconstruct reported temporary-basal evidence without assuming pump delivery.

Pinned wire semantics: reference/aaps/NSTemporaryBasalExtension.kt. This is an
independent interval resolver, not the legacy delivery prototype or autotune.
Unreported intervals stay unknown; endId is preserved, never used as a remote ID.
"""

import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def temporary_basal_record(record):
    """Normalize explicit wire fields. Invalid records remain diagnostic barriers."""
    try:
        payload = json.loads(record["payload_json"])
    except (TypeError, ValueError):
        return {
            "remote_id": record["remote_id"],
            "revision_hash": record["revision_hash"],
            "start_ms": record["event_ms"],
            "end_ms": None,
            "issues": ["malformed_treatment"],
            "mode": None,
            "rate": None,
            "pump_end_id": None,
        }
    if isinstance(payload, dict) and payload.get("eventType") in (
        "Suspend",
        "Resume",
        "Site Change",
        "Insulin Change",
    ):
        return {
            "remote_id": record["remote_id"],
            "revision_hash": record["revision_hash"],
            "start_ms": record["event_ms"],
            "end_ms": None,
            "issues": ["pump_transition_unresolved"],
            "mode": None,
            "rate": None,
            "pump_end_id": None,
        }
    if not isinstance(payload, dict) or payload.get("eventType") != "Temp Basal":
        return None
    result = {
        "remote_id": record["remote_id"],
        "revision_hash": record["revision_hash"],
        "start_ms": record["event_ms"],
        "end_ms": None,
        "issues": [],
        "mode": None,
        "rate": None,
        "pump_end_id": payload.get("endId"),
    }
    issues = result["issues"]
    if (
        record.get("presence_unknown")
        or not record.get("is_valid", True)
        or payload.get("isValid") is not True
    ):
        issues.append("invalid_or_unconfirmed_presence")
    duration = payload.get("durationInMilliseconds")
    if duration is not None:
        if type(duration) is not int or duration < 0:
            issues.append("invalid_duration")
        else:
            result["end_ms"] = record["event_ms"] + duration
    else:
        duration = payload.get("duration")
        if (
            not _number(duration)
            or duration < 0
            or not _number(duration * 60000)
            or duration * 60000 != int(duration * 60000)
        ):
            issues.append("missing_or_invalid_duration")
        else:
            result["end_ms"] = record["event_ms"] + int(duration * 60000)
    absolute, percent = payload.get("absolute"), payload.get("percent")
    if absolute is not None and percent is not None:
        issues.append("ambiguous_rate_fields")
    elif absolute is not None and _number(absolute) and absolute >= 0:
        result.update(mode="absolute", rate=absolute)
    elif percent is not None and _number(percent) and percent >= -100:
        result.update(mode="percent", rate=percent + 100)
    else:
        issues.append("missing_or_invalid_explicit_rate")
    # 'rate' is a compatibility snapshot and cannot replace absolute/percent.
    if payload.get("extendedEmulated") is not None:
        issues.append("extended_emulation_unresolved")
    return result


def _profile_rate(profile_interval, stamp):
    profile = profile_interval["profile"]
    local = datetime.fromtimestamp(stamp / 1000, ZoneInfo(profile["timezone"]))
    minute = local.hour * 60 + local.minute
    schedule = profile["basal"]
    selected = schedule[0]["value"]
    for item in schedule:
        hour, mins = map(int, item["time"].split(":")[:2])
        if hour * 60 + mins > minute:
            break
        selected = item["value"]
    return float(selected)


def reported_basal_segments(records, profile_intervals, start, end):
    """Resolve candidate rates across UTC, local schedule and evidence boundaries.

    Input profiles must be validated by effective_profile(). Rates describe uploads,
    not a claim that the pump delivered them. Intersections/conflicts stay unknown.
    Missing-duration records remain barriers to the report end, never zero duration.
    """
    if end <= start:
        raise ValueError("Report end must follow start")
    normalized = []
    for record in records:
        if record["event_ms"] is not None and record["event_ms"] < end:
            item = temporary_basal_record(record)
            if item is not None:
                normalized.append(item)
    boundaries = {start, end}
    starts, stops = {}, {}
    for index, item in enumerate(normalized):
        lo = max(start, item["start_ms"])
        hi = min(end, item["end_ms"] if item["end_ms"] is not None else end)
        if hi <= lo:
            continue
        boundaries.update((lo, hi))
        starts.setdefault(lo, set()).add(index)
        stops.setdefault(hi, set()).add(index)
    for profile in profile_intervals:
        boundaries.update(
            (max(start, min(end, profile["start_ms"])), max(start, min(end, profile["end_ms"])))
        )
    # UTC minute boundaries cover minute-granularity schedules and both DST folds.
    boundaries.update(range((start // 60000 + 1) * 60000, end, 60000))
    times = sorted(boundaries)
    active = set()
    segments = []
    for lo, hi in zip(times, times[1:]):
        active.difference_update(stops.get(lo, ()))
        active.update(starts.get(lo, ()))
        items = [normalized[i] for i in sorted(active)]
        refs = [{"remote_id": i["remote_id"], "revision_hash": i["revision_hash"]} for i in items]
        value = None
        profiles = [p for p in profile_intervals if p["start_ms"] <= lo < p["end_ms"]]
        profile_refs = []
        if not items:
            reason = "no_reported_temp_basal"
        elif any(i["issues"] for i in items):
            reason = "invalid_or_incomplete_temp_basal"
        elif len(items) > 1:
            reason = "overlapping_temp_basals"
        elif len(profiles) != 1:
            reason = "missing_or_conflicting_effective_profile"
        else:
            item = items[0]
            profile_refs = profiles[0]["source_refs"]
            basal = _profile_rate(profiles[0], lo)
            value = item["rate"] if item["mode"] == "absolute" else item["rate"] / 100 * basal
            reason = "reported_rate_only"
        segment = {
            "start_ms": lo,
            "end_ms": hi,
            "rate_u_h": value,
            "reason": reason,
            "source_refs": refs,
            "profile_refs": profile_refs,
            "delivery_confirmed": False,
        }
        if segments and all(
            segments[-1][k] == segment[k] for k in segment if k not in ("start_ms", "end_ms")
        ):
            segments[-1]["end_ms"] = hi
        else:
            segments.append(segment)
    return {
        "segments": segments,
        "records": normalized,
        "reported_rate_ms": sum(
            s["end_ms"] - s["start_ms"] for s in segments if s["rate_u_h"] is not None
        ),
        "delivery_verified": False,
    }
