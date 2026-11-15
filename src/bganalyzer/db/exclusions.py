"""Local user annotations; independent of imported records and synchronization."""
import time
from bganalyzer.analytics.calendar import day_bounds
from bganalyzer.db.connection import transaction


def set_day_exclusion(config, source_id, day, timezone, reason, active=True):
    reason = reason.strip()
    if active and not reason:
        raise ValueError("Enter a reason for excluding the day.")
    start, end = day_bounds(day, timezone)
    with transaction(config) as conn:
        if active:
            conn.execute("""INSERT INTO analysis_exclusions
                (source_id,local_date,timezone,start_ms,end_ms,reason,active,updated_ms)
                VALUES(?,?,?,?,?,?,1,?) ON CONFLICT(source_id,local_date,timezone)
                DO UPDATE SET start_ms=excluded.start_ms,end_ms=excluded.end_ms,
                reason=excluded.reason,active=1,updated_ms=excluded.updated_ms""",
                (source_id, day.isoformat(), timezone, start, end, reason, int(time.time()*1000)))
        else:
            conn.execute("""UPDATE analysis_exclusions SET active=0,updated_ms=?
                WHERE source_id=? AND local_date=? AND timezone=?""",
                (int(time.time()*1000), source_id, day.isoformat(), timezone))


def active_exclusions(conn, source_id):
    return [dict(row) for row in conn.execute(
        "SELECT * FROM analysis_exclusions WHERE source_id=? AND active=1 ORDER BY start_ms",
        (source_id,))]


def overlapping_exclusions(exclusions, start, end):
    return [item for item in exclusions if item['start_ms'] < end and item['end_ms'] > start]
