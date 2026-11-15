import sqlite3

import pytest

from bganalyzer.analytics.report import load_report, quality_text
from bganalyzer.contracts.analysis import AnalysisRun, RecommendationRecord
from bganalyzer.contracts.domain import (
    RecommendationFamily,
    RecommendationState,
    SyncCollection,
)
from bganalyzer.db.connection import get_connection, initialize_database
from bganalyzer.db.migrations import get_current_version, migration_001_initial
from bganalyzer.db.sync_journal import SyncJournal, interval_gaps
from bganalyzer.nightscout.client import NightscoutError
from bganalyzer.nightscout.sync import DAY, SyncCoordinator, SyncStats


class DatasetClient:
    def __init__(self, records=None, cap=1000):
        self.records = records or []
        self.cap = cap
        self.calls = []

    def get_status(self):
        return {}

    def fetch_profiles(self):
        return []

    def fetch_entries(self, start, end, count=1000, excluded_ids=None):
        self.calls.append((start, end))
        return [
            r
            for r in self.records
            if start <= r["date"] < end and r["_id"] not in (excluded_ids or [])
        ][: min(count, self.cap)]

    def fetch_treatments(self, *args, **kwargs):
        return []

    def fetch_devicestatus(self, *args, **kwargs):
        return []


def test_interval_union_preserves_holes():
    assert interval_gaps(0, 100, [(10, 30), (20, 50), (70, 90)]) == [(0, 10), (50, 70), (90, 100)]
    assert interval_gaps(0, 100, [(-10, 150)]) == []


def test_short_pages_detect_hidden_server_limit(config, repo):
    records = [{"_id": str(i), "date": i, "sgv": 100} for i in range(10)]
    client = DatasetClient(records, cap=2)
    sync = SyncCoordinator(config, repo, client)
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 10, SyncStats())
    assert len(repo.get_glucose_range("synthetic", 0, 10)) == 10
    assert SyncJournal(config).missing("synthetic", "entries", 0, 10) == []


def test_equal_timestamps_resolved_by_id_pagination(config, repo):
    records = [{"_id": str(i), "date": 1, "sgv": 100} for i in range(3)]
    client = DatasetClient(records, cap=2)
    sync = SyncCoordinator(config, repo, client)
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 2, SyncStats())
    glucose = repo.get_glucose_range("synthetic", 0, 2)
    assert len(glucose) == 3
    assert SyncJournal(config).missing("synthetic", "entries", 0, 2) == []


def test_ignored_exclusion_filter_is_rejected(config, repo):
    client = DatasetClient([{"_id": "a", "date": 1, "sgv": 100}])

    def broken(start, end, count, excluded_ids=None):
        return client.records

    sync = SyncCoordinator(config, repo, client)
    with pytest.raises(NightscoutError) as exc:
        list(sync._pages(broken, 0, 2))
    assert exc.value.error_code == "FILTER_IGNORED"


def test_missing_record_is_uncertain_then_reappears(config, repo):
    original = {"_id": "a", "date": 1, "sgv": 100}
    client = DatasetClient([original])
    sync = SyncCoordinator(config, repo, client)
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 10, SyncStats())
    client.records = []
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 10, SyncStats())
    assert repo.get_glucose_range("synthetic", 0, 10) == []
    conn = get_connection(config)
    assert conn.execute("SELECT is_valid FROM raw_records").fetchone()[0] == 1
    snapshot = load_report(config, 1, 0, 10)
    assert snapshot.metrics.covered_minutes == 0
    assert snapshot.quality["entries"]["unresolved_disappearances"] == 1
    assert "Unresolved disappeared records: 1" in quality_text(snapshot, "UTC")
    client.records = [original]
    stats = SyncStats()
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 10, stats)
    assert stats.records_changed == 1
    assert len(repo.get_glucose_range("synthetic", 0, 10)) == 1
    assert conn.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0] == 1


def test_corrected_data_stales_report_with_audit(config, repo):
    client = DatasetClient([{"_id": "a", "date": 1, "sgv": 100}])
    sync = SyncCoordinator(config, repo, client)
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 10, SyncStats())
    run = AnalysisRun(
        source_id="synthetic",
        data_revision=1,
        start_ms=0,
        end_ms=10,
        profile_hash="p",
        algorithm_version="test",
        policy_hash="p",
        input_hash="i",
        state="completed",
    )
    repo.insert_analysis_run(run)
    rec = RecommendationRecord(
        run_id=run.id,
        family=RecommendationFamily.BASAL,
        state=RecommendationState.READY_FOR_REVIEW,
        baseline_profile_hash="p",
        candidate_json="{}",
        evidence_ids_json="[]",
        eligibility_json="{}",
    )
    repo.insert_recommendation(rec)
    client.records[0]["sgv"] = 110
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 10, SyncStats())
    assert repo.get_latest_analysis_run().state == "stale"
    conn = get_connection(config)
    assert conn.execute("SELECT state FROM recommendations").fetchone()[0] == "stale"
    assert conn.execute("SELECT COUNT(*) FROM recommendation_events").fetchone()[0] == 1
    version = conn.execute("SELECT MAX(revision) FROM data_revisions").fetchone()[0]
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 10, SyncStats())
    assert conn.execute("SELECT MAX(revision) FROM data_revisions").fetchone()[0] == version


