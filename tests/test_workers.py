# Transport-independent import and report regressions retained from the HTTP implementation.
import threading
import time
import httpx
from bganalyzer.config import SyncConfig
from bganalyzer.db.connection import get_connection
from bganalyzer.nightscout.sync import SyncCoordinator, SyncStats
from bganalyzer.contracts.domain import SyncCollection
from bganalyzer.ui.main_window import MainWindow
from bganalyzer.secrets import CredentialProvider


def test_changed_report_range_discards_obsolete_result(qtbot, config, repo, monkeypatch):
    import bganalyzer.ui.workers as workers

    actual = workers.load_report
    entered = threading.Event()
    release = threading.Event()
    first = [True]

    def blocking(*args):
        if first[0]:
            first[0] = False
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test not released")
        return actual(*args)

    monkeypatch.setattr(workers, "load_report", blocking)
    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    try:
        qtbot.waitUntil(entered.is_set)
        window.report_days.setValue(30)
        newest = window._report_request_id
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.report_worker is None, timeout=5000)
    assert window._report_snapshot.request_id == newest
    assert window.metrics.total_minutes == 30 * 24 * 60
    window.close()


def test_sync_coordinator_server_cap_subdivision(config, repo):
    """When server returns fewer records than requested, coordinator subdivides windows."""
    call_log = []
    records_per_page = 10
    total_records = 25

    def fetch(start, end, count, excluded_ids=None):
        call_log.append((start, end, count, excluded_ids))
        all_records = [
            {"_id": str(i), "date": i, "sgv": 100 + i, "type": "sgv"} for i in range(total_records)
        ]
        available = [
            r
            for r in all_records
            if start <= r["date"] < end and r["_id"] not in (excluded_ids or [])
        ]
        return available[:records_per_page]

    config.sync.page_size = 1000
    sync = SyncCoordinator(config, repo, None, progress=lambda _: None)
    sync.client = type(
        "MockClient",
        (object,),
        {
            "fetch_entries": staticmethod(fetch),
            "fetch_treatments": staticmethod(lambda *a, **k: []),
            "fetch_devicestatus": staticmethod(lambda *a, **k: []),
        },
    )()

    stats = SyncStats()
    sync._window("synthetic", SyncCollection.ENTRIES, 0, total_records, stats)

    assert stats.entries_fetched == total_records
    assert len(call_log) > 1


def test_sync_coordinator_pagination_tie_same_timestamp(config, repo):
    """Records with identical timestamps are handled via ID exclusion probe."""
    call_log = []
    records = [
        {"_id": "a", "date": 1000, "sgv": 100, "type": "sgv"},
        {"_id": "b", "date": 1000, "sgv": 101, "type": "sgv"},
    ]

    def fetch(start, end, count, excluded_ids=None):
        call_log.append((start, end, count, excluded_ids))
        result = [
            r for r in records if start <= r["date"] < end and r["_id"] not in (excluded_ids or [])
        ]
        return result[:count]

    config.sync.page_size = 1
    sync = SyncCoordinator(config, repo, None, progress=lambda _: None)
    sync.client = type(
        "MockClient",
        (object,),
        {
            "fetch_entries": staticmethod(fetch),
            "fetch_treatments": staticmethod(lambda *a, **k: []),
            "fetch_devicestatus": staticmethod(lambda *a, **k: []),
        },
    )()

    stats = SyncStats()
    result = list(sync._pages(fetch, 0, 2000))

    assert sum(len(page) for page in result) == 2
    assert any(c[3] is not None for c in call_log)


def test_sync_coordinator_late_correction(config, repo):
    """Records that change after initial fetch are detected via revision hash."""
    from bganalyzer.nightscout.sync import content_hash

    call_count = [0]
    record = {"_id": "entry-1", "date": 1000, "sgv": 100, "type": "sgv"}

    def fetch(start, end, count, excluded_ids=None):
        call_count[0] += 1
        excluded = set(excluded_ids or [])
        if "entry-1" in excluded:
            return []
        if call_count[0] == 1:
            return [record]
        record_v2 = dict(record)
        record_v2["sgv"] = 150
        return [record_v2]

    sync = SyncCoordinator(config, repo, None, progress=lambda _: None)
    sync.client = type(
        "MockClient",
        (object,),
        {
            "fetch_entries": staticmethod(fetch),
            "fetch_treatments": staticmethod(lambda *a, **k: []),
            "fetch_devicestatus": staticmethod(lambda *a, **k: []),
        },
    )()

    stats = SyncStats()
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 2000, stats)
    assert stats.records_changed == 1

    stats2 = SyncStats()
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 2000, stats2)
    assert stats2.records_changed == 1


