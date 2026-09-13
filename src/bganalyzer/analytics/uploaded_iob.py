"""Source-linked AAPS IOB observations, independent of our reconstruction model."""

import json
import math
from datetime import datetime


def _sample_time(value):
    if type(value) in (int, float) and math.isfinite(value):
        return int(value)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return int(parsed.timestamp() * 1000)
    raise ValueError("IOB sample time must be explicit and timezone-aware")


def uploaded_iob_observations(records, start, end):
    """Preserve signed values, explicit sample times and duplicate source references.

    Unknown/conflicting values are barriers, never zeros or interpolated values.
    Invalid/disappeared records cannot contribute usable IOB. The uploader's own
    model/settings remain its responsibility; these are uploaded observations.
    """
    groups = {}
    for record in records:
        try:
            value = json.loads(record["iob_json"])
            stamp = _sample_time(value.get("time"))
        except (ValueError, TypeError, AttributeError, OverflowError):
            continue
        if not start <= stamp < end:
            continue
        iob = value.get("iob")
        valid = (record["is_valid"] and not record.get("presence_unknown")
                 and type(iob) in (int, float) and math.isfinite(iob))
        groups.setdefault(stamp, []).append((record, float(iob) if valid else None))
    observations = []
    for stamp, group in sorted(groups.items()):
        values = {item[1] for item in group}
        usable = len(values) == 1 and None not in values
        observations.append({"sample_ms": stamp, "iob_u": next(iter(values)) if usable else None,
                             "status": "uploaded" if usable else "invalid_or_conflicting",
                             "source_refs": [{"remote_id": r["remote_id"], "revision_hash": r["revision_hash"]}
                                             for r, _ in sorted(group, key=lambda x: x[0]["remote_id"])]})
    return observations
