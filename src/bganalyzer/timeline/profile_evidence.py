"""Conservative evidence intervals from AAPS profile-switch uploads.

Two verified Nightscout serializers feed this module (pinned AndroidAPS
1393357107a2b27ba153df31d64e745efd771ef2):
* EffectiveProfileSwitchExtension uploads eventType "Note" records holding the
  already-effective profile plus original* switch metadata. Discriminator used
  by AAPS itself: presence of "originalProfileName".
* ProfileSwitchExtension uploads eventType "Profile Switch" records holding
  the UNCUSTOMIZED base profile plus the requested timeshift/percentage/
  duration. The effective profile is base customized by percentage/timeshift
  for the requested duration (verified against ProfileSealed/BlockExtension
  customization math, not re-derived here).

Records that fail validation, conflict at the same timestamp, disappear, or
lack a parseable base profile leave gaps rather than guesses. Derived rows
are evidence-graded (certainty "inferred"), never confirmed history.
"""

import json
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
import hashlib
from uuid import NAMESPACE_OID, uuid5


def effective_profile(payload):
    if not isinstance(payload, dict):
        return None
    required = (
        "originalCustomizedName",
        "originalTimeshift",
        "originalPercentage",
        "originalEnd",
        "profileJson",
    )
    if (
        payload.get("eventType") != "Note"
        or payload.get("isValid", True) is False
        or not all(key in payload for key in required)
    ):
        return None
    expiry = payload["originalEnd"]
    if (
        isinstance(expiry, bool)
        or not isinstance(expiry, (int, float))
        or not math.isfinite(expiry)
        or expiry < 0
    ):
        return None
    profile = _parse_pure_profile(payload["profileJson"])
    if profile is None:
        return None
    return profile  # Already customized. Preserve zero basal and original ISF units.


def _parse_pure_profile(profile_json, issues=None):
    """Validate a pure Nightscout profile JSON object (verified schema).

    Matches ProfileSealed.toPureNsJson output: units, dia, timezone plus
    basal/carbratio/sens schedules of {time, value} entries, first entry at
    midnight. Returns the parsed dict or None. Times below hour granularity
    are accepted (real uploads are hour-aligned); anything malformed fails.
    When issues (a list) is supplied, the first failure reason is appended
    for diagnostics; validation outcome is identical either way.
    """
    def fail(reason):
        if issues is not None:
            issues.append(reason)
        return None

    try:
        profile = profile_json
        if isinstance(profile, str):
            try:
                profile = json.loads(profile)
            except (ValueError, TypeError):
                return fail("profileJson is not parseable JSON")
        if not isinstance(profile, dict):
            return fail("profileJson is not an object")
        try:
            ZoneInfo(profile["timezone"])
        except Exception:
            return fail(f"unknown timezone {profile.get('timezone')!r}")
        if profile.get("units") not in ("mg/dl", "mmol", "mmol/L", "mg/dL"):
            return fail(f"units {profile.get('units')!r} not mg/dl or mmol")
        for field in ("basal", "carbratio", "sens"):
            schedule = profile.get(field)
            if not isinstance(schedule, list) or not schedule:
                return fail(f"{field} schedule empty or missing")
            if schedule[0].get("time") not in ("00:00", "00:00:00"):
                return fail(f"{field} does not start at midnight")
            previous = -1
            for pos, entry in enumerate(schedule):
                try:
                    parts = list(map(int, str(entry["time"]).split(":")))
                    value = Decimal(str(entry["value"]))
                except (ValueError, TypeError, AttributeError):
                    return fail(f"{field}[{pos}] has non-numeric time/value")
                if (
                    len(parts) not in (2, 3)
                    or not 0 <= parts[0] < 24
                    or not 0 <= parts[1] < 60
                    or (len(parts) == 3 and parts[2] != 0)
                ):
                    return fail(f"{field}[{pos}] bad timestamp {entry.get('time')!r}")
                minute = parts[0] * 60 + parts[1]
                if minute <= previous:
                    return fail(f"{field}[{pos}] time not increasing")
                if not value.is_finite():
                    return fail(f"{field}[{pos}] non-finite value")
                if value < 0:
                    return fail(f"{field}[{pos}] negative value")
                if field != "basal" and value == 0:
                    return fail(f"{field}[{pos}] zero value")
                previous = minute
        return profile
    except (KeyError, IndexError, AttributeError, TypeError, ValueError, InvalidOperation):
        return fail("unexpected profileJson shape")


