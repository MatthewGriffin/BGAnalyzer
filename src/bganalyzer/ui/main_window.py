"""Native desktop overview, connection settings, cached timeline and read-only sync."""

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDateEdit,
        QScrollArea,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QTableWidget,
        QHeaderView,
        QTabWidget,
        QTextBrowser,
        QVBoxLayout,
        QWidget,
    )

from PySide6.QtWidgets import QTableWidgetItem

from bganalyzer.analytics.report import quality_text
from bganalyzer.analytics.calendar import day_bounds
from bganalyzer.analytics.treatment_evidence import LANES, event_lanes, event_details
from bganalyzer.secrets import AtlasCredentialProvider
from bganalyzer.nightscout.atlas import validate_atlas_uri
from bganalyzer.db.connection import close_connection, initialize_database
from bganalyzer.db.sync_journal import SyncJournal
from bganalyzer.nightscout.sync import DAY
from bganalyzer.ui.workers import ReportWorker, SyncWorker, BasalWorker

# A CGM that uploads once every 5 minutes is routinely 10 minutes late, so a
# live report anchored at the last wall-clock second invents a missing-data
# tail on every run. Historical windows keep their exact sync bounds; only the
# live "now" anchor is rolled back by this buffer.
CGM_DELAY_BUFFER_MS = 10 * 60 * 1000


class LocalDayAxis(pg.DateAxisItem):
    def __init__(self, zone):
        super().__init__(utcOffset=0)
        self.zone = ZoneInfo(zone)

    def tickStrings(self, values, scale, spacing):
        return [datetime.fromtimestamp(value, self.zone).strftime("%H:%M %Z") for value in values]


