"""Standalone local web POS for older Windows 10 systems."""
import logging
import os
import socket
import sys
import threading
from pathlib import Path

LOCAL_ROOT = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "TopCity" / "OfflinePOS"
DATA_ROOT = LOCAL_ROOT / "data"
DATA_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["TOP_CITY_DATA_DIR"] = str(DATA_ROOT)
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///" + (DATA_ROOT / "top_city.db").as_posix()
os.environ.setdefault("SESSION_SECRET", "top-city-offline-local-session")
os.environ["TOP_CITY_OFFLINE_MODE"] = "1"
os.environ.setdefault("TOP_CITY_SYNC_URL", "https://city-top-pos-production.up.railway.app")

import uvicorn  # noqa: E402
from app.web import app as web_app  # noqa: E402
from PySide2.QtCore import QTimer, QUrl  # noqa: E402
from PySide2.QtPrintSupport import QPrintDialog  # noqa: E402
from PySide2.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide2.QtWidgets import QAction, QApplication, QMainWindow, QMessageBox  # noqa: E402

APP_VERSION = "1.0.0-offline"


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class OfflineWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Top City POS - Complete Offline")
        self.resize(1440, 900)
        self.setMinimumSize(900, 620)
        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)
        self.port = available_port()
        self.local_url = QUrl("http://127.0.0.1:%d" % self.port)
        # This is a windowed PyInstaller build, so stdout/stderr are intentionally
        # absent. Uvicorn's default color formatter calls stderr.isatty() and
        # crashes in that environment; application diagnostics go to our file.
        self.server = uvicorn.Server(uvicorn.Config(web_app, host="127.0.0.1", port=self.port,
                                                    log_level="warning", access_log=False,
                                                    log_config=None))
        self.server_thread = threading.Thread(target=self._run_server, name="offline-pos-server", daemon=True)
        self.server_thread.start()
        self._build_toolbar()
        self.view.page().printRequested.connect(self.print_page)
        self.start_attempts = 0
        self.start_timer = QTimer(self)
        self.start_timer.timeout.connect(self.open_when_ready)
        self.start_timer.start(150)
        self.statusBar().showMessage("Starting local POS database...")

    def _build_toolbar(self):
        toolbar = self.addToolBar("Offline POS")
        toolbar.setMovable(False)
        for label, callback in (("Home", lambda: self.view.setUrl(self.local_url)),
                                ("Back", self.view.back), ("Reload", self.view.reload),
                                ("Print", self.print_page), ("Data folder", self.show_data_folder)):
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)

    def _run_server(self):
        try:
            self.server.run()
        except Exception:
            logging.exception("The local POS server stopped unexpectedly")

    def open_when_ready(self):
        self.start_attempts += 1
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=.05):
                self.start_timer.stop()
                self.view.setUrl(self.local_url)
                self.statusBar().showMessage("Offline POS ready - data is saved on this computer")
        except OSError:
            if self.start_attempts >= 200:
                self.start_timer.stop()
                QMessageBox.critical(self, "Startup failed",
                                     "The local POS server could not start. Check the diagnostic log in:\n" + str(LOCAL_ROOT))

    def show_data_folder(self):
        QMessageBox.information(self, "Local database",
                                "Offline database and logs are stored in:\n\n" + str(LOCAL_ROOT))

    def print_page(self):
        dialog = QPrintDialog(self)
        if dialog.exec_() == QPrintDialog.Accepted:
            self.view.page().print(dialog.printer(), lambda ok: self.statusBar().showMessage(
                "Receipt printed" if ok else "Printing failed"))

    def closeEvent(self, event):
        self.server.should_exit = True
        self.server_thread.join(timeout=3)
        event.accept()


def self_test():
    from PySide2.QtCore import qVersion
    from sqlalchemy import text
    from app.database import engine, init_db
    init_db()
    with engine.connect() as connection:
        connection.execute(text("SELECT COUNT(*) FROM orders"))
    Path(sys.executable).with_suffix(".check.txt").write_text(
        "TopCity POS Offline imports and SQLite OK; Qt " + qVersion(), encoding="utf-8")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(LOCAL_ROOT / "TopCityPOSOffline.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Top City POS Offline")
    qt_app.setOrganizationName("TopCity")
    qt_app.setStyle("Fusion")
    window = OfflineWindow()
    window.show()
    sys.exit(qt_app.exec_())
