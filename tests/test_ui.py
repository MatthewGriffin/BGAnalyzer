from bganalyzer.contracts.domain import GlucoseReading
from bganalyzer.secrets import CredentialProvider
from bganalyzer.ui.main_window import MainWindow


def test_native_window_cached_data_and_no_dose_actions(qtbot, config, repo):
    import time

    now = int(time.time() * 1000)
    repo.upsert_glucose(
        GlucoseReading(
            source_id="synthetic",
            remote_id="g",
            revision_hash="r",
            event_ms=now - 20 * 60_000,
            sgv_mgdl=108,
        )
    )
    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    window.show()
    qtbot.waitUntil(lambda: window.report_worker is None, timeout=5000)
    assert window.tabs.count() == 6
    assert "6.0 mmol/L" in window.latest.text()
    assert "STALE" in window.latest.text()
    assert window.metrics.covered_minutes == 5
    assert "unavailable" in window.review.text()
    window.close()


def test_eligibility_never_invents_completed_checks():
    from bganalyzer.recommendations.eligibility import check_eligibility

    result = check_eligibility(None, None, None, {"approved": True})
    assert result.status == "validation_unavailable"
    assert result.supported_families == []


def test_manual_sync_uses_selected_report_period(qtbot, config, repo, monkeypatch):
    from PySide6.QtCore import Qt

    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    qtbot.waitUntil(lambda: window.report_worker is None)
    requests = []
    monkeypatch.setattr(window, "sync", lambda days: requests.append(days))
    qtbot.mouseClick(window.refresh_button, Qt.LeftButton)
    window.report_days.setValue(30)
    qtbot.mouseClick(window.refresh_button, Qt.LeftButton)
    assert requests == [14, 30]
    qtbot.waitUntil(lambda: window.report_worker is None)
    window.close()


def test_basal_range_control_shares_report_range_and_guides_without_snapshot(
    qtbot, config, repo
):
    from PySide6.QtCore import Qt

    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    qtbot.waitUntil(lambda: window.report_worker is None)
    assert window.basal_days.value() == window.report_days.value() == 14
    window.basal_days.setValue(30)
    assert window.report_days.value() == 30
    qtbot.waitUntil(lambda: window.report_worker is None)
    # One click loads the report first, then runs the check automatically.
    window._report_snapshot = None
    qtbot.mouseClick(window.basal_refresh, Qt.LeftButton)
    assert window._basal_pending is True
    qtbot.waitUntil(
        lambda: window.basal_worker is None
        and window.report_worker is None
        and not window._basal_pending,
        timeout=15000,
    )
    assert "No basal rate changes were calculated." in window.basal_output.toPlainText()
    window.close()


def test_basal_check_waits_for_matching_report_range(qtbot, config, repo):
    import time
    from types import SimpleNamespace

    from PySide6.QtCore import Qt

    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    qtbot.waitUntil(lambda: window.report_worker is None)
    now = int(time.time() * 1000)
    window._report_snapshot = SimpleNamespace(
        start_ms=now - 14 * 86400000, end_ms=now
    )
    window.basal_days.setValue(30)
    qtbot.mouseClick(window.basal_refresh, Qt.LeftButton)
    assert window._basal_pending is True
    assert window.report_days.value() == 30
    assert "Loading 30-day report" in window.basal_status.text()
    qtbot.waitUntil(
        lambda: window.basal_worker is None
        and window.report_worker is None
        and not window._basal_pending,
        timeout=15000,
    )
    assert "Analyzing:" in window.basal_output.toPlainText()
    window.close()


def test_daily_graph_navigation_preserves_report_range(qtbot, config, repo):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from PySide6.QtCore import Qt
    from bganalyzer.analytics.calendar import day_bounds

    today = datetime.now(ZoneInfo(config.ui.timezone)).date()
    for offset in (0, 1, 20):
        lo, _ = day_bounds(today - timedelta(days=offset), config.ui.timezone)
        repo.upsert_glucose(
            GlucoseReading(
                source_id="synthetic",
                remote_id=f"day-{offset}",
                revision_hash="r",
                event_ms=lo + 1000,
                sgv_mgdl=108,
            )
        )
    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    qtbot.waitUntil(lambda: window.report_worker is None)
    assert len(window.plot.listDataItems()[0].xData) == 1
    qtbot.mouseClick(window.previous_day, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.report_worker is None)
    assert window.graph_date.date().toPython() == today - timedelta(days=1)
    assert window.report_days.value() == 14
    assert len(window.plot.listDataItems()[0].xData) == 1
    window.graph_date.setDate(window.graph_date.date().addDays(-19))
    qtbot.waitUntil(lambda: window.report_worker is None)
    assert len(window.plot.listDataItems()[0].xData) == 1  # Outside report range, still viewable.
    assert window.report_days.value() == 14
    qtbot.mouseClick(window.today_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.report_worker is None)
    assert window.graph_date.date().toPython() == today
    assert not window.next_day.isEnabled()
    window.close()


def test_report_uses_exact_requested_sync_end(qtbot, config, repo):
    from bganalyzer.nightscout.sync import SyncStats
    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    qtbot.waitUntil(lambda: window.report_worker is None)
    stamp = 1789000000000
    window.sync_result(SyncStats(requested_end_ms=stamp))
    window.timer.stop()
    window.refresh_cached()
    qtbot.waitUntil(lambda: window.report_worker is None)
    assert window._report_snapshot.end_ms == stamp
    assert window._report_snapshot.start_ms == stamp - 14 * 86400000


def test_basal_confirmations_are_explicit_and_reset_with_period(qtbot, config, repo):
    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    qtbot.waitUntil(lambda: window.report_worker is None)
    assert window._basal_settings() == {"user_confirmations": {}}
    window.basal_confirmations["meals_recorded"].setCurrentIndex(1)
    window.basal_confirmations["dynamic_isf"].setCurrentIndex(2)
    assert window._basal_settings()["user_confirmations"] == {"meals_recorded": True, "dynamic_isf": False}
    window.report_days.setValue(7)
    assert window._basal_settings() == {"user_confirmations": {}}
    qtbot.waitUntil(lambda: window.report_worker is None)
