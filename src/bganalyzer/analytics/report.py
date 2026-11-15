"""Consistent cached report snapshots, loaded entirely outside the GUI thread."""

import json
from dataclasses import dataclass, field

from bganalyzer.analytics.metrics import calculate_tir_metrics
from bganalyzer.contracts.analysis import TimeInRangeMetrics
from bganalyzer.contracts.domain import GlucoseReading, TreatmentEvent
from bganalyzer.db.connection import get_connection
from bganalyzer.db.sync_journal import SyncJournal


@dataclass
class ReportSnapshot:
    request_id: int
    source_id: str | None
    start_ms: int
    end_ms: int
    readings: list[GlucoseReading] = field(default_factory=list)
    treatments: list[TreatmentEvent] = field(default_factory=list)
    treatment_count: int = 0
    metrics: TimeInRangeMetrics | None = None
    quality: dict = field(default_factory=dict)
    configuration: dict = field(default_factory=dict)
    configuration_at_ms: int | None = None
    data_revision: int = 0
    explanation: dict = field(default_factory=dict)
    graph_treatments: list[TreatmentEvent] = field(default_factory=list)
    graph_treatment_count: int = 0
    treatment_presence_unknown: set[str] = field(default_factory=set)
    graph_presence_unknown: set[str] = field(default_factory=set)
    graph_readings: list[GlucoseReading] = field(default_factory=list)
    graph_start_ms: int | None = None
    graph_end_ms: int | None = None
    iob_points: list[tuple[int, float | None]] = field(default_factory=list)
    iob_observations: list[dict] = field(default_factory=list)
    analysis_exclusions: list[dict] = field(default_factory=list)


def load_report(config, request_id, start, end):
    snapshot = ReportSnapshot(request_id, None, start, end)
    conn = get_connection(config, read_only=True)
    conn.execute("BEGIN")
    try:
        source = conn.execute(
            "SELECT id FROM sources WHERE origin=?", (config.source_origin,)
        ).fetchone()
        if source is None:
            return snapshot
        snapshot.source_id = source[0]
        from bganalyzer.db.exclusions import active_exclusions, overlapping_exclusions
        snapshot.analysis_exclusions = overlapping_exclusions(active_exclusions(conn, source[0]), start, end)
        rows = conn.execute(
            """SELECT g.* FROM glucose g WHERE source_id=? AND event_ms>=? AND event_ms<?
            AND NOT EXISTS(SELECT 1 FROM sync_disappearances d WHERE d.source_id=g.source_id
                AND d.collection='entries' AND d.remote_id=g.remote_id AND d.resolved_ms IS NULL)
            ORDER BY event_ms,remote_id""",
            (source[0], start - 300_000, end),
        ).fetchall()
        snapshot.readings = [GlucoseReading(**dict(row)) for row in rows]
        snapshot.treatment_count = conn.execute(
            "SELECT COUNT(*) FROM treatments WHERE source_id=? AND event_ms>=? AND event_ms<?",
            (source[0], start, end),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM treatments WHERE source_id=? AND event_ms>=? AND event_ms<? ORDER BY event_ms DESC,remote_id DESC LIMIT 2000",
            (source[0], start, end),
        ).fetchall()
        snapshot.treatments = [TreatmentEvent(**dict(row)) for row in rows]
        snapshot.treatment_presence_unknown = {
            row[0]
            for row in conn.execute(
                "SELECT remote_id FROM sync_disappearances WHERE source_id=? AND collection='treatments' AND resolved_ms IS NULL",
                (source[0],),
            )
        }
        snapshot.quality = SyncJournal(config).summary(source[0], start, end, connection=conn)
        row = conn.execute(
            """SELECT event_ms,configuration_json FROM device_status WHERE source_id=?
            AND event_ms<=? AND configuration_json IS NOT NULL
            AND configuration_json NOT IN ('{}','null')
            AND json_type(configuration_json)='object'
            AND EXISTS(SELECT 1 FROM json_each(configuration_json))
            AND json_extract(quality_json,'$.valid') IS NOT 0
            AND NOT EXISTS(SELECT 1 FROM sync_disappearances d WHERE d.source_id=device_status.source_id
                AND d.collection='devicestatus' AND d.remote_id=device_status.remote_id AND d.resolved_ms IS NULL)
            ORDER BY event_ms DESC LIMIT 1""",
            (source[0], end),
        ).fetchone()
        if row:
            snapshot.configuration_at_ms = row[0]
            snapshot.configuration = json.loads(row[1])
        from bganalyzer.analytics.uploaded_iob import uploaded_iob_observations
        iob_rows = conn.execute(
            """SELECT r.remote_id,r.revision_hash,r.is_valid,
            json_extract(r.payload_json,'$.openaps.iob') AS iob_json,
            EXISTS(SELECT 1 FROM sync_disappearances d WHERE d.source_id=r.source_id
                AND d.collection='devicestatus' AND d.remote_id=r.remote_id AND d.resolved_ms IS NULL) AS presence_unknown
            FROM raw_records r WHERE r.source_id=? AND r.collection='devicestatus'
            AND r.is_current=1 AND json_type(r.payload_json,'$.openaps.iob')='object'""",
            (source[0],),
        ).fetchall()
        snapshot.iob_observations = uploaded_iob_observations([dict(r) for r in iob_rows], start, end)
        snapshot.iob_points = [(o["sample_ms"], o["iob_u"]) for o in snapshot.iob_observations]
        snapshot.data_revision = conn.execute(
            "SELECT COALESCE(MAX(revision),0) FROM data_revisions"
        ).fetchone()[0]
    finally:
        conn.rollback()
    snapshot.metrics = calculate_tir_metrics(snapshot.readings, start, end)
    from bganalyzer.analytics.explanation import build_report_explanation

    snapshot.explanation = build_report_explanation(snapshot, config.ui.timezone)
    return snapshot


