"""Deterministic report explanation with exact per-reading calculation provenance."""

import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from bganalyzer.analytics.metrics import metric_contributions


def build_report_explanation(snapshot, zone):
    metrics = snapshot.metrics
    if metrics is None:
        return {"version": 1, "text": "No imported data for this source.", "contributions": []}
    contributions = [
        dict(
            record_id=g.remote_id,
            revision=g.revision_hash,
            reading_ms=g.event_ms,
            start_ms=lo,
            end_ms=hi,
            minutes=minutes,
            glucose_mgdl=g.sgv_mgdl,
        )
        for g, lo, hi, minutes in metric_contributions(
            snapshot.readings, snapshot.start_ms, snapshot.end_ms
        )
    ]
    payload = dict(
        version=1,
        source_id=snapshot.source_id,
        data_revision=snapshot.data_revision,
        start_ms=snapshot.start_ms,
        end_ms=snapshot.end_ms,
        contributions=contributions,
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    def when(ms):
        return datetime.fromtimestamp(ms / 1000, ZoneInfo(zone)).strftime("%d %b %Y %H:%M:%S %Z")

    lines = [
        "How this report was calculated",
        f"Period: {when(snapshot.start_ms)} → {when(snapshot.end_ms)} (end exclusive).",
        "This is a calculated explanation, not AI-generated advice.",
        f"{metrics.total_readings} glucose intervals contribute to this report.",
        f"Coverage: {metrics.covered_minutes:.2f} covered minutes ÷ {metrics.total_minutes:.2f} requested minutes × 100 = {metrics.coverage_percent:.2f}%.",
        f"Missing time: {max(0,metrics.total_minutes-metrics.covered_minutes):.2f} minutes.",
        "Each valid reading represents time until the next usable reading, at most five minutes, clipped to the report boundaries. Missing time is not filled. Equal readings at the same timestamp count once; conflicting readings at the same timestamp are omitted. Records with unresolved disappearance are excluded before calculation.",
    ]
    if metrics.covered_minutes:
        for label, minutes in [
            ("Below 70 mg/dL", metrics.very_low_minutes + metrics.low_minutes),
            ("70–180 mg/dL inclusive", metrics.in_range_minutes),
            ("Above 180 mg/dL", metrics.high_minutes + metrics.very_high_minutes),
        ]:
            lines.append(
                f"{label}: {minutes:.2f} ÷ {metrics.covered_minutes:.2f} covered minutes × 100 = {100*minutes/metrics.covered_minutes:.2f}%."
            )
        lines.append(
            f"Mean glucose: sum(glucose × represented minutes) ÷ covered minutes = {metrics.mean_mgdl:.2f} mg/dL ({metrics.mean_mgdl/18:.2f} mmol/L). Each minute has equal weight; this is not the simple average of readings."
        )
        for label, key in [
            ("Lowest contributing reading", lambda row: row["glucose_mgdl"]),
            ("Highest contributing reading", lambda row: -row["glucose_mgdl"]),
        ]:
            row = min(contributions, key=key)
            lines.append(
                f"{label}: {row['glucose_mgdl']/18:.2f} mmol/L at {when(row['reading_ms'])}; represents {row['minutes']:.2f} minutes. Source ID: {row['record_id']}."
            )
    else:
        lines.append("No covered glucose time: range percentages and mean glucose are unavailable.")
    lines.extend(
        [
            "Treatment records provide context; they do not enter these glucose-only calculations. This report does not establish that a meal or insulin event caused a glucose change, and does not calculate basal, IC or ISF changes.",
            "Reference bands are report definitions, not changes to your pump targets.",
            f"Evidence fingerprint: {digest}",
            "Export summary includes the full per-reading contribution list and revision references.",
        ]
    )
    payload.update(text="\n\n".join(lines), evidence_hash=digest)
    return payload
