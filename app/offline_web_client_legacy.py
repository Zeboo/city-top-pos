"""Standalone local web POS for older Windows 10 systems."""
import logging
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import urllib.request
import zipfile
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
from app.build_version import BUILD_VERSION  # noqa: E402
from PySide2.QtCore import QMarginsF, QObject, QSizeF, Qt, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide2.QtPrintSupport import QPrinter, QPrinterInfo  # noqa: E402
from PySide2.QtWebChannel import QWebChannel  # noqa: E402
from PySide2.QtWebEngineWidgets import QWebEngineProfile, QWebEngineView  # noqa: E402
from PySide2.QtGui import QIcon, QPageLayout, QPageSize, QTextDocument  # noqa: E402
from PySide2.QtWidgets import QAction, QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox  # noqa: E402

APP_VERSION = BUILD_VERSION
APP_ICON = Path(__file__).resolve().parent / "resources" / "top_city_pos.ico"
IS_ONEFILE = getattr(sys, "frozen", False) and Path(getattr(sys, "_MEIPASS", "")).parent != Path(sys.executable).parent
DEFAULT_UPDATE_MANIFEST = "update.json" if IS_ONEFILE else "update-fast.json"
UPDATE_MANIFEST_URL = os.getenv("TOP_CITY_UPDATE_MANIFEST_URL",
                                "https://github.com/Zeboo/city-top-pos/releases/latest/download/" + DEFAULT_UPDATE_MANIFEST)
UPDATE_ROOT = LOCAL_ROOT / "updates"


def clean_stale_update_packages():
    """Remove superseded downloads without touching logs, scripts, or POS data."""
    UPDATE_ROOT.mkdir(parents=True, exist_ok=True)
    root = UPDATE_ROOT.resolve()
    for candidate in UPDATE_ROOT.glob("TopCityPOSOffline-*"):
        try:
            resolved = candidate.resolve()
            if resolved.parent != root:
                continue
            if candidate.is_dir():
                shutil.rmtree(str(candidate), ignore_errors=True)
            else:
                candidate.unlink(missing_ok=True)
        except OSError as exc:
            logging.warning("Could not remove stale update package %s: %s", candidate, exc)


class UpdateSignals(QObject):
    ready = Signal(str, str)
    failed = Signal(str)


class PrintBridge(QObject):
    """Reliable JavaScript-to-desktop print route for older Qt WebEngine builds."""
    requested = Signal(str, str, str)

    @Slot(str, str, str)
    def requestPrint(self, print_kind, print_html, request_id):
        if print_kind in ("receipt", "report"):
            self.requested.emit(print_kind, print_html, request_id)

