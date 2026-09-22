@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm top_city_pos.spec
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm top_city_live.spec
if errorlevel 1 exit /b 1
if exist dist\TopCityPOSLive-Windows-x64.zip del /q dist\TopCityPOSLive-Windows-x64.zip
powershell -NoProfile -Command "Compress-Archive -LiteralPath 'dist\TopCityPOSLive' -DestinationPath 'dist\TopCityPOSLive-Windows-x64.zip' -CompressionLevel Optimal"
if errorlevel 1 exit /b 1
echo Offline app: dist\TopCityPOS.exe
echo Live app: dist\TopCityPOSLive\TopCityPOSLive.exe
echo Portable live package: dist\TopCityPOSLive-Windows-x64.zip
echo Extract the ZIP on the other computer before opening TopCityPOSLive.exe.
pause