def diagnose_switch_records(records, start, end):
    """Explain per-record switch-evidence verdicts for display.

    Returns one short line per profile-bearing upload in range: what it is
    (effective Note / requested switch / other), and either the interval it
    supports or the exact reason it barriers. Purely descriptive; uses the
    same validators as interval building (a missing isValid counts as valid,
    mirroring AAPS parsing — disappearance tracking still barriers).
    """
    lines = []
    ordered = sorted(
        (record for record in records if record.get("event_ms") is not None
         and start <= record["event_ms"] < end),
        key=lambda record: (record["event_ms"], record.get("remote_id") or ""),
    )
    for record in ordered:
        try:
            payload = json.loads(record["payload_json"])
        except (TypeError, ValueError):
            lines.append(
                f"  {record.get('remote_id')}: malformed treatment payload, ignored"
            )
            continue
        if not isinstance(payload, dict):
            lines.append(f"  {record.get('remote_id')}: payload not an object, ignored")
            continue
        stamp = datetime.fromtimestamp(record["event_ms"] / 1000, timezone.utc).strftime(
            "%d %b %H:%M"
        )
        event_type = payload.get("eventType")
        if record.get("presence_unknown") or not record.get("is_valid", True):
            lines.append(
                f"  {stamp} {event_type or 'unknown type'} ({record.get('remote_id')}): "
                "barrier, presence unconfirmed or record invalid"
            )
            continue
        if event_type == "Note" and "originalCustomizedName" in payload:
            issues: list = []
            profile = effective_profile(payload)
            if profile is None:
                _parse_pure_profile(payload.get("profileJson"), issues)
                missing = [
                    key
                    for key in (
                        "originalCustomizedName", "originalTimeshift",
                        "originalPercentage", "originalEnd", "profileJson",
                    )
                    if key not in payload
                ]
                if payload.get("isValid") is False:
                    reason = "marked invalid by uploader"
                elif missing:
                    reason = "missing keys: " + ", ".join(missing)
                elif not isinstance(payload.get("originalEnd"), (int, float)):
                    reason = "bad originalEnd expiry"
                elif issues:
                    reason = "profileJson rejected: " + issues[0]
                else:
                    reason = "rejected for an unspecified shape reason"
                lines.append(f"  {stamp} effective Note ({record.get('remote_id')}): barrier, {reason}")
            else:
                lines.append(
                    f"  {stamp} effective Note ({record.get('remote_id')}): "
                    f"supports {payload.get('originalCustomizedName')}"
                )
        elif event_type == "Profile Switch":
            switch = requested_switch(payload)
            if switch is None:
                lines.append(
                    f"  {stamp} Profile Switch ({record.get('remote_id')}): barrier, "
                    + _switch_issue(payload)
                )
            else:
                lines.append(
                    f"  {stamp} Profile Switch ({record.get('remote_id')}): supports "
                    f"{switch['name']} at {switch['percentage']}% "
                    f"for {switch['duration_ms'] // 60000} min"
                )
        else:
            lines.append(
                f"  {stamp} {event_type or 'unknown type'} ({record.get('remote_id')}): "
                "profile data present but not switch evidence, ignored"
            )
    return lines