def quality_text(snapshot, timezone):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    def date(ms):
        return (
            datetime.fromtimestamp(ms / 1000, ZoneInfo(timezone)).strftime("%d %b %Y %H:%M %Z")
            if ms is not None
            else "not available"
        )

    if snapshot.source_id is None:
        return "No records imported for this source. Configure the connection to begin."
    sections = []
    if snapshot.analysis_exclusions:
        sections.append("Manual analysis exclusions (descriptive metrics still include these days):\n" + "\n".join(
            f"{item['local_date']} ({item['timezone']}): {item['reason']}"
            for item in snapshot.analysis_exclusions))
    run = snapshot.quality.get("last_run")
    if run:
        sections.append(
            f"Last import: {run['state']} · {date(run['finished_ms'] or run['started_ms'])}"
        )
        stats = json.loads(run["stats_json"])
        sections.append(
            f"Completed windows: {stats.get('windows_completed',0)} · Previously completed windows skipped: {stats.get('windows_skipped',0)}"
        )
        sections.extend(stats.get("errors", []))
    else:
        sections.append(
            "No import checkpoint yet. Existing records will be reconciled on the next import."
        )
    sections.append(
        "\nRequested-window coverage measures downloaded scope, not clinical-data completeness or CGM coverage."
    )
    for collection in ("entries", "treatments", "devicestatus"):
        item = snapshot.quality[collection]
        fraction = 100 * item["processed_ms"] / item["requested_ms"] if item["requested_ms"] else 0
        sections.append(
            f"\n{collection}: {fraction:.1f}% of report interval checked · {item['cached_records']} records in full local cache\n"
            f"Cached event dates: {date(item['first_event_ms'])} → {date(item['last_event_ms'])}\n"
            f"Last window checked: {date(item['last_checked_ms'])}\n"
            f"Unresolved disappeared records: {item['unresolved_disappearances']}"
        )
        for lo, hi in item["missing_windows"][:5]:
            sections.append(f"  Unchecked: {date(lo)} → {date(hi)}")
        if len(item["missing_windows"]) > 5:
            sections.append(f"  …and {len(item['missing_windows'])-5} further unchecked intervals")
    conf = snapshot.configuration
    mode = conf.get("apsConfiguration", {}).get("use_dynamic_sensitivity")
    dynamic = "enabled" if mode is True else "disabled" if mode is False else "unknown"
    sections.append(
        f"\nLatest uploaded configuration ({date(snapshot.configuration_at_ms)}):\n"
        f"AAPS version: {conf.get('version','unknown')}\nAlgorithm: {conf.get('aps','unknown')}\nDynamic ISF: {dynamic}"
    )
    sections.append(
        "\nConfiguration is a dated upload, not confirmation of current settings. "
        "An empty window does not prove there were no treatments. "
        "Disappeared glucose records are withheld from current summaries until re-observed; "
        "their original records remain preserved. Delivery, activation history, and numerical tuning remain unverified."
    )
    return "\n".join(sections)
