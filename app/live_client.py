"""Windows client for a shared live Top City POS server."""
import sys
from urllib.parse import urlparse
from PySide6.QtCore import QMarginsF, QSettings, QSizeF, QUrl
from PySide6.QtGui import QAction, QPageLayout, QPageSize, QTextDocument
from PySide6.QtWidgets import QApplication, QMainWindow, QInputDialog, QMessageBox
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtPrintSupport import QPrinter


class LiveWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Top City POS · Live')
        self.resize(1440, 900)
        self.settings = QSettings('TopCity', 'LivePOS')
        self.view = QWebEngineView()
        self.setCentralWidget(self.view)
        toolbar = self.addToolBar('Connection')
        for label, callback in [('Server address', self.connect_server), ('Reload', self.view.reload), ('Print', self.print_page)]:
            action = QAction(label, self); action.triggered.connect(callback); toolbar.addAction(action)
        self.view.page().printRequested.connect(self.print_page)
        self.view.loadFinished.connect(self.loaded)
        self.printer = None
        url = self.settings.value('server_url', '')
        if url: self.view.setUrl(QUrl(url))
        else: self.connect_server()

    def connect_server(self):
        url, accepted = QInputDialog.getText(self, 'Connect to live POS', 'Enter your live server URL (https://...)', text=self.settings.value('server_url', ''))
        if not accepted: return
        url = url.strip().rstrip('/')
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            QMessageBox.warning(self, 'Invalid address', 'Enter a valid HTTP or HTTPS server address.'); return
        self.settings.setValue('server_url', url)
        self.view.setUrl(QUrl(url))

    def loaded(self, ok):
        self.statusBar().showMessage('Connected to ' + self.view.url().host() if ok else 'Cannot reach the server. Check the server address and internet connection.')

    def print_page(self):
        self.view.page().runJavaScript(
            "(() => { const receipt=document.querySelector('#thermal-print-host #receipt') "
            "|| document.querySelector('#receipt'); return receipt ? receipt.innerHTML : ''; })()",
            self._print_thermal_receipt,
        )

    def _print_thermal_receipt(self, receipt_html):
        if not receipt_html:
            self.statusBar().showMessage('No completed receipt is available to print.')
            return
        self.print_document = QTextDocument(self)
        self.print_document.setDocumentMargin(2 * 72 / 25.4)
        self.print_document.setDefaultStyleSheet(
            'body{font-family:Arial;font-size:10pt;color:#000;margin:0}'
            'h2{text-align:center;font-size:15pt;margin:0 0 6px}'
            'p{margin:5px 0}hr{border:0;border-top:1px dashed #000;margin:6px 0}'
        )
        self.print_document.setHtml(f'<body>{receipt_html}</body>')
        page_width_points = 80 * 72 / 25.4
        self.print_document.setTextWidth(page_width_points)
        self.print_document.adjustSize()
        receipt_height = max(50, self.print_document.size().height() * 25.4 / 72 + 2)
        self.printer = QPrinter(QPrinter.HighResolution)
        page_size = QPageSize(QSizeF(80, receipt_height), QPageSize.Millimeter,
                              '80mm thermal receipt', QPageSize.ExactMatch)
        self.printer.setPageSize(page_size)
        self.printer.setFullPage(True)
        self.printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
        if not self.printer.isValid():
            self.statusBar().showMessage('No default printer is available. Set the thermal printer as the Windows default.')
            return
        self.statusBar().showMessage('Printing receipt on ' + self.printer.printerName())
        self.print_document.setPageSize(QSizeF(page_width_points, receipt_height * 72 / 25.4))
        self.print_document.print_(self.printer)


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        from pathlib import Path
        from PySide6.QtCore import qVersion
        Path(sys.executable).with_suffix('.check.txt').write_text(
            'TopCityPOSLive imports OK; Qt ' + qVersion(), encoding='utf-8')
        sys.exit(0)
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = LiveWindow(); window.show()
    sys.exit(app.exec())
