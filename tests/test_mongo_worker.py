import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from bganalyzer.nightscout.atlas import midnight_ms
from bganalyzer.nightscout.client import NightscoutError
from bganalyzer.secrets import CredentialProvider
from bganalyzer.ui.main_window import MainWindow
from bganalyzer.ui.workers import SyncWorker
from bganalyzer.db.connection import get_connection


@pytest.fixture(autouse=True)
def no_http(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("MongoDB-only application must never create an HTTP client")

    monkeypatch.setattr(httpx, "Client", forbidden)


@pytest.mark.parametrize("today_only", [True, False])
def test_worker_reads_mongodb_closes_client_and_preserves_cache(
    qtbot, config, repo, monkeypatch, today_only
):
    config.atlas.enabled = False  # Legacy switch must no longer cause HTTP fallback.
    now = int(time.time() * 1000) - 1000
    calls = []
    closed = []

    class Atlas:
        def __init__(self, cfg, uri, cancelled):
            assert uri == "synthetic-uri"

        def pages(self, collection, start=None, end=None, after_id=None):
            calls.append((collection, start, end))
            if today_only and start is not None:
                assert start >= midnight_ms(config.ui.timezone)
            if collection == "entries" and start <= now < end:
                yield [{"_id": "mongo", "date": now, "sgv": 108}]

        def close(self):
            closed.append(True)

    monkeypatch.setattr("bganalyzer.ui.workers.AtlasClient", Atlas)
    provider = SimpleNamespace(get_token=lambda: "synthetic-uri")
    worker = SyncWorker(config, None, 2, today_only=today_only, atlas_credentials=provider)
    results = []
    worker.result.connect(results.append)
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start()
    assert results and not results[0].errors
    assert len(repo.get_glucose_range("synthetic", now - 1, now + 1)) == 1
    assert {c[0] for c in calls} == {"profile", "entries", "treatments", "devicestatus"}
    assert closed == [True]
    worker.deleteLater()


def test_today_poll_marks_incremental_full_import_does_not(qtbot, config, repo, monkeypatch):
    from bganalyzer.nightscout.sync import SyncStats

    seen = {}

    class Coordinator:
        def __init__(self, *args, **kwargs):
            pass

        def initial_backfill(self, source_id, days=90, force=False, start_ms=None,
                             incremental=False):
            seen["incremental"] = incremental
            seen["start_ms"] = start_ms
            return SyncStats()

    class Atlas:
        def __init__(self, cfg, uri, cancelled):
            pass

        def close(self):
            pass

    monkeypatch.setattr("bganalyzer.ui.workers.AtlasCoordinator", Coordinator)
    monkeypatch.setattr("bganalyzer.ui.workers.AtlasClient", Atlas)
    provider = SimpleNamespace(get_token=lambda: "synthetic-uri")
    for today_only, expected in ((True, True), (False, False)):
        worker = SyncWorker(config, None, 2, today_only=today_only, atlas_credentials=provider)
        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.start()
        assert seen["incremental"] is expected
        assert (seen["start_ms"] is not None) is today_only
        worker.deleteLater()


def test_missing_uri_does_not_fall_back(qtbot, config, repo):
    worker = SyncWorker(config, None, 1, atlas_credentials=SimpleNamespace(get_token=lambda: None))
    errors = []
    worker.failed.connect(errors.append)
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start()
    assert errors and "AUTH_REQUIRED" in errors[0]
    worker.deleteLater()


def test_close_cancels_mongodb_worker_and_closes_cursor_client(qtbot, config, repo, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    closed = []

    class Atlas:
        def __init__(self, cfg, uri, cancelled):
            self.cancelled = cancelled

        def pages(self, *args):
            entered.set()
            assert release.wait(5)
            if self.cancelled():
                raise NightscoutError("Cancelled", error_code="CANCELLED")
            yield []

        def close(self):
            closed.append(True)

    monkeypatch.setattr("bganalyzer.ui.workers.AtlasClient", Atlas)
    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    window.atlas_credentials = SimpleNamespace(get_token=lambda: "synthetic")
    window.show()
    qtbot.waitUntil(lambda: window.report_worker is None)
    try:
        window.sync(1)
        qtbot.waitUntil(entered.is_set)
        window.close()
        assert window.worker is not None
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.worker is None and window.report_worker is None, timeout=5000)
    assert closed == [True]
    assert not window.isVisible()
    assert (
        get_connection(config).execute("SELECT state FROM sync_runs").fetchone()[0] == "cancelled"
    )


def test_connection_page_has_no_nightscout_inputs(qtbot, config, repo):
    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    qtbot.waitUntil(lambda: window.report_worker is None)
    assert not hasattr(window, "origin")
    assert not hasattr(window, "secret")
    assert not hasattr(window, "atlas_enabled")
    assert config.source_origin == config.nightscout.origin  # Existing cache remains visible.
    window.close()


def test_legacy_settings_load_without_losing_atlas_or_cache(config):
    from bganalyzer.config import AppConfig
    data = config.model_dump()
    data["nightscout"].update(api_mode="v1", verify_ssl=True, timeout_connect=10, timeout_read=30)
    data["atlas"]["database"] = "Cluster0"
    loaded = AppConfig.model_validate(data)
    assert loaded.source_origin == config.source_origin
    assert loaded.atlas.database == "Cluster0"
