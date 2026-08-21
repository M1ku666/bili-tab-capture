@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] Virtualenv not found: %PY%
    echo Please create a virtualenv and install dependencies first:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

echo [1/3] Installing / upgrading PyInstaller ...
"%PY%" -m pip install --upgrade pyinstaller || goto :error

echo [2/3] Building single-file exe ...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --name BiliTabCapture ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "bilix.exe;." ^
    --add-data "VERSION;." ^
    --collect-submodules "yt_dlp" ^
    --collect-submodules "cv2" ^
    app.py || goto :error

echo [3/3] Done.
echo.
echo Output : %~dp0dist\BiliTabCapture.exe
echo Usage  : copy BiliTabCapture.exe to any Windows PC and double-click it.
echo          On first run it extracts bilix.exe and creates BiliTabCapture_cache/
echo          next to the exe to keep cache and Bilibili login cookie.
pause
exit /b 0

:error
echo.
echo [ERROR] Build failed. See the log above.
pause
exit /b 1
