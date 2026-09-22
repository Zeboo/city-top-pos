"""Legacy Windows desktop client using Qt 5 for Windows 10 build 15063."""
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from PySide2.QtCore import QMarginsF, QSettings, QSizeF, QStandardPaths, QUrl
from PySide2.QtGui import QDesktopServices, QPageLayout, QPageSize, QTextDocument
from PySide2.QtPrintSupport import QPrinter
from PySide2.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile, QWebEngineView
from PySide2.QtWidgets import QAction, QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox

APP_VERSION = "1.1.0-legacy"


def configure_logging():
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "TopCityPOSLiveLegacy.log"
    logging.basicConfig(filename=str(path), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    return path


class LiveWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Top City POS - Live Legacy")
        self.resize(1440, 900)
        self.settings = QSettings("TopCity", "LivePOS")
        self.server_url = ""
        self.printer = None
        self.print_document = None
        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)
        toolbar = self.addToolBar("Connection")
        toolbar.setMovable(False)
        for label, callback in (("Server address", self.connect_server), ("Back", self.view.back),
                                ("Reload", self.reload_server), ("Print receipt", self.print_page),
                                ("Open in browser", self.open_in_browser)):
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)
        self.view.page().printRequested.connect(self.print_page)
        self.view.loadFinished.connect(self.loaded)
        QWebEngineProfile.defaultProfile().downloadRequested.connect(self.download_requested)
        saved = os.getenv("TOP_CITY_POS_URL", "").strip() or str(
            self.settings.value("server_url", "") or "").strip()
        if saved:
            self.open_server(saved)
        else:
            self.connect_server(required=True)

    @staticmethod
    def valid_url(value):
        parsed = urlparse(value)
        return bool(parsed.scheme in ("http", "https") and parsed.hostname
                    and not parsed.username and not parsed.password)

    def connect_server(self, _checked=False, required=False):
        url, accepted = QInputDialog.getText(
            self, "Connect to live POS", "Enter the public POS website address (https://...):",
            text=self.server_url or str(self.settings.value("server_url", "") or ""))
        if not accepted:
            if required:
                QMessageBox.information(self, "Server required", "Use Server address to connect to the POS.")
            return
        url = url.strip().rstrip("/")
        if not self.valid_url(url):
            QMessageBox.warning(self, "Invalid address",
                                "Enter the public Railway app URL, not a database or dashboard URL.")
            return self.connect_server(required=required)
        self.settings.setValue("server_url", url)
        self.open_server(url)

    def open_server(self, url):
        self.server_url = url
        self.statusBar().showMessage("Connecting...")
        self.view.setUrl(QUrl(url))

    def reload_server(self):
        if self.server_url:
            self.view.setUrl(QUrl(self.server_url))
        else:
            self.connect_server(required=True)

    def open_in_browser(self):
        if self.server_url:
            QDesktopServices.openUrl(QUrl(self.server_url))

    def loaded(self, ok):
        host = urlparse(self.server_url).hostname or "server"
        self.statusBar().showMessage(("Connected to " if ok else "Cannot reach ") + host)
        if not ok:
            QMessageBox.warning(self, "Connection problem",
                                "Check the internet connection, Railway deployment, and public HTTPS address.")

    def download_requested(self, download):
        target, _ = QFileDialog.getSaveFileName(
            self, "Save download", download.suggestedFileName() or "top-city-pos-download")
        if target:
            download.setPath(target)
            download.accept()
        else:
            download.cancel()

    def print_page(self):
        self.view.page().runJavaScript(
            "(() => {const r=document.querySelector('#thermal-print-host #receipt')||"
            "document.querySelector('#receipt');return r?r.innerHTML:''})()",
            self.print_receipt)

    def print_receipt(self, html):
        if not html:
            QMessageBox.information(self, "Print receipt", "Complete an order before printing.")
            return
        self.print_document = QTextDocument(self)
        self.print_document.setDocumentMargin(2 * 72 / 25.4)
        self.print_document.setDefaultStyleSheet(
            "body{font-family:Arial;font-size:7.5pt;text-align:center;margin:0}"
            "table{width:100%;border-collapse:collapse}th,td{font-size:6.5pt;text-align:center}")
        self.print_document.setHtml("<body>" + html + "</body>")
        self.print_document.setTextWidth(76 * 72 / 25.4)
        self.print_document.adjustSize()
        height = max(70, self.print_document.size().height() * 25.4 / 72 + 15)
        self.printer = QPrinter(QPrinter.HighResolution)
        self.printer.setPageSize(QPageSize(QSizeF(80, height), QPageSize.Millimeter,
                                           "80mm receipt", QPageSize.ExactMatch))
        self.printer.setPageOrientation(QPageLayout.Portrait)
        self.printer.setFullPage(True)
        self.printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
        if not self.printer.isValid():
            QMessageBox.warning(self, "Printer unavailable", "Configure a default Windows printer first.")
            return
        self.print_document.setPageSize(QSizeF(80 * 72 / 25.4, height * 72 / 25.4))
        self.print_document.print_(self.printer)


def self_test():
    from PySide2.QtCore import qVersion
    Path(sys.executable).with_suffix(".check.txt").write_text(
        "TopCityPOSLive Legacy imports OK; Qt " + qVersion(), encoding="utf-8")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    app = QApplication(sys.argv)
    app.setApplicationName("Top City POS Live Legacy")
    app.setOrganizationName("TopCity")
    log_path = configure_logging()

    def exception_handler(kind, value, traceback):
        logging.exception("Unhandled error", exc_info=(kind, value, traceback))
        QMessageBox.critical(None, "Top City POS error", "See diagnostic log:\n" + str(log_path))

    sys.excepthook = exception_handler
    app.setStyle("Fusion")
    window = LiveWindow()
    window.show()
    sys.exit(app.exec_())
