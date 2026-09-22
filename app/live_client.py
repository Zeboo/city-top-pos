"""Windows desktop client for the shared, Railway-hosted Top City POS."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QMarginsF, QSettings, QSizeF, QStandardPaths, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

APP_VERSION = "1.1.0"


def app_data_directory() -> Path:
    root = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    path = Path(root or Path.home() / "AppData" / "Local" / "TopCityPOSLive")
    path.mkdir(parents=True, exist_ok=True)
    return path


def configure_logging() -> Path:
    log_path = app_data_directory() / "TopCityPOSLive.log"
    logging.basicConfig(filename=log_path, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    logging.info("Starting Top City POS Live %s", APP_VERSION)
    return log_path


class PosWebPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):  # noqa: N802
        if navigation_type == QWebEnginePage.NavigationTypeLinkClicked and not is_main_frame:
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


class LiveWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Top City POS · Live {APP_VERSION}")
        self.resize(1440, 900)
        self.setMinimumSize(900, 620)
        self.settings = QSettings("TopCity", "LivePOS")
        self.server_url = ""
        self.printer = None
        self.print_document = None
        self.view = QWebEngineView(self)
        self.view.setPage(PosWebPage(QWebEngineProfile.defaultProfile(), self.view))
        self.setCentralWidget(self.view)
        self._build_toolbar()
        self.view.page().printRequested.connect(self.print_page)
        self.view.loadStarted.connect(lambda: self.statusBar().showMessage("Connecting…"))
        self.view.loadFinished.connect(self.loaded)
        QWebEngineProfile.defaultProfile().downloadRequested.connect(self.download_requested)
        saved_url = str(self.settings.value("server_url", "") or "").strip()
        configured_url = os.getenv("TOP_CITY_POS_URL", "").strip()
        if configured_url or saved_url:
            self.open_server(configured_url or saved_url)
        else:
            self.connect_server(required=True)

    def _build_toolbar(self):
        toolbar = self.addToolBar("Connection")
        toolbar.setMovable(False)
        for label, callback in (("Server address", self.connect_server), ("Back", self.view.back),
                                ("Reload", self.reload_server), ("Print receipt", self.print_page),
                                ("Open in browser", self.open_in_browser)):
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)

    @staticmethod
    def valid_server_url(value: str) -> bool:
        parsed = urlparse(value)
        return bool(parsed.scheme in ("http", "https") and parsed.hostname
                    and not parsed.username and not parsed.password)

    def connect_server(self, _checked=False, required=False):
        while True:
            url, accepted = QInputDialog.getText(
                self, "Connect to live POS", "Enter the public POS website address (https://…):",
                text=self.server_url or str(self.settings.value("server_url", "") or ""))
            if not accepted:
                if required:
                    self.show_connection_help("A server address is required before the POS can start.")
                return
            url = url.strip().rstrip("/")
            if self.valid_server_url(url):
                self.settings.setValue("server_url", url)
                self.open_server(url)
                return
            QMessageBox.warning(
                self, "Invalid server address",
                "Enter the public HTTP or HTTPS address of the deployed POS.\n\n"
                "Example: https://your-pos.up.railway.app\n\n"
                "Do not enter a PostgreSQL URL or a Railway dashboard URL.")

    def open_server(self, url: str):
        url = url.strip().rstrip("/")
        if not self.valid_server_url(url):
            self.connect_server(required=True)
            return
        self.server_url = url
        logging.info("Opening POS host %s", urlparse(url).hostname)
        self.view.setUrl(QUrl(url))

    def reload_server(self):
        if self.server_url:
            self.view.setUrl(QUrl(self.server_url))
        else:
            self.connect_server(required=True)

    def open_in_browser(self):
        if self.server_url:
            QDesktopServices.openUrl(QUrl(self.server_url))

    def loaded(self, ok: bool):
        host = urlparse(self.server_url).hostname or "server"
        if ok:
            self.statusBar().showMessage(f"Connected securely to {host}")
            logging.info("POS page loaded from %s", host)
            return
        logging.error("Could not load POS page from %s", host)
        self.statusBar().showMessage("Cannot reach the POS server")
        self.show_connection_help(
            "The desktop app could not reach the POS server. Check the internet connection, "
            "confirm that Railway is deployed, and verify the public HTTPS address.")

    def show_connection_help(self, message: str):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("POS connection problem")
        box.setText(message)
        box.setInformativeText(f"Current address: {self.server_url or 'Not configured'}")
        change = box.addButton("Change server address", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is change:
            self.connect_server(required=True)

    def download_requested(self, download):
        suggested = download.suggestedFileName() or "top-city-pos-download"
        target, _ = QFileDialog.getSaveFileName(self, "Save download", suggested)
        if not target:
            download.cancel()
            return
        destination = Path(target)
        download.setDownloadDirectory(str(destination.parent))
        download.setDownloadFileName(destination.name)
        download.accept()
        self.statusBar().showMessage(f"Downloading {destination.name}…")

    def print_page(self):
        self.view.page().runJavaScript(
            "(() => { const receipt=document.querySelector('#thermal-print-host #receipt') "
            "|| document.querySelector('#receipt'); return receipt ? receipt.innerHTML : ''; })()",
            self._print_thermal_receipt)

    def _print_thermal_receipt(self, receipt_html):
        if not receipt_html:
            QMessageBox.information(self, "Print receipt", "Complete an order before printing its receipt.")
            return
        self.print_document = QTextDocument(self)
        self.print_document.setDocumentMargin(2 * 72 / 25.4)
        self.print_document.setDefaultStyleSheet(
            "body{font-family:Arial;font-size:7.5pt;color:#000;margin:0;text-align:center}"
            "h2{text-align:center;font-size:11pt;margin:0 0 4px}"
            "p{margin:3px 0;text-align:center}hr{border:0;border-top:1px dashed #000;margin:4px 0}"
            "table{width:100%;border-collapse:collapse;margin:7px 0}"
            "th,td{padding:2px 1px;border-bottom:1px dashed #777;font-size:6.5pt;text-align:center}")
        self.print_document.setHtml(f"<body>{receipt_html}</body>")
        page_width_points = 80 * 72 / 25.4
        self.print_document.setTextWidth(76 * 72 / 25.4)
        self.print_document.adjustSize()
        receipt_height = max(70, self.print_document.size().height() * 25.4 / 72 + 15)
        self.printer = QPrinter(QPrinter.HighResolution)
        self.printer.setPageSize(QPageSize(QSizeF(80, receipt_height), QPageSize.Millimeter,
                                           "80mm thermal receipt", QPageSize.ExactMatch))
        self.printer.setPageOrientation(QPageLayout.Portrait)
        self.printer.setFullPage(True)
        self.printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
        if not self.printer.isValid():
            QMessageBox.warning(self, "Printer unavailable",
                                "No default printer is available. Configure the thermal printer in Windows first.")
            return
        self.statusBar().showMessage("Printing receipt on " + self.printer.printerName())
        self.print_document.setPageSize(QSizeF(page_width_points, receipt_height * 72 / 25.4))
        self.print_document.print_(self.printer)


def run_self_test():
    from PySide6.QtCore import qVersion
    Path(sys.executable).with_suffix(".check.txt").write_text(
        f"TopCityPOSLive {APP_VERSION} imports OK; Qt {qVersion()}", encoding="utf-8")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        run_self_test()
        raise SystemExit(0)
    app = QApplication(sys.argv)
    app.setApplicationName("Top City POS Live")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("TopCity")
    log_path = configure_logging()

    def report_unhandled_exception(exc_type, exc_value, exc_traceback):
        logging.exception("Unhandled desktop client error", exc_info=(exc_type, exc_value, exc_traceback))
        QMessageBox.critical(None, "Top City POS could not continue",
                             f"An unexpected error occurred. Diagnostic log:\n{log_path}")

    sys.excepthook = report_unhandled_exception
    app.setStyle("Fusion")
    window = LiveWindow()
    window.show()
    sys.exit(app.exec())