def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class OfflineWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Top City POS - Complete Offline")
        self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(1440, 900)
        self.setMinimumSize(900, 620)
        cache_root = LOCAL_ROOT / "browser-cache"
        version_marker = LOCAL_ROOT / "browser-cache.version"
        try:
            cached_version = version_marker.read_text(encoding="utf-8").strip() if version_marker.exists() else ""
            if cached_version != APP_VERSION:
                shutil.rmtree(str(cache_root), ignore_errors=True)
                version_marker.write_text(APP_VERSION, encoding="utf-8")
        except OSError:
            logging.warning("Could not reset the browser cache for POS version %s", APP_VERSION)
        cache_root.mkdir(parents=True, exist_ok=True)
        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)
        profile = QWebEngineProfile.defaultProfile()
        profile.setCachePath(str(cache_root / "http"))
        profile.setPersistentStoragePath(str(cache_root / "storage"))
        profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
        profile.setHttpCacheMaximumSize(256 * 1024 * 1024)
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
        # The native queue is primary; the Qt print signal remains as a
        # fallback for printer drivers that require a browser print request.
        self.view.page().printRequested.connect(self.print_web_document)
        # Direct WebChannel bridge avoids lost dialog-click requests on legacy Qt WebEngine.
        self._print_bridge = PrintBridge(self)
        self._print_bridge.requested.connect(self._start_native_print_request)
        self._web_channel = QWebChannel(self.view.page())
        self._web_channel.registerObject("topCityPrintBridge", self._print_bridge)
        self.view.page().setWebChannel(self._web_channel)
        self.view.loadFinished.connect(self._install_print_bridge)
        profile.downloadRequested.connect(self.download_requested)
        self._native_print_busy = False
        self._native_print_timer = QTimer(self)
        self._native_print_timer.setInterval(180)
        self._native_print_timer.timeout.connect(self._poll_native_print_request)
        self._native_print_timer.start()
        self.start_attempts = 0
        self.start_timer = QTimer(self)
        self.start_timer.timeout.connect(self.open_when_ready)
        self.start_timer.start(150)
        self.statusBar().showMessage("Starting local POS database...")
        self.pending_update = None
        self.installing_update = False
        self.update_check_running = False
        self.update_signals = UpdateSignals(self)
        self.update_signals.ready.connect(self.update_ready)
        self.update_signals.failed.connect(self.update_failed)
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(15 * 60 * 1000)
        self.update_timer.timeout.connect(self.start_update_check)

    def _build_toolbar(self):
        toolbar = self.addToolBar("Offline POS")
        toolbar.setMovable(False)
        for label, callback in (("Home", lambda: self.view.setUrl(self.local_url)),
                                ("Back", self.view.back), ("Reload", self.view.reload),
                                ("Print", self.print_web_document), ("Data folder", self.show_data_folder)):
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)

    def _install_print_bridge(self, loaded):
        if not loaded:
            return
        self.view.page().runJavaScript("""
            (() => {
              if (window.topCityPrintBridge || window.__topCityPrintBridgeLoading) return;
              window.__topCityPrintBridgeLoading = true;
              const start = () => new QWebChannel(qt.webChannelTransport, channel => {
                window.topCityPrintBridge = channel.objects.topCityPrintBridge;
                window.__topCityPrintBridgeLoading = false;
              });
              if (window.QWebChannel) { start(); return; }
              const script = document.createElement('script');
              script.src = 'qrc:///qtwebchannel/qwebchannel.js';
              script.onload = start;
              script.onerror = () => { window.__topCityPrintBridgeLoading = false; };
              document.head.appendChild(script);
            })();
        """)
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
                QTimer.singleShot(3000, self.start_update_check)
                self.update_timer.start()
        except OSError:
            if self.start_attempts >= 200:
                self.start_timer.stop()
                QMessageBox.critical(self, "Startup failed",
                                     "The local POS server could not start. Check the diagnostic log in:\n" + str(LOCAL_ROOT))

    def start_update_check(self):
        if (self.update_check_running or self.pending_update or not getattr(sys, "frozen", False)
                or not UPDATE_MANIFEST_URL.lower().startswith("https://")):
            return
        self.update_check_running = True
        threading.Thread(target=self._check_for_update, name="pos-auto-update", daemon=True).start()

    def _check_for_update(self):
        try:
            request = urllib.request.Request(UPDATE_MANIFEST_URL, headers={"User-Agent": "TopCityPOS/" + APP_VERSION})
            with urllib.request.urlopen(request, timeout=12) as response:
                manifest = json.loads(response.read(65536).decode("utf-8-sig"))
            new_version = str(manifest["version"]).strip()
            download_url = str(manifest["url"]).strip()
            expected_hash = str(manifest["sha256"]).strip().lower()
            package_format = str(manifest.get("format", "exe")).strip().lower()
            if not new_version.isdigit() or not APP_VERSION.isdigit() or int(new_version) <= int(APP_VERSION):
                return
            if (not download_url.lower().startswith("https://") or len(expected_hash) != 64
                    or package_format not in {"exe", "zip"}):
                raise ValueError("The update manifest is invalid")
            clean_stale_update_packages()
            update_file = UPDATE_ROOT / ("TopCityPOSOffline-" + new_version + "." + package_format)
            digest = hashlib.sha256()
            download_request = urllib.request.Request(download_url, headers={"User-Agent": "TopCityPOS/" + APP_VERSION})
            try:
                with urllib.request.urlopen(download_request, timeout=30) as response, update_file.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
            except Exception:
                update_file.unlink(missing_ok=True)
                raise
            if digest.hexdigest().lower() != expected_hash:
                update_file.unlink(missing_ok=True)
                raise ValueError("Downloaded update failed its security check")
            ready_path = update_file
            if package_format == "zip":
                ready_path = UPDATE_ROOT / ("TopCityPOSOffline-" + new_version)
                ready_path.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(str(update_file)) as archive:
                    root = ready_path.resolve()
                    for member in archive.infolist():
                        destination = (root / member.filename).resolve()
                        if root != destination and root not in destination.parents:
                            raise ValueError("The update archive contains an unsafe path")
                    archive.extractall(str(ready_path))
                update_file.unlink(missing_ok=True)
            self.update_signals.ready.emit(str(ready_path), new_version)
        except Exception as exc:
            logging.warning("Automatic update check failed: %s", exc)
            self.update_signals.failed.emit(str(exc))
        finally:
            self.update_check_running = False

    def update_ready(self, update_path, version):
        self.pending_update = Path(update_path)
        self.statusBar().showMessage("Update " + version + " downloaded and verified", 10000)
        prompt = QMessageBox(self)
        prompt.setWindowTitle("Top City POS Update")
        prompt.setWindowIcon(QIcon(str(APP_ICON)))
        prompt.setIcon(QMessageBox.Information)
        prompt.setTextFormat(Qt.RichText)
        prompt.setText(
            '<div style="font-size:20px;font-weight:800;color:#c91f24;">'
            'A new POS update is ready</div>')
        prompt.setInformativeText(
            "Version " + version + " has been downloaded and verified.\n\n"
            "Install it now? Top City POS will close, install the update, and restart automatically.\n\n"
            "Choose Later to continue working. The update will install when you close the POS.")
        install_button = prompt.addButton("Install & Restart", QMessageBox.AcceptRole)
        later_button = prompt.addButton("Later", QMessageBox.RejectRole)
        prompt.setDefaultButton(install_button)
        prompt.setEscapeButton(later_button)
        prompt.setStyleSheet("""
            QMessageBox {
                background: #fffaf3;
                color: #291112;
                font-family: "Segoe UI", Arial;
            }
            QMessageBox QLabel {
                color: #291112;
                font-size: 13px;
            }
            QMessageBox QLabel#qt_msgbox_label,
            QMessageBox QLabel#qt_msgbox_informativelabel {
                min-width: 270px;
                max-width: 300px;
            }
            QMessageBox QPushButton {
                min-width: 120px;
                min-height: 40px;
                padding: 8px 16px;
                border: 1px solid #dfd2c0;
                border-radius: 8px;
                background: #ffffff;
                color: #291112;
                font-size: 13px;
                font-weight: 700;
            }
            QMessageBox QPushButton:hover {
                border-color: #c91f24;
                background: #fff1ed;
            }
            QMessageBox QPushButton:default {
                border: 1px solid #c91f24;
                background: #c91f24;
                color: #ffffff;
            }
            QMessageBox QPushButton:default:hover {
                background: #a9161b;
            }
        """)
        for label_name in ("qt_msgbox_label", "qt_msgbox_informativelabel"):
            label = prompt.findChild(QLabel, label_name)
            if label:
                label.setAlignment(Qt.AlignCenter)
                label.setWordWrap(True)
        prompt.setFixedWidth(390)
        prompt.exec_()
        if prompt.clickedButton() is install_button:
            self.install_update()

    def update_failed(self, message):
        self.statusBar().showMessage("Update check will retry next time the POS starts", 6000)

    def install_update(self, close_window=True):
        if not self.pending_update or not self.pending_update.exists() or self.installing_update:
            return
        target = Path(sys.executable).resolve()
        script = UPDATE_ROOT / "install-update.cmd"
        update_log = UPDATE_ROOT / "install-update.log"
        launch_target = target.parent / "TopCityPOSOffline.exe" if self.pending_update.is_dir() else target
        shortcut_command = (
            "$w=New-Object -ComObject WScript.Shell;"
            "$p=[IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'Top City POS.lnk');"
            "$s=$w.CreateShortcut($p);"
            f"$s.TargetPath='{launch_target}';"
            f"$s.WorkingDirectory='{launch_target.parent}';"
            f"$s.IconLocation='{launch_target},0';"
            "$s.Save()")
        launch_commands = (
            f'rmdir /S /Q "{LOCAL_ROOT / "browser-cache"}" 2>NUL\r\n'
            f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "{shortcut_command}"\r\n'
            "set LAUNCH_TRIES=0\r\n"
            ":launch_update\r\n"
            "set /A LAUNCH_TRIES+=1\r\n"
            f'echo [%DATE% %TIME%] Launch attempt %LAUNCH_TRIES% for {launch_target}>>"{update_log}"\r\n'
            f'start "" /D "{launch_target.parent}" "{launch_target}"\r\n'
            "ping 127.0.0.1 -n 2 >NUL\r\n"
            f'tasklist /FI "IMAGENAME eq {launch_target.name}" 2>NUL | find /I "{launch_target.name}" >NUL && goto launch_done\r\n'
            f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Start-Process -FilePath \'{launch_target}\' -WorkingDirectory \'{launch_target.parent}\'"\r\n'
            "ping 127.0.0.1 -n 2 >NUL\r\n"
            f'tasklist /FI "IMAGENAME eq {launch_target.name}" 2>NUL | find /I "{launch_target.name}" >NUL && goto launch_done\r\n'
            f'explorer.exe "{launch_target}"\r\n'
            "ping 127.0.0.1 -n 2 >NUL\r\n"
            f'tasklist /FI "IMAGENAME eq {launch_target.name}" 2>NUL | find /I "{launch_target.name}" >NUL && goto launch_done\r\n'
            "if %LAUNCH_TRIES% LSS 5 goto launch_update\r\n"
            f'echo [%DATE% %TIME%] ERROR: updated application did not stay running>>"{update_log}"\r\n'
            "exit /b 1\r\n"
            ":launch_done\r\n"
            f'echo [%DATE% %TIME%] Updated application relaunched successfully>>"{update_log}"\r\n')
        if self.pending_update.is_dir():
            replacement = (
                "set COPY_TRIES=0\r\n"
                ":copy_update\r\n"
                "set /A COPY_TRIES+=1\r\n"
                f'"%SystemRoot%\\System32\\robocopy.exe" "{self.pending_update}" "{target.parent}" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /MT:8 >NUL\r\n'
                "if errorlevel 8 goto copy_failed\r\n"
                "goto files_ready\r\n"
                ":copy_failed\r\n"
                "if %COPY_TRIES% GEQ 12 exit /b 1\r\n"
                "ping 127.0.0.1 -n 2 >NUL\r\n"
                "goto copy_update\r\n"
                ":files_ready\r\n"
                + launch_commands +
                f'rmdir /S /Q "{self.pending_update}"\r\n')
        else:
            replacement = (
                "set COPY_TRIES=0\r\n"
                ":copy_update\r\n"
                "set /A COPY_TRIES+=1\r\n"
                f'copy /Y "{self.pending_update}" "{target}" >NUL\r\n'
                "if not errorlevel 1 goto files_ready\r\n"
                "if %COPY_TRIES% GEQ 30 exit /b 1\r\n"
                "ping 127.0.0.1 -n 2 >NUL\r\n"
                "goto copy_update\r\n"
                ":files_ready\r\n"
                + launch_commands +
                f'del /Q "{self.pending_update}"\r\n')
        script.write_text(
            "@echo off\r\n"
            "setlocal\r\n"
            f'echo [%DATE% %TIME%] Starting update handoff from PID {os.getpid()}>>"{update_log}"\r\n'
            "set WAIT_TRIES=0\r\n"
            ":wait_for_exit\r\n"
            "set /A WAIT_TRIES+=1\r\n"
            f'tasklist /FI "PID eq {os.getpid()}" 2>NUL | find "{os.getpid()}" >NUL\r\n'
            "if errorlevel 1 goto replace\r\n"
            "if %WAIT_TRIES% GEQ 120 (\r\n"
            f'  echo [%DATE% %TIME%] ERROR: old application did not exit>>"{update_log}"\r\n'
            "  exit /b 1\r\n"
            ")\r\n"
            "ping 127.0.0.1 -n 2 >NUL\r\n"
            "goto wait_for_exit\r\n"
            ":replace\r\n"
            f'echo [%DATE% %TIME%] Old application closed; replacing files>>"{update_log}"\r\n'
            "ping 127.0.0.1 -n 2 >NUL\r\n"
            + replacement +
            'del /Q "%~f0"\r\n', encoding="utf-8")
        self.installing_update = True
        comspec = os.environ.get("COMSPEC", str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                                                / "System32" / "cmd.exe"))
        creation_flags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                          | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                          | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                          # Qt/WebEngine can place the desktop process in a
                          # Windows job object whose shutdown also kills child
                          # processes. The updater must survive that shutdown
                          # long enough to replace and relaunch the POS.
                          | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000))
        try:
            # Windows 10 includes WMIC. Asking the WMI service to create the
            # helper makes it independent of the Qt/WebEngine process tree, so
            # it remains alive after the POS closes. This is the most reliable
            # handoff on the older Windows 10 1703 machines used by the shop.
            wmic = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wbem" / "WMIC.exe"
            launched = False
            if wmic.exists():
                helper_command = f'"{comspec}" /d /c ""{script}""'
                result = subprocess.run(
                    [str(wmic), "process", "call", "create", helper_command],
                    cwd=str(UPDATE_ROOT), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                    timeout=15)
                launched = result.returncode == 0 and b"ReturnValue = 0" in result.stdout
                if not launched:
                    logging.warning("WMI updater handoff failed: %s", result.stdout.decode(errors="replace"))
            if not launched:
                subprocess.Popen([comspec, "/d", "/c", str(script)],
                                 cwd=str(UPDATE_ROOT), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 close_fds=True, creationflags=creation_flags)
        except (OSError, subprocess.SubprocessError) as exc:
            self.installing_update = False
            logging.exception("Could not launch the POS updater")
            QMessageBox.critical(self, "Update could not start", str(exc))
            return
        if close_window:
            self.close()
            QApplication.instance().quit()

    def show_data_folder(self):
        QMessageBox.information(self, "Local database",
                                "Offline database and logs are stored in:\n\n" + str(LOCAL_ROOT))

    def download_requested(self, download):
        target, _ = QFileDialog.getSaveFileName(
            self, "Save PDF report", download.suggestedFileName() or "sales-report.pdf", "PDF files (*.pdf)")
        if target:
            if not target.lower().endswith(".pdf"):
                target += ".pdf"
            download.setPath(target)
            download.accept()
        else:
            download.cancel()

    def _poll_native_print_request(self):
        if self._native_print_busy:
            return
        self.view.page().runJavaScript(
            "(() => { const request=window.__topCityNativePrintRequest; "
            "if(!request || request.claimed)return ''; request.claimed=true; "
            "return request.kind || ''; })()",
            self._start_native_print_request,
        )

    def _start_native_print_request(self, print_kind, print_html="", request_id=""):
        if not print_kind or self._native_print_busy:
            return
        self._active_print_request_id = str(request_id or "")
        self._native_print_busy = True
        self.statusBar().showMessage("Preparing " + print_kind + " for printer...", 5000)
        logging.info("Starting native %s print job (HTML length: %s)", print_kind, len(print_html or ""))
        if print_html:
            self._thermal_print_kind = print_kind
            self._print_thermal_receipt(print_html)
        else:
            self._route_web_print(print_kind)

    def print_page(self):
        self.print_web_document()
    def print_web_document(self):
        """Route browser print requests to either thermal receipt or A4 report printing."""
        self.view.page().runJavaScript(
            "(() => { const request=window.__topCityNativePrintRequest; "
            "if(request){if(request.claimed)return ''; request.claimed=true; "
            "return request.kind || '';} return window.__topCityPrintKind || "
            "(document.querySelector('#thermal-print-host') ? 'receipt' : "
            "(document.querySelector('#report-print-host') ? 'report' : '')); })()",
            self._start_native_print_request,
        )

    def _route_web_print(self, print_kind):
        if print_kind == "report":
            self.print_report_silently()
        elif print_kind == "receipt":
            self.print_receipt_silently()
        else:
            self._native_print_busy = False
            self.statusBar().showMessage("Nothing is ready to print", 5000)

    def print_report_silently(self):
        # Reports print on the same fitted 80 mm thermal roll as receipts.
        self._thermal_print_kind = 'report'
        self.view.page().runJavaScript(
            "(() => { const report=document.querySelector('#report-print-host'); "
            "return report ? report.outerHTML : ''; })()",
            self._print_thermal_report,
        )

    def _print_thermal_report(self, report_html):
        self._print_thermal_receipt(report_html)

    def print_receipt_silently(self):
        self._thermal_print_kind = 'receipt'
        # Browser printing uses the printer driver's default paper length,
        # which can feed a very long roll. Instead, take only the visible
        # receipt section and print it on a custom 80 mm page sized to its
        # actual rendered contents.
        self.view.page().runJavaScript(
            "(() => { const host=document.querySelector('#thermal-print-host');"
            "const receipt=host && host.querySelector('#receipt,.kitchen-receipt');"
            "return receipt ? receipt.outerHTML : ''; })()",
            self._print_thermal_receipt,
        )

    def _print_thermal_receipt(self, receipt_html):
        if not receipt_html:
            self.statusBar().showMessage("Print content is not available", 8000)
            self._finish_thermal_print(False)
            return
        printer_info = QPrinterInfo.defaultPrinter()
        if printer_info.isNull():
            self.statusBar().showMessage("Not printed - set a Windows default printer", 8000)
            QMessageBox.warning(self, "Printer required",
                                "No Windows default printer is configured.\n\n"
                                "Open Windows Settings > Printers & scanners, choose the 80 mm thermal printer, and set it as default.")
            self._finish_thermal_print(False)
            return
        try:
            self._receipt_document = QTextDocument(self)
            # QTextDocument uses CSS/layout pixels (96 dpi), not PostScript points.
            layout_units_per_mm = 96 / 25.4
            self._receipt_document.setDocumentMargin(0)
            self._receipt_document.setDefaultStyleSheet(
                "body{font-family:Arial,sans-serif;color:#000;margin:0;text-align:center;font-size:9pt;}"
                "h2{margin:0 0 5px;font-size:14pt;line-height:1.1;text-align:center;}"
                "p{margin:4px 0;line-height:1.28;text-align:center;}"
                ".receipt-order,.kitchen-order-number{font-size:11pt;font-weight:bold;}"
                ".kitchen-customer{font-size:10pt;}"
                "hr{border:0;border-top:1px dashed #000;margin:5px 0;}"
                "table{width:100%;border-collapse:collapse;table-layout:fixed;margin:6px 0;}"
                "th,td{padding:3px 1px;border-bottom:1px dashed #777;font-size:8pt;line-height:1.2;}"
                "th{text-transform:uppercase;}"
                "th:first-child,td:first-child{text-align:left;width:40%;word-wrap:break-word;}"
                "th:not(:first-child),td:not(:first-child){text-align:right;}"
                ".receipt-footer{margin-top:7px;padding-top:6px;border-top:1px dashed #777;font-size:8pt;}"
            )
            self._receipt_document.setHtml("<body>" + receipt_html + "</body>")
            supported_widths = [
                size.size(QPageSize.Millimeter).width()
                for size in printer_info.supportedPageSizes()
                if 68 <= size.size(QPageSize.Millimeter).width() <= 80
            ]
            # Use the whole imageable width of the nominal 80 mm roll. Some
            # POS-80 drivers expose only about 72 mm as printable.
            page_width_mm = max(supported_widths, default=80.0)
            # Keep the receipt near the full 80 mm printable area without clipping.
            content_width_mm = min(76.0, max(68.0, page_width_mm - 2.0))
            printable_width = content_width_mm * layout_units_per_mm
            self._receipt_document.setTextWidth(printable_width)
            content_height_points = self._receipt_document.documentLayout().documentSize().height()
            # Small padding prevents the last printed line from being clipped,
            # without adding blank thermal-paper length.
            receipt_height = max(25, content_height_points / layout_units_per_mm + 6)
            self._receipt_printer = QPrinter(QPrinter.HighResolution)
            self._receipt_printer.setOutputFormat(QPrinter.NativeFormat)
            self._receipt_printer.setPrinterName(printer_info.printerName())
            print_part = "item slip" if "kitchen-receipt" in receipt_html else "full receipt"
            self._receipt_printer.setDocName("Top City POS - " + print_part)
            if not self._receipt_printer.isValid():
                raise RuntimeError("Windows could not open the selected printer")
            self._receipt_printer.setPageSize(QPageSize(
                QSizeF(page_width_mm, receipt_height), QPageSize.Millimeter,
                "Fitted thermal receipt", QPageSize.ExactMatch
            ))
            self._receipt_printer.setPageOrientation(QPageLayout.Portrait)
            self._receipt_printer.setFullPage(True)
            self._receipt_printer.setPageMargins(QMarginsF(0, 0, 0, 0))
            self._receipt_document.setPageSize(QSizeF(page_width_mm * layout_units_per_mm,
                                                      receipt_height * layout_units_per_mm))
            self._receipt_document.setTextWidth(printable_width)
            self.statusBar().showMessage("Printing receipt to " + printer_info.printerName())
            logging.info("Submitting %s to %s at %.2f x %.2f mm",
                         getattr(self, '_thermal_print_kind', 'receipt'),
                         printer_info.printerName(), page_width_mm, receipt_height)
            self._receipt_document.print_(self._receipt_printer)
            logging.info("Submitted %s job to %s", print_part, printer_info.printerName())
            self.statusBar().showMessage(print_part.title() + " sent to " + printer_info.printerName(), 8000)
            # The next event swaps in the compact order slip. A short delay
            # lets Windows finish submitting this job, giving auto-cut printers
            # a separate job boundary before the slip begins.
            # Give the Windows spooler time to close this one-page job before the
            # next (order-slip) job begins. Each job now has exactly one page and
            # therefore one driver-controlled cut.
            QTimer.singleShot(900, self._finish_thermal_print)
        except Exception as exc:
            logging.exception("Thermal receipt printing failed")
            message = str(exc) or exc.__class__.__name__
            self.statusBar().showMessage("Receipt printing failed: " + message, 12000)
            QMessageBox.critical(self, "Printing failed",
                                 "The receipt could not be sent to the Windows printer.\n\n"
                                 "Reason: " + message + "\n\n"
                                 "Check that the thermal printer is powered on, connected, online, and selected as the Windows default printer.")
            self._finish_thermal_print(False)

    def _finish_thermal_print(self, success=True):
        self._native_print_busy = False
        self._receipt_printer = None
        self._receipt_document = None
        kind = getattr(self, '_thermal_print_kind', 'receipt')
        event_name = 'topcity-report-print-complete' if kind == 'report' else 'topcity-receipt-print-complete'
        self.view.page().runJavaScript(
            "window.dispatchEvent(new CustomEvent('" + event_name + "',"
            "{detail:{success:" + ("true" if success else "false") + ",requestId:"
            + json.dumps(getattr(self, "_active_print_request_id", "")) + "}}));"
        )

    def closeEvent(self, event):
        self.server.should_exit = True
        self.server_thread.join(timeout=.75)
        if self.pending_update and not self.installing_update:
            self.install_update(close_window=False)
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
    qt_app.setWindowIcon(QIcon(str(APP_ICON)))
    qt_app.setStyle("Fusion")
    window = OfflineWindow()
    window.show()
    sys.exit(qt_app.exec_())