def test_resume_skips_committed_old_windows(config, repo, monkeypatch):
    config.sync.window_days = 1
    now = 10 * DAY + DAY // 2
    monkeypatch.setattr("bganalyzer.nightscout.sync.time.time", lambda: now / 1000)
    client = DatasetClient()
    conn = get_connection(config)

    def cancel():
        return conn.execute("SELECT COUNT(*) FROM sync_windows").fetchone()[0] >= 13

    sync = SyncCoordinator(config, repo, client, cancelled=cancel)
    first = sync.initial_backfill("synthetic", 5)
    assert first.cancelled
    assert first.windows_completed == 13
    sync.cancelled = lambda: False
    second = sync.initial_backfill("synthetic", 5)
    assert not second.errors and not second.cancelled
    assert second.windows_skipped >= 4
    for collection in ("entries", "treatments", "devicestatus"):
        assert sync.journal.missing("synthetic", collection, now - 5 * DAY, now) == []
    third = sync.initial_backfill("synthetic", 5, force=True)
    assert third.windows_skipped == 0


def test_historical_coverage_expires_for_reconciliation(config, repo):
    journal = SyncJournal(config)
    journal.record_window("synthetic", "entries", 0, 100, 1)
    assert journal.missing("synthetic", "entries", 0, 100) == []
    assert journal.missing("synthetic", "entries", 0, 100, checked_since=2) == [(0, 100)]


def test_failed_recheck_does_not_hide_under_large_old_success(config, repo):
    journal = SyncJournal(config)
    journal.record_window("synthetic", "entries", 0, 100, 1)
    journal.record_window("synthetic", "entries", 40, 60, 2, state="failed", error="NETWORK_ERROR")
    assert journal.missing("synthetic", "entries", 40, 60) == [(40, 60)]


def test_recover_crash_preserves_completed_windows(config, repo):
    journal = SyncJournal(config)
    run = journal.begin_run("synthetic", 0, 100, 1)
    journal.record_window("synthetic", "entries", 0, 50, 2)
    journal.recover_interrupted()
    assert journal.summary("synthetic", 0, 100)["last_run"]["state"] == "interrupted"
    assert journal.missing("synthetic", "entries", 0, 100) == [(50, 100)]


def test_existing_database_backed_up_before_upgrade(config):
    conn = get_connection(config)
    migration_001_initial(conn)
    conn.execute("INSERT INTO schema_version VALUES(1,0)")
    conn.execute("INSERT INTO sources VALUES('old','https://old.test','v1',NULL,'{}',0)")
    conn.commit()
    initialize_database(config)
    assert get_current_version(conn) == 3
    backups = list(config.data_dir.glob("before-migration-1-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as old:
        assert get_current_version(old) == 1
        assert old.execute("SELECT id FROM sources").fetchone()[0] == "old"
    assert backups[0].stat().st_mode & 0o777 == 0o600


def test_large_page_never_builds_large_exclusion_url(config, repo):
    config.sync.request_delay_seconds = 0
    records = [{"_id": f"{i:024x}", "date": i, "sgv": 100} for i in range(471)]
    client = DatasetClient(records)
    original = client.fetch_entries
    sizes = []

    def fetch(start, end, count, excluded_ids=None):
        sizes.append(len(excluded_ids or []))
        assert len(excluded_ids or []) <= 20
        return original(start, end, count, excluded_ids)

    client.fetch_entries = fetch
    sync = SyncCoordinator(config, repo, client)
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 500, SyncStats())
    assert len(repo.get_glucose_range("synthetic", 0, 500)) == 471
    assert max(sizes) <= 20


def test_persistent_server_error_stops_the_import_pass(config, repo):
    class Unavailable(DatasetClient):
        def fetch_entries(self, *args, **kwargs):
            self.calls.append("entries")
            raise NightscoutError("Server unavailable", 503, "HTTP_ERROR")

        def fetch_treatments(self, *args, **kwargs):
            pytest.fail("Do not keep requesting collections after persistent server errors")

    client = Unavailable()
    result = SyncCoordinator(config, repo, client).initial_backfill("synthetic", days=14)
    assert client.calls == ["entries"]
    assert result.error_codes == ["HTTP_ERROR"]
    assert "HTTP 503" in result.errors[0]
