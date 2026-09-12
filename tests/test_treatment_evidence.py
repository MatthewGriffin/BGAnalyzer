import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pyqtgraph as pg
from bganalyzer.analytics.calendar import day_bounds
from bganalyzer.analytics.treatment_evidence import event_details, event_lanes
from bganalyzer.contracts.domain import TreatmentEvent, TreatmentKind
from bganalyzer.db.connection import get_connection
from bganalyzer.secrets import CredentialProvider
from bganalyzer.ui.main_window import MainWindow


def event(remote="event", **kwargs):
    return TreatmentEvent(
        source_id="synthetic",
        remote_id=remote,
        revision_hash="revision",
        event_ms=kwargs.pop("event_ms", 1000),
        kind=kwargs.pop("kind", TreatmentKind.BOLUS),
        **kwargs,
    )


def test_recorded_evidence_preserves_zero_and_does_not_invent_delivery():
    tx = event(
        kind=TreatmentKind.TEMP_BASAL,
        rate_u_h=Decimal("0"),
        percent=Decimal("0"),
        attributes_json=json.dumps({"notes": "<b>literal note</b>"}),
    )
    text = event_details(tx, "Europe/London", presence_unknown=True)
    assert "Recorded basal rate: 0 U/h" in text
    assert "Recorded basal percentage: 0 %" in text
    assert "Delivery status: unknown" in text
    assert "Presence uncertain" in text
    assert "<b>literal note</b>" in text
    assert "Source record ID: event" in text
    assert event_lanes(tx) == ["basal"]


def test_combined_carbs_and_bolus_have_both_lanes_without_wizard_as_delivery():
    assert event_lanes(event(carbs_g=30, insulin_u=2)) == ["carbs", "bolus"]
    assert event_lanes(event(kind=TreatmentKind.SMB, insulin_u=0.1)) == ["smb"]
    assert event_lanes(event(kind=TreatmentKind.BOLUS_WIZARD, insulin_u=2)) == ["other"]


def test_timeline_links_records_and_withholds_uncertain_markers(qtbot, config, repo):
    day = datetime.now(ZoneInfo(config.ui.timezone)).date() - timedelta(days=1)
    lo, _ = day_bounds(day, config.ui.timezone)
    tx = event("meal", event_ms=lo + 60000, carbs_g=30, insulin_u=2)
    for row in (
        tx,
        event("invalid", event_ms=lo + 120000, valid=False),
        event("missing", event_ms=lo + 180000),
    ):
        repo.upsert_treatment(row)
    get_connection(config).execute(
        "INSERT INTO sync_disappearances(source_id,collection,remote_id,first_missing_ms) VALUES(?,?,?,?)",
        ("synthetic", "treatments", "missing", lo),
    )
    get_connection(config).commit()
    window = MainWindow(config, CredentialProvider(config))
    qtbot.addWidget(window)
    window.timer.stop()
    qtbot.waitUntil(lambda: window.report_worker is None)
    meal_row = next(
        row
        for row in range(window.table.rowCount())
        if window.table.item(row, 5).text() == "" and window.table.item(row, 2).text() == "30"
    )
    window._open_table_event(meal_row, 0)
    qtbot.waitUntil(lambda: window.report_worker is None)
    assert window.graph_date.date().toPython() == day
    assert window.report_days.value() == 14
    markers = next(
        item for item in window.event_plot.items() if isinstance(item, pg.ScatterPlotItem)
    )
    assert len(markers.points()) == 2  # One record occupies the carb and bolus lanes.
    assert {point.data().remote_id for point in markers.points()} == {"meal"}
    window._event_clicked(markers, markers.points(), None)
    assert "Source record ID: meal" in window.event_details.toPlainText()
    assert "Delivery status: unknown" in window.event_details.toPlainText()
    assert "1 shown of 3" in window.event_summary.text()
    window.close()