class MainWindow(QMainWindow):
    def __init__(self, config, credential_provider):
        super().__init__()
        self.config = config
        self.credentials = credential_provider
        self.atlas_credentials = AtlasCredentialProvider(config)
        self.basal_worker = None
        self._basal_request_id = None
        self._basal_pending = False
        self._basal_got_result = True
        self._auto_sync_pending = False
        self.worker = None
        self._report_end_ms = None
        self.report_worker = None
        self._report_request_id = 0
        self._report_running_id = 0
        self._report_snapshot = None
        self._last_local_error = ""
        self._sync_failures = 0
        self._close_pending = False
        self.metrics = None
        self._selected_event_id = None
        self.setWindowTitle("BGAnalyzer")
        self.resize(1200, 820)
        initialize_database(config)
        SyncJournal(config).recover_interrupted()
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._overview()
        self._records()
        self._quality()
        self._basal()
        self._settings()
        explanation_layout = self._page("Report explanation")
        self.explanation_view = QTextBrowser()
        explanation_layout.addWidget(self.explanation_view)
        self.timer = QTimer(self)
        self.timer.setInterval(max(60, config.sync.poll_interval_seconds) * 1000)
        self.timer.timeout.connect(lambda: self.sync(1, today_only=True))
        self.timer.start()
        self.refresh_cached()
        if not config.atlas.database:
            self.tabs.setCurrentIndex(2)

    def _page(self, name):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.tabs.addTab(page, name)
        return layout

    def _overview(self):
        layout = self._page("Overview")
        self.latest = QLabel("No glucose data imported")
        font = self.latest.font()
        font.setPointSize(20)
        self.latest.setFont(font)
        self.latest.setTextFormat(Qt.PlainText)
        self.latest.setWordWrap(True)
        layout.addWidget(self.latest)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Report period"))
        self.report_days = QSpinBox()
        self.report_days.setRange(1, 90)
        self.report_days.setValue(14)
        self.report_days.setSuffix(" days")
        self.report_days.valueChanged.connect(self.refresh_cached)
        controls.addWidget(self.report_days)
        self.refresh_button = QPushButton("Sync report period")
        self.refresh_button.clicked.connect(lambda: self.sync(self.report_days.value()))
        controls.addWidget(self.refresh_button)
        self.cancel_button = QPushButton("Cancel sync")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_sync)
        controls.addWidget(self.cancel_button)
        self.export_button = QPushButton("Export summary…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_summary)
        controls.addWidget(self.export_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.summary = QLabel("Coverage and metrics will appear after import.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        navigation = QHBoxLayout()
        self.previous_day = QPushButton("← Previous day")
        self.next_day = QPushButton("Next day →")
        self.today_button = QPushButton("Today")
        self.graph_date = QDateEdit()
        self.graph_date.setCalendarPopup(True)
        self.graph_date.setDisplayFormat("ddd dd MMM yyyy")
        today = datetime.now(ZoneInfo(self.config.ui.timezone)).date()
        self.graph_date.setMaximumDate(QDate(today.year, today.month, today.day))
        self.graph_date.setDate(QDate(today.year, today.month, today.day))
        self.previous_day.clicked.connect(
            lambda: self.graph_date.setDate(self.graph_date.date().addDays(-1))
        )
        self.next_day.clicked.connect(
            lambda: self.graph_date.setDate(self.graph_date.date().addDays(1))
        )
        self.today_button.clicked.connect(self.show_today)
        self.graph_date.dateChanged.connect(self.refresh_cached)
        for widget in (self.previous_day, self.graph_date, self.next_day, self.today_button):
            navigation.addWidget(widget)
        navigation.addStretch()
        layout.addLayout(navigation)
        self.graph_message = QLabel()
        layout.addWidget(self.graph_message)
        self.plot = pg.PlotWidget(axisItems={"bottom": LocalDayAxis(self.config.ui.timezone)})
        self.plot.setLabel("left", "Glucose", units="mmol/L")
        self.plot.setLabel("bottom", f"Time ({self.config.ui.timezone})")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        layout.addWidget(self.plot, 1)
        self._event_timeline(layout)
        self.review = QLabel(
            "Profile suggestions are unavailable: the inherited tuning code has not passed AAPS reference-parity testing. No settings are written to Nightscout or AAPS."
        )
        self.review.setWordWrap(True)
        layout.addWidget(self.review)

    def _event_timeline(self, layout):
        self.event_summary = QLabel("Recorded events · click a marker for details")
        layout.addWidget(self.event_summary)
        self.event_plot = pg.PlotWidget(axisItems={"bottom": LocalDayAxis(self.config.ui.timezone)})
        self.event_plot.setXLink(self.plot)
        self.event_plot.setMouseEnabled(x=True, y=False)
        self.event_plot.setYRange(-0.6, 4.6, padding=0)
        self.event_plot.setMinimumHeight(135)
        self.event_plot.setMaximumHeight(170)
        self.event_plot.getAxis("left").setTicks(
            [[(value, name.title()) for name, value in LANES.items()]]
        )
        layout.addWidget(self.event_plot)
        self.event_details = QTextBrowser()
        self.event_details.setMinimumHeight(90)
        self.event_details.setMaximumHeight(145)
        layout.addWidget(self.event_details)

    def _render_events(self, snapshot):
        palette = {
            "carbs": "#f0b44d",
            "bolus": "#be86ed",
            "smb": "#759cec",
            "basal": "#53b69e",
            "other": "#aaaaaa",
        }
        visible = [
            tx
            for tx in snapshot.graph_treatments
            if tx.valid and tx.remote_id not in snapshot.graph_presence_unknown
        ]
        spots = []
        for tx in visible:
            for lane in event_lanes(tx):
                spots.append(
                    {
                        "pos": (tx.event_ms / 1000, LANES[lane]),
                        "data": tx,
                        "brush": pg.mkBrush(palette[lane]),
                        "symbol": "o",
                        "size": 9,
                    }
                )
        markers = pg.ScatterPlotItem(
            spots=spots,
            hoverable=True,
            tip=lambda x, y, data: event_details(data, self.config.ui.timezone),
        )
        markers.sigClicked.connect(self._event_clicked)
        self.event_plot.addItem(markers)
        self.event_summary.setText(
            f"Recorded events: {len(visible)} shown of {snapshot.graph_treatment_count} cached for this day · "
            "invalid/uncertain records omitted; newest 2,000 loaded · double-click a treatment row to view its day"
        )
        selected = next(
            (tx for tx in snapshot.graph_treatments if tx.remote_id == self._selected_event_id),
            None,
        )
        if selected is not None:
            self._show_event(selected, selected.remote_id in snapshot.graph_presence_unknown)

    def _event_clicked(self, scatter, points, event):
        if len(points):
            self._show_event(points[0].data())

    def _show_event(self, tx, presence_unknown=False):
        self._selected_event_id = tx.remote_id
        self.event_details.setPlainText(
            event_details(tx, self.config.ui.timezone, presence_unknown)
        )
        # A timestamp reference line does not imply a measured glucose value.
        for plot in (self.plot, self.event_plot):
            for item in list(plot.items()):
                if isinstance(item, pg.InfiniteLine):
                    plot.removeItem(item)
            plot.addItem(
                pg.InfiniteLine(
                    tx.event_ms / 1000, angle=90, pen=pg.mkPen("#bbbbbb", style=Qt.DashLine)
                )
            )

    def _open_table_event(self, row, column):
        if self._report_snapshot is None:
            return
        item = self.table.item(row, 0)
        tx = next(
            (
                tx
                for tx in self._report_snapshot.treatments
                if tx.remote_id == item.data(Qt.UserRole)
            ),
            None,
        )
        if tx is None:
            return
        self._selected_event_id = tx.remote_id
        day = datetime.fromtimestamp(tx.event_ms / 1000, ZoneInfo(self.config.ui.timezone)).date()
        self.graph_date.setDate(QDate(day.year, day.month, day.day))
        self.tabs.setCurrentIndex(0)
        self._show_event(tx, tx.remote_id in self._report_snapshot.treatment_presence_unknown)

    def _records(self):
        layout = self._page("Treatment records")
        label = QLabel(
            "Uploaded records, not verified delivered-insulin totals. Calculator records and SMB remain distinct. Times use the configured report timezone."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.record_count_label = QLabel()
        layout.addWidget(self.record_count_label)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Kind", "Carbs (g)", "Insulin (U)", "Rate (U/h)", "Notes"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._open_table_event)
        layout.addWidget(self.table)

    def _quality(self):
        layout = self._page("Data quality")
        self.quality = QTextBrowser()
        self.quality.setPlainText(
            "No synchronization completed.\n\nHistory completeness, delivery reconstruction, and profile activation are not yet verified. Numerical recommendations remain unavailable."
        )
        layout.addWidget(self.quality)

    def _settings(self):
        outer = self._page("Connection")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        form = QFormLayout()

        form.addRow("Data source", QLabel("MongoDB Atlas — today and history"))

        self.atlas_database = QLineEdit(self.config.atlas.database)
        self.atlas_database.setPlaceholderText("Atlas database name")
        form.addRow("Atlas database", self.atlas_database)

        self.atlas_collections = {}
        for name in ("entries", "treatments", "devicestatus", "profile"):
            edit = QLineEdit(getattr(self.config.atlas, name))
            edit.setPlaceholderText(f"Atlas {name} collection")
            self.atlas_collections[name] = edit
            form.addRow(f"Atlas {name}", edit)

        self.atlas_uri = QLineEdit()
        self.atlas_uri.setPlaceholderText(
            "mongodb+srv://user:pass@cluster.mongodb.net (stored in keyring)"
        )
        self.atlas_uri.setEchoMode(QLineEdit.Password)
        form.addRow("Atlas URI", self.atlas_uri)

        self.atlas_remember = QCheckBox("Store Atlas URI in keyring")
        self.atlas_remember.setChecked(True)
        form.addRow("", self.atlas_remember)

        self.history_days = QSpinBox()
        self.history_days.setRange(1, 90)
        self.history_days.setValue(min(90, self.config.sync.backfill_window_days))
        form.addRow("Days to import", self.history_days)

        self.recheck_history = QCheckBox("Recheck previously imported history")
        form.addRow("", self.recheck_history)

        layout.addLayout(form)

        self.save_button = QPushButton("Save connection and import")
        self.save_button.clicked.connect(self.save_connection)
        layout.addWidget(self.save_button)

        description = QLabel(
            "All requests are read-only. Imports run while the app is open. Closing it stops synchronization.\n\nThis development build provides local glucose summaries and recorded treatments. Embedded AI explanations and validated profile suggestions are still being implemented."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addStretch()

    def save_connection(self):
        if not self.atlas_database.text().strip():
            QMessageBox.warning(self, "MongoDB database", "Enter the database name.")
            return
        if any(not edit.text().strip() for edit in self.atlas_collections.values()):
            QMessageBox.warning(self, "MongoDB collections", "Enter all collection names.")
            return
        if self.atlas_uri.text():
            try:
                validate_atlas_uri(self.atlas_uri.text().strip())
            except ValueError as exc:
                QMessageBox.warning(self, "MongoDB connection", str(exc))
                return
        self.config.atlas.enabled = True  # Kept only for compatibility with older config files.
        self.config.atlas.database = self.atlas_database.text().strip()
        for name, edit in self.atlas_collections.items():
            setattr(self.config.atlas, name, edit.text().strip())
        self.config.sync.backfill_window_days = self.history_days.value()
        if self.atlas_uri.text():
            persisted = self.atlas_credentials.set_token(
                self.atlas_uri.text().strip(), self.atlas_remember.isChecked()
            )
            self.atlas_uri.clear()
            if not persisted:
                QMessageBox.information(
                    self,
                    "Atlas session credential",
                    "Keyring unavailable. The Atlas URI is available only for this session.",
                )
        try:
            self.config.save()
        except OSError:
            QMessageBox.warning(self, "Save failed", "Could not save connection settings.")
            return
        self.refresh_cached()
        self.sync(self.history_days.value(), force=self.recheck_history.isChecked())

    def _basal(self):
        layout = self._page("Basal readiness")
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Range:"))
        self.basal_days = QSpinBox()
        self.basal_days.setRange(1, 90)
        self.basal_days.setValue(self.report_days.value())
        self.basal_days.setSuffix(" days")
        self.basal_days.valueChanged.connect(self._basal_range_changed)
        self.report_days.valueChanged.connect(self._report_range_changed)
        controls.addWidget(self.basal_days)
        self.basal_refresh = QPushButton("Check basal analysis readiness")
        self.basal_refresh.clicked.connect(self._start_basal_computation)
        controls.addWidget(self.basal_refresh)
        self.basal_cancel = QPushButton("Cancel")
        self.basal_cancel.setEnabled(False)
        self.basal_cancel.clicked.connect(self._cancel_basal)
        controls.addWidget(self.basal_cancel)
        controls.addStretch()
        layout.addLayout(controls)

        confirmation_form = QFormLayout()
        self.basal_confirmations = {}
        for key, label in (("meals_recorded", "Meals/carbs recorded throughout this period?"),
                           ("autosens_enabled", "Autosens enabled throughout this period?"),
                           ("dynamic_isf", "Dynamic ISF enabled throughout this period?")):
            combo = QComboBox()
            combo.addItem("Unknown / use uploaded evidence", None)
            combo.addItem("Yes — I confirm for this period", True)
            combo.addItem("No — I confirm for this period", False)
            self.basal_confirmations[key] = combo
            confirmation_form.addRow(label, combo)
        layout.addLayout(confirmation_form)

        self.basal_status = QLabel(
            "Check input completeness and validation blockers. Numerical basal changes are withheld."
        )
        self.basal_status.setWordWrap(True)
        layout.addWidget(self.basal_status)

        # Suggestions table: one row per merged basal segment plus IC/ISF.
        # Consecutive hours sharing a proposed rate are merged into a range
        # (e.g. hours 20-23 at 1.325 U/hr) instead of four identical rows.
        self.basal_table = QTableWidget()
        self.basal_table.setColumnCount(6)
        self.basal_table.setHorizontalHeaderLabels(
            ["Segment", "Baseline (U/hr)", "Proposed (U/hr)", "Direction", "Status", "Confidence"]
        )
        self.basal_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.basal_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.basal_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.basal_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.basal_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.basal_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.basal_table.setAlternatingRowColors(True)
        self.basal_table.setSortingEnabled(True)
        self.basal_table.setMinimumHeight(120)
        layout.addWidget(self.basal_table)

    def _start_basal_computation(self):
        if self.basal_worker is not None or self._close_pending:
            return
        if self._report_snapshot is None:
            self._basal_pending = True
            self.refresh_cached()
            self.basal_status.setText("Loading report…")
            return
        wanted = self.basal_days.value()
        if self._snapshot_days(self._report_snapshot) != wanted:
            self._basal_pending = True
            if self.report_days.value() != wanted:
                self.report_days.setValue(wanted)
            else:
                self.refresh_cached()
            self.basal_status.setText(f"Loading {wanted}-day report…")
            return
        self._basal_pending = False
        self._basal_request_id = self._report_request_id
        self._basal_got_result = False
        self.basal_status.setText("Checking basal analysis readiness…")
        self.basal_refresh.setEnabled(False)
        self.basal_cancel.setEnabled(True)
        self.basal_table.clear()
        settings = self._basal_settings()
        for combo in self.basal_confirmations.values():
            combo.setEnabled(False)
        self.basal_worker = BasalWorker(
            self.config, self._report_snapshot, self._basal_request_id, settings, self
        )
        self.basal_worker.progress.connect(self._basal_progress)
        self.basal_worker.result.connect(self._basal_result)
        self.basal_worker.failed.connect(self._basal_failed)
        self.basal_worker.finished.connect(self._basal_finished)
        self.basal_worker.start()

    @staticmethod
    def _snapshot_days(snapshot):
        return int(round((snapshot.end_ms - snapshot.start_ms) / DAY))

    def _basal_settings(self):
        return {"user_confirmations": {key: combo.currentData()
                for key, combo in self.basal_confirmations.items()
                if combo.currentData() is not None}}

    def _reset_basal_confirmations(self):
        for combo in getattr(self, "basal_confirmations", {}).values():
            combo.setCurrentIndex(0)

    def _basal_range_changed(self, days):
        if self.report_days.value() != days:
            self.report_days.setValue(days)

    def _report_range_changed(self, days):
        self._reset_basal_confirmations()
        if hasattr(self, "basal_days") and self.basal_days.value() != days:
            self.basal_days.setValue(days)

    def _cancel_basal(self):
        self._basal_pending = False
        if self.basal_worker is not None:
            self.basal_worker.requestInterruption()
            self.basal_status.setText("Stopping basal computation…")
        else:
            self.basal_status.setText("Cancelled.")

    def _basal_progress(self, text):
        self.basal_status.setText(text)

    def _render_basal_table(self, result):
        """Populate the suggestions table from the merged candidate grid.

        Consecutive hours sharing a proposed rate are merged into a range
        (e.g. hours 20-23 at 1.325 U/hr) rather than listing four identical
        rows. Rejected segments keep their reason in the Status column.
        """
        from bganalyzer.analytics.basal_recommendations import _merge_basal_ranges

        rows = _merge_basal_ranges(result.get("recommendations", [])) or \
            _merge_basal_ranges(result.get("descriptive_candidates", []))
        self.basal_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.basal_table.setItem(r, 0, QTableWidgetItem(str(row.get("range", ""))))
            # Basal rates are entered on Omnipod/AAPS to two decimal places;
            # display them rounded so the grid never shows a third digit.
            self.basal_table.setItem(
                r, 1, QTableWidgetItem(f"{row.get('baseline', 0):.2f}")
            )
            self.basal_table.setItem(
                r, 2, QTableWidgetItem(f"{row.get('proposed', 0):.2f}")
            )
            self.basal_table.setItem(
                r, 3, QTableWidgetItem(str(row.get("direction", "n/a")))
            )
            self.basal_table.setItem(
                r, 4, QTableWidgetItem(str(row.get("status", "")))
            )
            self.basal_table.setItem(
                r, 5, QTableWidgetItem(str(row.get("confidence", "")))
            )
        if rows:
            self.basal_table.resizeRowsToContents()

    def _basal_result(self, result):
        if self._basal_request_id != self._report_request_id:
            return

        self._basal_got_result = True

        if not isinstance(result, dict):
            self.basal_status.setText(
                f"Failed: basal worker returned non-dict result: "
                f"{type(result).__name__} = {result!r}"
            )
            return

        self._render_basal_table(result)

        # A stale connection usually means the last cached upload is older than
        # the live window expects — most often the tail of the report range has
        # not been synced yet. Rather than leaving the user to notice and click
        # Sync report period, trigger one and re-run the check once it lands.
        # Sync is best-effort: if it fails the existing result still displays.
        reason_codes = {
            rc.get("code") for rc in result.get("checks", []) if not rc.get("passed")
        }
        if "eligibility_connection_stale" in reason_codes and self.worker is None:
            self._auto_sync_pending = True
            self._basal_pending = True
            self._basal_got_result = False
            self.basal_status.setText("Connection stale — syncing latest data…")
            self.sync(self.report_days.value(), today_only=True)
            return

        self.basal_status.setText(result.get("message", "Basal recommendations withheld."))

    def _basal_failed(self, message):
        if self._basal_request_id == self._report_request_id:
            self._basal_got_result = True
            self.basal_status.setText(f"Basal computation failed: {message}")

    def _basal_finished(self):
        for combo in self.basal_confirmations.values():
            combo.setEnabled(True)
        if self.basal_worker is not None:
            self.basal_worker.deleteLater()
            self.basal_worker = None
        if not getattr(self, "_basal_got_result", True):
            self.basal_status.setText("Cancelled.")
        self.basal_refresh.setEnabled(True)
        self.basal_cancel.setEnabled(False)

    def sync(self, days, force=False, today_only=False):
        if self._close_pending or not self.config.atlas.database or self.worker is not None:
            return
        self._last_local_error = ""
        self.worker = SyncWorker(
            self.config,
            self.credentials,
            days,
            self,
            force=force,
            atlas_credentials=self.atlas_credentials,
            today_only=today_only,
        )
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.result.connect(self.sync_result)
        self.worker.failed.connect(self.sync_failed)
        self.worker.finished.connect(self.sync_finished)
        self.refresh_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.worker.start()

    def cancel_sync(self):
        if self.worker is not None:
            self.worker.requestInterruption()
            self.statusBar().showMessage("Stopping after the active bounded network request…")

    def sync_result(self, stats):
        self._reset_basal_confirmations()
        if getattr(stats, "requested_end_ms", None) is not None:
            self._report_end_ms = stats.requested_end_ms
        if stats.cancelled:
            message = "Import cancelled; completed history windows are saved."
            self.timer.stop()
        elif stats.errors:
            self._sync_failures += 1
            message = "Import finished with incomplete windows. See Data quality."
            if any(
                code in ("AUTH_FAILED", "AUTH_REQUIRED", "UNSUPPORTED_AUTH")
                for code in stats.error_codes
            ):
                self.timer.stop()
                message = "Authentication needs attention. Update Connection or retry manually."
            else:
                self.timer.start(
                    min(
                        3600,
                        max(60, self.config.sync.poll_interval_seconds)
                        * 2 ** min(self._sync_failures, 5),
                    )
                    * 1000
                )
        else:
            self._sync_failures = 0
            message = (
                f"Import complete · {stats.windows_skipped} previously checked windows skipped."
            )
            self.timer.start(max(60, self.config.sync.poll_interval_seconds) * 1000)
        self.statusBar().showMessage(message)

    def sync_failed(self, message):
        self._last_local_error = message
        self.statusBar().showMessage(message)
        self.timer.stop()

    def sync_finished(self):
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self.refresh_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        # refresh_cached() starts a fresh report worker; _render_report will
        # re-trigger the basal check against the new snapshot when it lands.
        # The stale-connection auto-sync path sets _basal_pending above.
        self.refresh_cached()
        if self._close_pending and self.report_worker is None:
            self.close()

    def show_today(self):
        today = datetime.now(ZoneInfo(self.config.ui.timezone)).date()
        qday = QDate(today.year, today.month, today.day)
        self.graph_date.setMaximumDate(qday)
        self.graph_date.setDate(qday)

    def refresh_cached(self):
        if self._close_pending:
            return
        self._report_request_id += 1
        self.metrics = None
        self.export_button.setEnabled(False)
        if self.basal_worker is not None:
            self.basal_worker.requestInterruption()
        if self.report_worker is None:
            self._start_report()

    def _start_report(self):
        # CGM uploads lag behind real time; a device that reports once every
        # 5 minutes can easily be 10 minutes late. Demanding data up to the
        # last wall-clock second only manufactures a false "missing data" edge
        # at the end of every report, so the live end is rolled back by the
        # configured delay buffer. Synced historical windows keep their exact
        # bounds: only the live "now" anchor is trimmed.
        end = self._report_end_ms
        if end is None:
            end = int(time.time() * 1000) - CGM_DELAY_BUFFER_MS
        start = end - self.report_days.value() * DAY
        self._report_running_id = self._report_request_id
        today = datetime.now(ZoneInfo(self.config.ui.timezone)).date()
        self.graph_date.setMaximumDate(QDate(today.year, today.month, today.day))
        selected = self.graph_date.date().toPython()
        self.next_day.setEnabled(selected < today)
        self.report_worker = ReportWorker(
            self.config,
            self._report_running_id,
            start,
            end,
            self,
            graph_bounds=day_bounds(selected, self.config.ui.timezone),
        )
        self.report_worker.result.connect(self._render_report)
        self.report_worker.failed.connect(self._report_failed)
        self.report_worker.finished.connect(self._report_finished)
        self.report_worker.start()

    def _report_failed(self, message):
        self._last_local_error = message
        self.quality.setPlainText(message)
        self.statusBar().showMessage(message)

    def _report_finished(self):
        if self.report_worker is not None:
            self.report_worker.deleteLater()
            self.report_worker = None
        if self._close_pending:
            if self.worker is None:
                self.close()
        elif self._report_running_id != self._report_request_id:
            self._start_report()

    def _render_report(self, snapshot):
        # Changing source or range while loading cannot overwrite the newest selection.
        if self._close_pending or snapshot.request_id != self._report_request_id:
            return
        self._report_snapshot = snapshot
        if self._basal_pending and not self._close_pending:
            if self._snapshot_days(snapshot) == self.basal_days.value():
                self._basal_pending = False
                self._start_basal_computation()
            else:
                self._start_basal_computation()
        self.metrics = None
        self.plot.clear()
        self.event_plot.clear()
        self.event_details.setPlainText(
            "Click a recorded event below the glucose graph to inspect its evidence."
        )
        self.graph_message.setText("No cached glucose readings for this day.")
        self.table.setRowCount(0)
        self.latest.setText("No glucose data imported for this source")
        self.summary.setText("Coverage and metrics will appear after import.")
        self.record_count_label.setText("")
        self.quality.setPlainText(
            (self._last_local_error + "\n\n" if self._last_local_error else "")
            + quality_text(snapshot, self.config.ui.timezone)
        )
        if snapshot.source_id is None:
            return
        start, end = snapshot.start_ms, snapshot.end_ms
        readings = snapshot.readings
        self.metrics = snapshot.metrics
        self.export_button.setEnabled(self.metrics is not None and self.metrics.covered_minutes > 0)
        m = self.metrics
        valid = [g for g in readings if g.valid and start <= g.event_ms < end]
        if valid:
            last = valid[-1]
            age = max(0, (end - last.event_ms) // 60_000)
            when = datetime.fromtimestamp(
                last.event_ms / 1000, ZoneInfo(self.config.ui.timezone)
            ).strftime("%d %b %H:%M %Z")
            self.latest.setText(
                f"{last.sgv_mmol:.1f} mmol/L · {when} · {age} minutes old"
                + (" · STALE" if age > 15 else "")
            )
        lo, hi = snapshot.graph_start_ms, snapshot.graph_end_ms
        if lo is not None:
            daily = [g for g in snapshot.graph_readings if g.valid and lo <= g.event_ms < hi]
            self.plot.setXRange(lo / 1000, hi / 1000, padding=0)
            self.graph_message.setText(
                f"{self.graph_date.date().toString('dd MMM yyyy')} · {self.config.ui.timezone} calendar day · {len(daily)} readings"
                if daily
                else "No cached glucose readings for this day. Import a history range that includes it."
            )
            x, y = [], []
            for i, g in enumerate(daily):
                if i and g.event_ms - daily[i - 1].event_ms > 600_000:
                    x.append(float("nan"))
                    y.append(float("nan"))
                x.append(g.event_ms / 1000)
                y.append(g.sgv_mmol)
            self.plot.plot(
                np.array(x), np.array(y), pen=pg.mkPen("#38a6d7", width=2), connect="finite"
            )
        self._render_events(snapshot)
        if m.covered_minutes:
            self.summary.setText(
                f"Coverage {m.coverage_percent:.1f}% · Mean {m.mean_mgdl / 18:.1f} mmol/L · "
                f"Time in reference range (70–180 mg/dL): {100 * m.in_range_minutes / m.covered_minutes:.1f}% · "
                f"Below 70 mg/dL: {100 * (m.low_minutes + m.very_low_minutes) / m.covered_minutes:.1f}%\n"
                "Percentages use covered time only. Missing glucose intervals remain missing; report bands do not change AAPS targets."
            )
        treatments = snapshot.treatments
        self.record_count_label.setText(
            f"Showing {len(treatments)} of {snapshot.treatment_count} records in the selected period (newest first)."
        )
        self.table.setRowCount(len(treatments))
        for row, tx in enumerate(treatments):
            attrs = json.loads(tx.attributes_json)
            when = datetime.fromtimestamp(
                tx.event_ms / 1000, ZoneInfo(self.config.ui.timezone)
            ).strftime("%d %b %H:%M %Z")
            values = [
                when,
                tx.kind.value + ("" if tx.valid else " (invalid)"),
                tx.carbs_g,
                tx.insulin_u,
                tx.rate_u_h,
                attrs.get("notes", ""),
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))
        self.table.resizeColumnsToContents()
        for row, tx in enumerate(treatments):
            self.table.item(row, 0).setData(Qt.UserRole, tx.remote_id)
            if tx.remote_id in snapshot.treatment_presence_unknown:
                self.table.item(row, 1).setText(tx.kind.value + " (presence uncertain)")

    def export_summary(self):
        if self.metrics is None:
            QMessageBox.information(
                self, "No report", "Import glucose data before exporting a summary."
            )
            return
        name, _ = QFileDialog.getSaveFileName(
            self, "Export local summary", "bganalyzer-summary.json", "JSON (*.json)"
        )
        if not name:
            return
        try:
            import os
            from pathlib import Path

            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(
                    {
                        "schema_version": 3,
                        "metrics": self.metrics.model_dump(),
                        "data_revision": self._report_snapshot.data_revision,
                        "explanation": self._report_snapshot.explanation,
                        "quality": self._report_snapshot.quality,
                        "limitations": [
                            "Descriptive glucose summary only",
                            "No validated profile recommendations",
                        ],
                        "units": "mg/dL",
                    },
                    stream,
                    indent=2,
                )
            Path(name).chmod(0o600)
        except OSError:
            QMessageBox.warning(self, "Export failed", "Could not write the selected file.")

    def closeEvent(self, event):
        self.timer.stop()
        if (
            self.worker is not None
            or self.report_worker is not None
            or self.basal_worker is not None
        ):
            self._close_pending = True
            self.cancel_sync()
            if self.report_worker is not None:
                self.report_worker.requestInterruption()
            if self.basal_worker is not None:
                self.basal_worker.requestInterruption()
            event.ignore()
            return
        close_connection()
        event.accept()
