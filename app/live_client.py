"""Windows client for a shared live Top City POS server."""
import sys
from urllib.parse import urlparse
from PySide6.QtCore import QMarginsF, QSettings, QSizeF, QUrl
from PySide6.QtGui import QAction, QPageLayout, QPageSize
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
            "(() => { const receipt=document.querySelector('#receipt'); "
            "return receipt ? Math.max(50, Math.ceil(receipt.scrollHeight*25.4/96)+8) : 0; })()",
            self._print_thermal_receipt,
        )

    def _print_thermal_receipt(self, receipt_height):
        self.printer = QPrinter(QPrinter.HighResolution)
        if receipt_height:
            page_size = QPageSize(QSizeF(80, float(receipt_height)), QPageSize.Millimeter,
                                  '80mm thermal receipt', QPageSize.ExactMatch)
            self.printer.setPageSize(page_size)
            self.printer.setPageMargins(QMarginsF(2, 2, 2, 2), QPageLayout.Millimeter)
        if not self.printer.isValid():
            self.statusBar().showMessage('No default printer is available. Set the thermal printer as the Windows default.')
            return
        self.statusBar().showMessage('Printing receipt on ' + self.printer.printerName())
        self.view.print(self.printer)


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