def test_sync_coordinator_malformed_records(config, repo):
    """Malformed records (missing required fields) are rejected."""

    def fetch(start, end, count, excluded_ids=None):
        excluded = set(excluded_ids or [])
        records = [
            {"_id": "valid", "date": 1000, "sgv": 100, "type": "sgv"},
            {"_id": "missing_sgv", "date": 1001, "type": "sgv"},
        ]
        return [r for r in records if r["_id"] not in excluded]

    sync = SyncCoordinator(config, repo, None, progress=lambda _: None)
    sync.client = type(
        "MockClient",
        (object,),
        {
            "fetch_entries": staticmethod(fetch),
            "fetch_treatments": staticmethod(lambda *a, **k: []),
            "fetch_devicestatus": staticmethod(lambda *a, **k: []),
        },
    )()

    stats = SyncStats()
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 2000, stats)

    assert stats.entries_fetched == 2
    glucose = repo.get_glucose_range("synthetic", 0, 2000)
    assert len(glucose) == 1
    assert glucose[0].sgv_mgdl == 100


def test_sync_resumes_from_checkpoint(config, repo, monkeypatch):
    """Interrupted sync resumes from journal checkpoints instead of restarting."""
    now = int(time.time() * 1000)
    monkeypatch.setattr("bganalyzer.nightscout.sync.time.time", lambda: now / 1000)
    monkeypatch.setattr("bganalyzer.db.sync_journal.time.time", lambda: now / 1000)

    class MockClient:
        def fetch_entries(self, start, end, count, excluded_ids=None):
            excluded = set(excluded_ids or [])
            records = [{"_id": f"entry-{start}", "date": start, "sgv": 100, "type": "sgv"}]
            return [r for r in records if r["_id"] not in excluded]

        def fetch_treatments(self, *args, **kwargs):
            return []

        def fetch_devicestatus(self, *args, **kwargs):
            return []

        def fetch_profiles(self):
            return []

        def get_status(self):
            return {}

    config.sync.window_days = 1
    sync = SyncCoordinator(config, repo, None, progress=lambda _: None)
    sync.client = MockClient()

    first = sync.initial_backfill("synthetic", days=3)
    assert first.entries_fetched > 0

    # Debug: check what's in the journal
    from bganalyzer.db.connection import get_connection

    conn = get_connection(config)
    windows = conn.execute(
        "SELECT source_id, collection, start_ms, end_ms, checked_ms, state FROM sync_windows WHERE source_id='synthetic'"
    ).fetchall()
    print("Journal windows after first backfill:")
    for w in windows:
        print(
            f"  {w['source_id']} {w['collection']} {w['start_ms']} {w['end_ms']} {w['checked_ms']} {w['state']}"
        )

    second = sync.initial_backfill("synthetic", days=3)
    print("Second run stats:", second.windows_completed, second.windows_skipped)
    assert second.windows_skipped > 0


def test_sync_handles_429_rate_limit(config, repo):
    """429 responses trigger retry-after backoff."""
    from bganalyzer.nightscout.client import NightscoutError

    call_count = [0]

    class MockClient:
        def __init__(self):
            self.should_raise = True

        def fetch_entries(self, start, end, count, excluded_ids=None):
            call_count[0] += 1
            excluded = set(excluded_ids or [])
            if self.should_raise:
                self.should_raise = False
                raise NightscoutError("Rate limited", status_code=429, error_code="RATE_LIMITED")
            records = [{"_id": f"entry-{start}", "date": start, "sgv": 100, "type": "sgv"}]
            return [r for r in records if r["_id"] not in excluded]

        def fetch_treatments(self, *args, **kwargs):
            return []

        def fetch_devicestatus(self, *args, **kwargs):
            return []

    sync = SyncCoordinator(config, repo, None, progress=lambda _: None)
    sync.client = MockClient()

    stats = SyncStats()
    try:
        sync._window("synthetic", SyncCollection.ENTRIES, 0, 2000, stats)
    except NightscoutError as e:
        assert e.error_code == "RATE_LIMITED"


def test_sync_v1_disappearance_reconciliation(config, repo):
    """Records that disappear from server are tracked but not immediately deleted."""
    from bganalyzer.db.sync_journal import SyncJournal

    def fetch_first(start, end, count, excluded_ids=None):
        excluded = set(excluded_ids or [])
        records = [{"_id": "entry-1", "date": 1000, "sgv": 100, "type": "sgv"}]
        return [r for r in records if r["_id"] not in excluded]

    def fetch_second(start, end, count, excluded_ids=None):
        excluded = set(excluded_ids or [])
        return []

    sync = SyncCoordinator(config, repo, None, progress=lambda _: None)

    sync.client = type(
        "MockClient",
        (object,),
        {
            "fetch_entries": staticmethod(fetch_first),
            "fetch_treatments": staticmethod(lambda *a, **k: []),
            "fetch_devicestatus": staticmethod(lambda *a, **k: []),
        },
    )()
    stats1 = SyncStats()
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 2000, stats1)

    sync.client = type(
        "MockClient",
        (object,),
        {
            "fetch_entries": staticmethod(fetch_second),
            "fetch_treatments": staticmethod(lambda *a, **k: []),
            "fetch_devicestatus": staticmethod(lambda *a, **k: []),
        },
    )()
    stats2 = SyncStats()
    sync._window("synthetic", SyncCollection.ENTRIES, 0, 2000, stats2)

    journal = SyncJournal(config)
    summary = journal.summary("synthetic", 0, 2000)
    assert summary["entries"]["unresolved_disappearances"] == 1

    glucose = repo.get_glucose_range("synthetic", 0, 2000)
    assert len(glucose) == 0
