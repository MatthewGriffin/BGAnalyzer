"""Thread-owned background work; immutable results cross back to the GUI."""

from uuid import uuid4

from PySide6.QtCore import QThread, Signal

from bganalyzer.analytics.report import load_report
from bganalyzer.analytics.basal_recommendations import build_basal_recommendations
from bganalyzer.autotune.models import AutotuneCancelled
from bganalyzer.contracts.domain import SourceRecord
from bganalyzer.db.connection import close_connection
from bganalyzer.db.repository import Repository
from bganalyzer.nightscout.atlas import AtlasClient, AtlasCoordinator, midnight_ms
from bganalyzer.nightscout.client import NightscoutError
from bganalyzer.secrets import AtlasCredentialProvider


class SyncWorker(QThread):
    progress = Signal(str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        config,
        credentials,
        days,
        parent=None,
        force=False,
        today_only=False,
        atlas_credentials=None,
    ):
        super().__init__(parent)
        self.config = config.model_copy(deep=True)
        self.credentials = credentials
        self.days = days
        self.force = force
        self.today_only = today_only
        self.atlas_credentials = atlas_credentials

    def run(self):
        atlas_client = None
        try:
            repo = Repository(self.config)
            source = repo.get_source(self.config.source_origin)
            if source is None:
                source = SourceRecord(id=str(uuid4()), origin=self.config.source_origin)
                repo.upsert_source(source)

            provider = self.atlas_credentials or AtlasCredentialProvider(self.config)
            atlas_client = AtlasClient(
                self.config.atlas, provider.get_token(), self.isInterruptionRequested
            )
            coordinator = AtlasCoordinator(
                self.config,
                repo,
                atlas_client,
                cancelled=self.isInterruptionRequested,
                progress=self.progress.emit,
            )

            boundary = midnight_ms(self.config.ui.timezone)
            self.result.emit(
                coordinator.initial_backfill(
                    source.id,
                    self.days,
                    force=self.force,
                    start_ms=boundary if self.today_only else None,
                    incremental=self.today_only,
                )
            )
        except NightscoutError as exc:
            self.failed.emit(f"Sync stopped: {exc.error_code}. {exc}")
        except Exception:
            self.failed.emit(
                "Sync stopped because of a local error. Cached records remain available."
            )
        finally:
            if atlas_client is not None:
                atlas_client.close()
            close_connection()


class ReportWorker(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, config, request_id, start, end, parent=None, graph_bounds=None):
        super().__init__(parent)
        self.config = config.model_copy(deep=True)
        self.request_id = request_id
        self.start_ms = start
        self.end_ms = end
        self.graph_bounds = graph_bounds

    def run(self):
        try:
            if not self.isInterruptionRequested():
                report = load_report(self.config, self.request_id, self.start_ms, self.end_ms)
                if self.graph_bounds is not None and not self.isInterruptionRequested():
                    lo, hi = self.graph_bounds
                    graph = load_report(self.config, self.request_id, lo, hi)
                    report.graph_readings = graph.readings
                    report.graph_treatments = graph.treatments
                    report.graph_treatment_count = graph.treatment_count
                    report.graph_presence_unknown = graph.treatment_presence_unknown
                    report.graph_start_ms, report.graph_end_ms = lo, hi
                if not self.isInterruptionRequested():
                    self.result.emit(report)
        except Exception:
            self.failed.emit(
                "Could not load the cached report. Existing data has not been deleted."
            )
        finally:
            close_connection()


class LocalAIWorker(QThread):
    progress = Signal(str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, config, explanation=None, parent=None):
        super().__init__(parent)
        self.config = config.model_copy(deep=True)
        self.explanation = explanation
        self.manager = None

    def requestInterruption(self):
        super().requestInterruption()
        if self.manager is not None:
            self.manager.cancel()

    def run(self):
        from bganalyzer.inference.assets import install, LocalAIError
        from bganalyzer.inference.manager import InferenceManager

        try:
            if self.explanation is None:
                install(self.config, self.progress.emit, self.isInterruptionRequested)
                self.result.emit({"installed": True})
            else:
                self.manager = InferenceManager(
                    self.config, self.isInterruptionRequested, self.progress.emit
                )
                self.result.emit(self.manager.explain(self.explanation))
        except LocalAIError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Local AI operation failed. Your calculated report remains available.")
        finally:
            if self.manager is not None:
                self.manager.stop_server()


class BasalWorker(QThread):
    progress = Signal(str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, config, snapshot, request_id, settings: dict, parent=None):
        super().__init__(parent)
        self.config = config.model_copy(deep=True)
        self.snapshot = snapshot
        self.request_id = request_id
        self.settings = settings

    def run(self):
        try:
            if not self.isInterruptionRequested():
                self.progress.emit("Checking basal analysis readiness…")
                result = build_basal_recommendations(
                    self.snapshot,
                    self.config,
                    self.config.ui.timezone,
                    self.settings,
                    cancelled=self.isInterruptionRequested,
                    progress=(
                        lambda text: self.progress.emit(text)
                        if not self.isInterruptionRequested()
                        else None
                    ),
                )
                if not self.isInterruptionRequested():
                    self.result.emit(result)
        except AutotuneCancelled:
            # User pressed Cancel; finished() still fires and resets the UI.
            pass
        except Exception as e:
            import traceback
            self.failed.emit(f"Basal computation failed: {str(e)}\n{traceback.format_exc()}")
        finally:
            close_connection()
