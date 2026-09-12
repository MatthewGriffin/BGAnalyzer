"""Main entry point for BGAnalyzer application."""

import logging
import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from bganalyzer.app import AppController
from bganalyzer.config import AppConfig
from bganalyzer.logging_config import setup_logging


def main() -> int:
    """Main application entry point."""
    QCoreApplication.setOrganizationName("BGAnalyzer")
    QCoreApplication.setApplicationName("BGAnalyzer")
    QCoreApplication.setApplicationVersion("0.1.0")

    setup_logging()
    logger = logging.getLogger(__name__)

    config = AppConfig.load()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    try:
        controller = AppController(config)
    except RuntimeError as exc:
        QMessageBox.information(QWidget(), "BGAnalyzer", str(exc))
        return 1
    controller.show()

    logger.info("BGAnalyzer started")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
