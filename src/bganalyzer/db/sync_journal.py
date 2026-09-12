"""Persistent import coverage and correction provenance, independent of the GUI."""

import json
import time
from uuid import uuid4

from bganalyzer.db.connection import get_connection, transaction

COLLECTIONS = ("entries", "treatments", "devicestatus")


def interval_gaps(start, end, covered):
    """Subtract a union of half-open intervals without treating internal holes as covered."""
    cursor = start
    gaps = []
    for lo, hi in sorted(covered):
        if hi <= cursor or lo >= end:
            continue
        if lo > cursor:
            gaps.append((cursor, min(lo, end)))
        cursor = max(cursor, min(hi, end))
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


class SyncJournal:
    def __init__(self, config):
        self.config = config

    def begin_run(self, source, start, end, now):
        run_id = str(uuid4())
        with transaction(self.config) as conn:
            conn.execute(
                "INSERT INTO sync_runs(id,source_id,requested_start_ms,requested_end_ms,started_ms,state) VALUES(?,?,?,?,?,?)",
                (run_id, source, start, end, now, "running"),
            )
        return run_id

    def finish_run(self, run_id, state, stats, now):
        with transaction(self.config) as conn:
            conn.execute(
                "UPDATE sync_runs SET state=?, finished_ms=?, stats_json=? WHERE id=?",
                (state, now, json.dumps(stats, sort_keys=True), run_id),
            )

    def recover_interrupted(self):
        with transaction(self.config) as conn:
            conn.execute(
                "UPDATE sync_runs SET state='interrupted',finished_ms=? WHERE state='running'",
                (int(time.time() * 1000),),
            )

    def missing(self, source, collection, start, end, checked_since=0, connection=None):
        conn = connection if connection is not None else get_connection(self.config)
        rows = conn.execute(
            """SELECT start_ms,end_ms FROM sync_windows
            WHERE source_id=? AND collection=? AND state='complete'
            AND checked_ms>=? AND start_ms<? AND end_ms>?""",
            (source, collection, checked_since, end, start),
        ).fetchall()
        return interval_gaps(start, end, [(r[0], r[1]) for r in rows])

    def record_window(
        self, source, collection, start, end, now, state="complete", count=0, error=None
    ):
        with transaction(self.config) as conn:
            conn.execute(
                """INSERT INTO sync_windows VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(source_id,collection,start_ms,end_ms) DO UPDATE SET
                checked_ms=excluded.checked_ms,state=excluded.state,
                record_count=excluded.record_count,error_code=excluded.error_code""",
                (source, collection, start, end, now, state, count, error),
            )
            if state != "complete":
                # An older, larger successful window must not conceal a failed re-check.
                conn.execute(
                    """UPDATE sync_windows SET state='needs_recheck'
                    WHERE source_id=? AND collection=? AND state='complete'
                    AND start_ms<? AND end_ms>?""",
                    (source, collection, end, start),
                )

    def seen(self, source, collection, remote, now):
        with transaction(self.config) as conn:
            return (
                conn.execute(
                    "UPDATE sync_disappearances SET resolved_ms=? WHERE source_id=? AND collection=? AND remote_id=? AND resolved_ms IS NULL",
                    (now, source, collection, remote),
                ).rowcount
                > 0
            )

    def reconcile(self, source, collection, start, end, seen_ids, now):
        """Absence is uncertainty, never an authoritative remote deletion."""
        with transaction(self.config) as conn:
            rows = conn.execute(
                """SELECT remote_id FROM raw_records WHERE source_id=? AND collection=?
                AND is_current=1 AND is_valid=1 AND event_ms>=? AND event_ms<?""",
                (source, collection, start, end),
            ).fetchall()
            missing = {row[0] for row in rows} - seen_ids
            changed = 0
            for remote in missing:
                row = conn.execute(
                    "SELECT resolved_ms FROM sync_disappearances WHERE source_id=? AND collection=? AND remote_id=?",
                    (source, collection, remote),
                ).fetchone()
                if row is None or row[0] is not None:
                    conn.execute(
                        """INSERT INTO sync_disappearances VALUES(?,?,?,?,NULL)
                        ON CONFLICT(source_id,collection,remote_id) DO UPDATE SET first_missing_ms=excluded.first_missing_ms,resolved_ms=NULL""",
                        (source, collection, remote, now),
                    )
                    changed += 1
            return changed

    def invalidate(self, source, start, end, now, reason):
        """Conservatively stale all source reports: profile/insulin effects can cross windows."""
        with transaction(self.config) as conn:
            conn.execute(
                "INSERT INTO data_revisions(committed_ms,affected_start_ms,affected_end_ms,reason,source_id) VALUES(?,?,?,?,?)",
                (now, start, end, reason, source),
            )
            rows = conn.execute(
                """SELECT id FROM analysis_runs WHERE (source_id=? OR source_id IS NULL)
                AND state IN ('completed','running','pending')""",
                (source,),
            ).fetchall()
            for row in rows:
                run_id = row[0]
                conn.execute(
                    "UPDATE analysis_runs SET state='stale',error_code='SOURCE_REVISED' WHERE id=?",
                    (run_id,),
                )
                recs = conn.execute(
                    "SELECT id FROM recommendations WHERE run_id=? AND state IN ('draft','ready_for_review','discussed')",
                    (run_id,),
                ).fetchall()
                for rec in recs:
                    conn.execute("UPDATE recommendations SET state='stale' WHERE id=?", (rec[0],))
                    conn.execute(
                        "INSERT INTO recommendation_events VALUES(?,?,?,?,?)",
                        (
                            str(uuid4()),
                            rec[0],
                            now,
                            "source_revised",
                            json.dumps({"reason": reason}),
                        ),
                    )

    def summary(self, source, start, end, connection=None):
        conn = connection if connection is not None else get_connection(self.config)
        output = {}
        for collection in COLLECTIONS:
            gaps = self.missing(source, collection, start, end, connection=conn)
            incomplete = sum(hi - lo for lo, hi in gaps)
            latest = conn.execute(
                "SELECT MAX(checked_ms) FROM sync_windows WHERE source_id=? AND collection=? AND state='complete'",
                (source, collection),
            ).fetchone()[0]
            bounds = conn.execute(
                "SELECT MIN(event_ms),MAX(event_ms),COUNT(*) FROM raw_records WHERE source_id=? AND collection=? AND is_current=1",
                (source, collection),
            ).fetchone()
            missing = conn.execute(
                "SELECT COUNT(*) FROM sync_disappearances WHERE source_id=? AND collection=? AND resolved_ms IS NULL",
                (source, collection),
            ).fetchone()[0]
            output[collection] = {
                "requested_ms": end - start,
                "processed_ms": end - start - incomplete,
                "missing_windows": gaps,
                "last_checked_ms": latest,
                "first_event_ms": bounds[0],
                "last_event_ms": bounds[1],
                "cached_records": bounds[2],
                "unresolved_disappearances": missing,
            }
        run = conn.execute(
            "SELECT state,started_ms,finished_ms,stats_json FROM sync_runs WHERE source_id=? ORDER BY started_ms DESC,id DESC LIMIT 1",
            (source,),
        ).fetchone()
        output["last_run"] = dict(run) if run else None
        return output
