"""Descriptive recorded-event evidence; no inferred delivery or dose advice."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

LANES = {"carbs": 4, "bolus": 3, "smb": 2, "basal": 1, "other": 0}


def event_lanes(event):
    lanes = []
    if event.carbs_g is not None and event.carbs_g > 0:
        lanes.append("carbs")
    if event.kind.value == "smb":
        lanes.append("smb")
    elif event.kind.value == "bolus":
        lanes.append("bolus")
    elif event.kind.value in ("temp_basal", "suspend", "resume"):
        lanes.append("basal")
    return lanes or ["other"]


def event_details(event, zone, presence_unknown=False):
    def when(ms):
        return datetime.fromtimestamp(ms / 1000, ZoneInfo(zone)).strftime("%d %b %Y %H:%M:%S %Z")

    lines = [
        f"Recorded event: {event.kind.value.replace('_', ' ')}",
        f"Time: {when(event.event_ms)}",
    ]
    for name, value, unit in (
        ("Recorded carbohydrates", event.carbs_g, "g"),
        ("Recorded insulin", event.insulin_u, "U"),
        ("Recorded basal rate", event.rate_u_h, "U/h"),
        ("Recorded basal percentage", event.percent, "%"),
    ):
        if value is not None:
            lines.append(f"{name}: {value} {unit}")
    if event.end_ms is not None:
        lines.append(f"Recorded end: {when(event.end_ms)}")
    lines.extend(
        [
            f"Delivery status: {event.delivery_status.value}",
            f"Record validity: {'valid' if event.valid else 'invalid'}",
        ]
    )
    if presence_unknown:
        lines.append("Presence uncertain: this record was absent from a later complete import.")
    try:
        notes = json.loads(event.attributes_json).get("notes")
    except (ValueError, AttributeError):
        notes = None
    if notes:
        lines.append(f"Notes: {notes}")
    lines.extend(
        [
            f"Source record ID: {event.remote_id}",
            f"Revision: {event.revision_hash}",
            "Recorded amounts are not confirmation of insulin delivery. Nearby glucose changes do not establish the event's effect.",
        ]
    )
    return "\n".join(lines)
