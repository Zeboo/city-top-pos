"""Windows client for a shared live Top City POS server."""
import sys
from urllib.parse import urlparse
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMainWindow, QInputDialog, QMessageBox
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtPrintSupport import QPrinter, QPrintDialog


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
        self.printer = QPrinter(QPrinter.HighResolution)
        if QPrintDialog(self.printer, self).exec() == QPrintDialog.Accepted:
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
