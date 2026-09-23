@echo off
setlocal
cd /d "%~dp0"
if not exist .venv-legacy\Scripts\python.exe (
  echo Python 3.9 legacy environment is required.
  exit /b 1
)
.venv-legacy\Scripts\python.exe -m pip install -r requirements-offline-legacy.txt
if errorlevel 1 exit /b 1
.venv-legacy\Scripts\python.exe -m PyInstaller --noconfirm --clean top_city_offline_legacy.spec
if errorlevel 1 exit /b 1
if exist dist\TopCityPOSOffline-Windows10-1703-x64.zip del /q dist\TopCityPOSOffline-Windows10-1703-x64.zip
powershell -NoProfile -Command "Compress-Archive -LiteralPath 'dist\TopCityPOSOffline' -DestinationPath 'dist\TopCityPOSOffline-Windows10-1703-x64.zip' -CompressionLevel Optimal"
if errorlevel 1 exit /b 1
echo Offline POS: dist\TopCityPOSOffline-Windows10-1703-x64.zip
pause