def _switch_issue(payload):
    """First failing Profile Switch check as display text.

    Mirrors requested_switch check order so the reported reason is the one
    that actually barriered the record.
    """
    if payload.get("isValid") is False:
        return "marked invalid by uploader"
    if "profileJson" not in payload or payload["profileJson"] is None:
        return "no profileJson (Nightscout-entered switch is unresolvable here)"
    issues: list = []
    _parse_pure_profile(payload.get("profileJson"), issues)
    if issues:
        return "profileJson rejected: " + issues[0]
    percentage = payload.get("percentage", 100)
    if isinstance(percentage, bool) or not isinstance(percentage, int):
        return f"percentage {percentage!r} is not an integer"
    if not 1 <= percentage <= 1000:
        return f"percentage {percentage} outside 1..1000"
    shift = payload.get("timeshift", 0)
    if isinstance(shift, bool) or not isinstance(shift, int):
        return f"timeshift {shift!r} is not integer milliseconds"
    if shift % 3600000 != 0:
        return "timeshift not whole hours"
    duration_ms = None
    if "originalDuration" in payload and payload["originalDuration"] is not None:
        original_duration = payload["originalDuration"]
        if (
            isinstance(original_duration, bool)
            or not isinstance(original_duration, (int, float))
            or original_duration < 0
        ):
            return "bad originalDuration"
        duration_ms = int(original_duration)
    else:
        minutes = payload.get("duration")
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)):
            return f"duration {minutes!r} is not a number of minutes"
        if not math.isfinite(minutes) or minutes < 0:
            return f"duration {minutes!r} is negative"
        duration_ms = int(minutes * 60000)
    if duration_ms <= 0:
        return "zero-length switch (barrier only)"
    name = payload.get("originalProfileName") or payload.get("profile")
    if not isinstance(name, str) or not name:
        return "no profile name"
    return "rejected for an unspecified shape reason"


