"""Dated AAPS insulin observations; not an activation or insulin-action timeline.

Protocol references are pinned in reference/aaps/manifest.json. No brand inference,
preference defaults, inter-upload interpolation or DIA substitution is permitted.
"""

import json
from collections import Counter

REFERENCE_VERSION = "3.4.2.1"
PLUGIN_NAMES = {
    2: "OREF_RAPID_ACTING",
    3: "OREF_ULTRA_RAPID_ACTING",
    4: "OREF_FREE_PEAK",
    5: "OREF_LYUMJEV",
}


def insulin_configuration_observation(record):
    """Return source-linked facts even when a configuration is unsupported."""
    observation = {key: record[key] for key in ("remote_id", "revision_hash", "event_ms")}
    observation.update(
        plugin_id=None,
        plugin_name=None,
        peak_minutes=None,
        peak_origin=None,
        version=None,
        issues=[],
    )
    issues = observation["issues"]
    try:
        payload = json.loads(record["payload_json"])
    except (ValueError, TypeError):
        issues.append("malformed_device_status")
        return observation
    if not isinstance(payload, dict):
        issues.append("malformed_device_status")
        return observation
    if record.get("presence_unknown") or payload.get("isValid", True) is not True:
        issues.append("invalid_or_disappeared_upload")
        return observation
    config = payload.get("configuration")
    if not isinstance(config, dict) or not config:
        issues.append("missing_or_malformed_configuration")
        return observation
    observation["version"] = (
        config.get("version") if isinstance(config.get("version"), str) else None
    )
    plugin = config.get("insulin")
    if type(plugin) is int:
        observation["plugin_id"] = plugin
        observation["plugin_name"] = PLUGIN_NAMES.get(plugin)
    if observation["version"] != REFERENCE_VERSION:
        issues.append("unsupported_aaps_version")
    if observation["plugin_name"] is None:
        issues.append("missing_or_unknown_insulin_plugin")
    # Interpret constants only for the exact version whose source was checked.
    if issues:
        return observation
    if plugin in (2, 3):
        observation["peak_minutes"] = {2: 75, 3: 55}[plugin]
        observation["peak_origin"] = "pinned_plugin_constant"
    elif plugin == 4:
        settings = config.get("insulinConfiguration")
        peak = settings.get("insulin_oref_peak") if isinstance(settings, dict) else None
        if type(peak) is int and 35 <= peak <= 120:
            observation["peak_minutes"] = peak
            observation["peak_origin"] = "uploaded_insulinConfiguration.insulin_oref_peak"
        else:
            issues.append("missing_or_invalid_uploaded_peak")
    else:
        issues.append("unsupported_insulin_plugin")
    return observation


def insulin_configuration_evidence(records, start, end):
    """Include report uploads and the nearest preceding configuration timestamp.

    Empty configuration objects are the serializer's ordinary omitted uploads.
    Malformed or invalid nonempty uploads remain visible rather than falling back
    to an older usable configuration. Simultaneous conflicting uploads are flagged.
    """
    candidates = []
    for record in records:
        stamp = record["event_ms"]
        if stamp is None or stamp >= end:
            continue
        try:
            payload = json.loads(record["payload_json"])
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict) and payload.get("configuration") in (None, {}):
            continue
        candidates.append(record)
    prior = max((r["event_ms"] for r in candidates if r["event_ms"] < start), default=None)
    observations = [
        insulin_configuration_observation(r)
        for r in candidates
        if r["event_ms"] >= start or r["event_ms"] == prior
    ]
    observations.sort(key=lambda o: (o["event_ms"], o["remote_id"]))
    groups = {}
    for o in observations:
        groups.setdefault(o["event_ms"], []).append(o)
    for group in groups.values():
        signatures = {
            json.dumps(
                {k: o[k] for k in ("plugin_id", "peak_minutes", "version", "issues")},
                sort_keys=True,
            )
            for o in group
        }
        if len(signatures) > 1:
            for o in group:
                o["issues"].append("conflicting_simultaneous_configuration")
    return {
        "observations": observations,
        "issue_counts": dict(Counter(issue for o in observations for issue in o["issues"])),
        "resolved_peak_observations": sum(
            not o["issues"] and o["peak_minutes"] is not None for o in observations
        ),
        "historical_activation_verified": False,
    }
