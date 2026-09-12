"""Desktop lifecycle with an actual exclusive process lock."""

import sys

from PySide6.QtCore import QLockFile, QObject
from PySide6.QtWidgets import QApplication

from bganalyzer.secrets import CredentialProvider
from bganalyzer.ui.main_window import MainWindow


class AppController(QObject):
    def __init__(self, config):
        super().__init__()
        self.config = config
        config.ensure_dirs()
        self._lock = QLockFile(str(config.data_dir / "bganalyzer.lock"))
        if not self._lock.tryLock(0):
            raise RuntimeError("BGAnalyzer is already running. Open its existing window.")
        self._main_window = MainWindow(config, CredentialProvider(config))
        QApplication.instance().aboutToQuit.connect(self._lock.unlock)

    def show(self):
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()


def create_application():
    return QApplication.instance() or QApplication(sys.argv)