def requested_switch(payload):
    """Validate a requested Profile Switch record (verified serializer).

    Returns {"base": parsed uncustomized profile, "percentage": int,
    "timeshift_minutes": int, "duration_ms": int, "name": str} or None.
    Bounds (percentage 1..1000, whole-hour shifts, positive durations) are
    explicit engineering guards: absurd values must gap, never scale.
    A missing profileJson (Nightscout-entered switch) is unresolvable here
    and returns None; the record still truncates predecessors as a barrier.
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("eventType") != "Profile Switch":
        return None
    if payload.get("isValid") is False:
        return None
    if "profileJson" not in payload or payload["profileJson"] is None:
        return None
    base = _parse_pure_profile(payload["profileJson"])
    if base is None:
        return None
    percentage = payload.get("percentage", 100)
    if isinstance(percentage, bool) or not isinstance(percentage, int):
        return None
    if not 1 <= percentage <= 1000:
        return None
    shift = payload.get("timeshift", 0)
    if isinstance(shift, bool) or not isinstance(shift, int):
        return None
    if shift % 3600000 != 0:
        return None
    duration_ms = None
    original_duration = payload.get("originalDuration")
    if isinstance(original_duration, bool):
        return None
    if isinstance(original_duration, (int, float)) and math.isfinite(original_duration):
        if original_duration < 0:
            return None
        duration_ms = int(original_duration)
    else:
        minutes = payload.get("duration")
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)):
            return None
        if not math.isfinite(minutes) or minutes < 0:
            return None
        duration_ms = int(minutes * 60000)
    name = payload.get("originalProfileName") or payload.get("profile")
    if not isinstance(name, str) or not name:
        return None
    return {
        "base": base,
        "percentage": percentage,
        "timeshift_minutes": shift // 60000,
        "duration_ms": duration_ms,
        "name": name,
    }


def _entry_minute(time_str):
    parts = str(time_str).split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _lookup_24(entries, shift_minutes=0):
    """Expand a sparse schedule to 24 hourly values by wall-clock lookup.

    The value at wall-clock hour h is the entry active at schedule time
    (h:00 minus shift), mirroring BlockExtension lookup. No scaling here.
    """
    table = sorted(
        ((_entry_minute(entry["time"]), float(entry["value"])) for entry in entries),
        key=lambda item: item[0],
    )
    hours = []
    for hour in range(24):
        moment = (hour * 60 - shift_minutes) % 1440
        selected = table[0][1]
        for minute, value in table:
            if minute > moment:
                break
            selected = value
        hours.append(selected)
    return hours


def _effective_signature(profile, percentage=100, shift_minutes=0, already_effective=False):
    """Canonical effective content for equivalence comparison.

    Already-effective uploads expand identically (lookup only): re-applying
    scale arithmetic would drift the last ulp and manufacture conflicts.
    Requested switches expand with the verified AAPS operation order
    (basal `amount * percentage / 100.0`, IC/ISF `amount * 100.0 /
    percentage`), matching what AAPS itself writes into effective uploads.
    """
    if already_effective:
        basal = _lookup_24(profile["basal"])
        ic = _lookup_24(profile["carbratio"])
        isf = _lookup_24(profile["sens"])
    else:
        basal = [value * percentage / 100.0 for value in _lookup_24(profile["basal"], shift_minutes)]
        ic = [value * 100.0 / percentage for value in _lookup_24(profile["carbratio"], shift_minutes)]
        isf = [value * 100.0 / percentage for value in _lookup_24(profile["sens"], shift_minutes)]
    return json.dumps(
        {
            "basal": basal,
            "ic": ic,
            "isf": isf,
            "dia": profile.get("dia"),
            "units": profile.get("units"),
            "timezone": profile.get("timezone"),
        },
        sort_keys=True,
    )


def _effective_end(payload, stamp, report_end):
    # EPS.originalEnd is explicitly unused in pinned AAPS EPS.kt. Duration 0
    # means permanent; old upload timestamps in originalEnd must not expire it.
    duration = payload.get("originalDuration")
    if type(duration) in (int, float) and math.isfinite(duration) and duration >= 0:
        return stamp + int(duration) if duration > 0 else report_end
    expiry = payload.get("originalEnd")
    return int(expiry) if isinstance(expiry, (int, float)) and expiry > 0 else report_end


def observed_profile_intervals(records, start, end):
    """Unify effective Notes and requested switches into evidence intervals.

    Each group of simultaneous candidate uploads resolves to at most one
    interval: all-effective groups must agree on content and expiry; a lone
    requested switch contributes its base profile plus customization; mixed
    groups must agree on effective content (a switch restating the uploaded
    effective profile). Anything else — malformed, conflicting, disappeared,
    or unparseable uploads — leaves a gap. Every group timestamp truncates
    its predecessor, including groups that yield no interval.
    """
    groups = {}
    for record in records:
        if record["event_ms"] is not None and record["event_ms"] < end:
            payload = json.loads(record["payload_json"])
            event_type = payload.get("eventType")
            if event_type == "Note" and "originalCustomizedName" in payload:
                parsed = None if record.get("presence_unknown") else effective_profile(payload)
                groups.setdefault(record["event_ms"], []).append((record, "eps", parsed, payload))
            elif event_type == "Profile Switch":
                parsed = None if record.get("presence_unknown") else requested_switch(payload)
                groups.setdefault(record["event_ms"], []).append((record, "ps", parsed, payload))
    times = sorted(groups)
    intervals = []
    for index, stamp in enumerate(times):
        group = groups[stamp]
        lo = max(start, stamp)
        hi = min(end, times[index + 1] if index + 1 < len(times) else end)
        if hi <= lo:
            continue
        # Conflicting, malformed, disappeared or unparseable uploads gap.
        if any(item[2] is None for item in group):
            continue
        kinds = {item[1] for item in group}
        if kinds == {"eps"}:
            signatures = {
                (json.dumps(item[2], sort_keys=True), _effective_end(item[3], stamp, end))
                for item in group
            }
            if len(signatures) != 1:
                continue
            group = sorted(group, key=lambda item: item[0]["remote_id"])
            record, _, profile, payload = group[0]
            own_end = _effective_end(payload, stamp, end)
            intervals.append(
                _evidence_interval(
                    lo, min(hi, own_end), "eps", record, group, profile, None, 0,
                    payload.get("originalCustomizedName"),
                )
            )
        elif kinds == {"ps"}:
            signatures = {
                (
                    json.dumps(item[2]["base"], sort_keys=True),
                    item[2]["percentage"],
                    item[2]["timeshift_minutes"],
                    item[2]["duration_ms"],
                )
                for item in group
            }
            if len(signatures) != 1:
                continue
            group = sorted(group, key=lambda item: item[0]["remote_id"])
            record, _, switch, _payload = group[0]
            own_end = record["event_ms"] + switch["duration_ms"] if switch["duration_ms"] > 0 else end
            if own_end <= lo:
                continue
            intervals.append(
                _evidence_interval(
                    lo, min(hi, own_end), "ps", record, group, switch["base"],
                    switch["percentage"], switch["timeshift_minutes"], switch["name"],
                )
            )
        else:
            # Mixed effective uploads and requested switches: agree on
            # effective content or gap.
            effective = set()
            for _record, kind, data, _payload in group:
                if kind == "eps":
                    effective.add(_effective_signature(data, already_effective=True))
                else:
                    effective.add(
                        _effective_signature(
                            data["base"], data["percentage"], data["timeshift_minutes"]
                        )
                    )
            if len(effective) != 1:
                continue
            eps_members = sorted(
                (item for item in group if item[1] == "eps"),
                key=lambda item: item[0]["remote_id"],
            )
            record, _, profile, payload = eps_members[0]
            own_end = _effective_end(payload, stamp, end)
            intervals.append(
                _evidence_interval(
                    lo, min(hi, own_end), "eps", record, group, profile, None, 0,
                    payload.get("originalCustomizedName"),
                )
            )
    return _coalesce_intervals(intervals)


def _evidence_interval(lo, hi, kind, record, group, profile, percentage, shift_minutes, name):
    """One normalized evidence interval dict."""
    if hi <= lo:
        return None
    return {
        "start_ms": lo,
        "end_ms": hi,
        "kind": kind,
        "remote_id": record["remote_id"],
        "revision_hash": record["revision_hash"],
        "customized_name": name,
        "profile": profile,
        "percentage": percentage,
        "timeshift_minutes": shift_minutes,
        "source_refs": [
            {"remote_id": item[0]["remote_id"], "revision_hash": item[0]["revision_hash"]}
            for item in group
        ],
        "already_customized": kind == "eps",
        "dia_hours": profile.get("dia"),
        "insulin_plugin": None,
        "insulin_peak_minutes": None,
    }


def _coalesce_intervals(intervals):
    """Merge contiguous same-kind intervals with identical effective content.

    Repeated identical uploads (e.g. restated effective profiles) become one
    row instead of slivers; provenance unions across the merged sources.
    Cross-kind adjacency is kept separate so version identity stays clean.
    """
    merged = []
    for interval in intervals:
        if interval is None:
            continue
        if (
            merged
            and merged[-1]["kind"] == interval["kind"]
            and merged[-1]["end_ms"] == interval["start_ms"]
            and _interval_effective(merged[-1]) == _interval_effective(interval)
        ):
            merged[-1]["end_ms"] = interval["end_ms"]
            known = {ref["remote_id"] for ref in merged[-1]["source_refs"]}
            merged[-1]["source_refs"].extend(
                ref for ref in interval["source_refs"] if ref["remote_id"] not in known
            )
        else:
            merged.append(interval)
    return merged


def _interval_effective(interval):
    """Effective-content signature of a normalized interval."""
    if interval["kind"] == "eps":
        return _effective_signature(interval["profile"], already_effective=True)
    return _effective_signature(
        interval["profile"], interval["percentage"], interval["timeshift_minutes"]
    )


def profile_evidence_coverage(intervals, start, end):
    """Union candidate evidence in UTC milliseconds; never infer activation validity."""
    if end <= start:
        raise ValueError("Report end must follow start")
    spans = sorted((max(start, i["start_ms"]), min(end, i["end_ms"])) for i in intervals)
    cursor = start
    gaps = []
    for lo, hi in spans:
        if hi <= lo:
            continue
        if lo > cursor:
            gaps.append({"start_ms": cursor, "end_ms": lo})
        cursor = max(cursor, hi)
    if cursor < end:
        gaps.append({"start_ms": cursor, "end_ms": end})
    missing = sum(g["end_ms"] - g["start_ms"] for g in gaps)
    return {
        "covered_ms": end - start - missing,
        "missing_ms": missing,
        "coverage_percent": 100 * (end - start - missing) / (end - start),
        "gaps": gaps,
    }


def derive_effective_activations(repository, source_id, now_ms):
    """Rebuild inferred activation evidence from profile-switch uploads.

    Reads all current effective Note and Profile Switch records for the
    source, recomputes the conservative unified intervals over full history,
    then replaces every derived activation with the fresh set. Full recompute
    (rather than incremental patching) keeps corrections, expiries and
    disappeared uploads from leaving orphan or over-long activations: a later
    run converges to the same rows.

    Each interval becomes one profile_versions row (remote
    "effective:<id>" with already-customized content, or "switch:<id>" with
    the uncustomized base) plus one profile_activations row with certainty
    "inferred". Switch-requested activations carry the requested percentage
    and time shift, applied downstream with the verified AAPS customization
    math; already-effective uploads carry none. Conflicting, malformed or
    disappeared uploads leave gaps. The trailing interval stays open-ended
    (end_ms None) unless the upload set a positive expiry.

    Returns (version_count, activation_count). Raises on database errors so
    the caller can record the derivation failure honestly.
    """
    from decimal import Decimal

    from bganalyzer.contracts.domain import (
        ProfileActivation,
        ProfileSource,
        ProfileVersion,
        SyncCollection,
    )

    records = repository.get_profile_note_records(source_id, now_ms)
    missing = set(
        repository.list_unresolved_disappearances(source_id, SyncCollection.TREATMENTS)
    )
    records = [
        dict(row, presence_unknown=row["remote_id"] in missing or not row["is_valid"])
        for row in records
    ]
    intervals = observed_profile_intervals(records, 0, now_ms)

    versions = []
    activations = []
    for interval in intervals:
        note_remote = interval["remote_id"]
        profile = interval["profile"]
        kind = interval["kind"]
        canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"))
        if kind == "eps":
            version_remote = f"effective:{note_remote}"
            origin = ProfileSource.EFFECTIVE_NOTE
            percentage = None
            shift_minutes = 0
            evidence = {
                "source_refs": interval["source_refs"],
                "already_customized": True,
                "dia_hours": interval.get("dia_hours"),
                "derived_from": "effective_note",
            }
        else:
            version_remote = f"switch:{note_remote}"
            origin = ProfileSource.PROFILE_SWITCH
            percentage = Decimal(interval["percentage"])
            shift_minutes = interval["timeshift_minutes"]
            evidence = {
                "source_refs": interval["source_refs"],
                "already_customized": False,
                "requested_percentage": interval["percentage"],
                "requested_timeshift_minutes": interval["timeshift_minutes"],
                "dia_hours": interval.get("dia_hours"),
                "derived_from": "profile_switch",
            }
        versions.append(
            ProfileVersion(
                source_id=source_id,
                remote_id=version_remote,
                revision_hash=interval["revision_hash"],
                profile_name=interval.get("customized_name") or note_remote,
                effective_from_ms=interval["start_ms"],
                timezone=profile.get("timezone", "unknown"),
                units_original=profile.get("units", "unknown"),
                normalized_json=canonical,
                content_hash=hashlib.sha256(canonical.encode()).hexdigest(),
            )
        )
        end_ms = interval["end_ms"]
        if end_ms is not None and end_ms >= now_ms:
            end_ms = None
        activations.append(
            ProfileActivation(
                # Stable identity per source/kind/note/interval-start: reruns
                # update rows in place instead of churning them.
                id=uuid5(
                    NAMESPACE_OID,
                    f"{source_id}:{origin.value}:{note_remote}:{interval['start_ms']}",
                ),
                profile_version_id=versions[-1].id,
                start_ms=interval["start_ms"],
                end_ms=end_ms,
                percentage=percentage,
                time_shift_minutes=shift_minutes,
                origin=origin,
                evidence_json=json.dumps(evidence, sort_keys=True),
                certainty="inferred",
            )
        )

    for origin_value in (ProfileSource.EFFECTIVE_NOTE.value, ProfileSource.PROFILE_SWITCH.value):
        repository.delete_activations_by_origin(source_id, origin_value)
    version_ids = {}
    for version in versions:
        repository.upsert_profile_version(version)
        version_ids[version.remote_id] = repository.get_profile_version_id(
            source_id, version.remote_id
        )
    for activation, version in zip(activations, versions):
        activation.profile_version_id = version_ids[version.remote_id]
        repository.upsert_profile_activation(activation)
    return len(versions), len(activations)
