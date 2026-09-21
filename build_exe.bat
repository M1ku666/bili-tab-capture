@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

REM NOTE: keep this file ASCII-only. Mixing CJK comments into a .bat can be
REM mis-parsed by cmd.exe before/around chcp takes effect. Chinese docs live in
REM build_mac.sh and build_preflight.py instead.

set "PY=.venv\Scripts\python.exe"
set "REQ=requirements.txt"

if not exist "%PY%" (
    echo [ERROR] Virtualenv not found: %PY%
    echo Please create a virtualenv and install dependencies first:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

echo [1/5] Installing runtime dependencies from %REQ% ...
REM This step used to be missing: only PyInstaller was installed, so a package
REM added later (e.g. pymupdf) stayed absent from the venv -- the build still
REM succeeded, but the produced exe failed at runtime with "missing library".
"%PY%" -m pip install --upgrade -r "%REQ%" || goto :error

echo [2/5] Installing / upgrading PyInstaller ...
"%PY%" -m pip install --upgrade pyinstaller || goto :error

echo [3/5] Verifying that key dependencies can be imported ...
REM Fail fast (with a precise list) instead of shipping an exe that cannot
REM import its own dependencies.
"%PY%" build_preflight.py || goto :error

echo [4/5] Building single-file exe ...
REM pymupdf ships no PyInstaller hook and carries native libraries
REM (_mupdf / libmupdf*). --collect-submodules alone would drop those binaries,
REM so --collect-all is required; fitz is its legacy alias module.
"%PY%" -m PyInstaller --noconfirm --clean --onefile --name BiliTabCapture ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "VERSION;." ^
    --collect-submodules "cv2" ^
    --collect-submodules "curl_cffi" ^
    --collect-submodules "qrcode" ^
    --hidden-import "qrcode" ^
    --collect-all "pymupdf" ^
    --collect-all "fitz" ^
    app.py || goto :error

echo [5/5] Done.
echo.
echo Output : %~dp0dist\BiliTabCapture.exe
echo Usage  : copy BiliTabCapture.exe to any Windows PC and double-click it.
echo          It self-extracts and starts the local web service, opening the
echo          browser automatically. No Python needed.
echo.
echo          On first run it creates BiliTabCapture_cache/ next to the exe to
echo          keep cache and the Bilibili login cookie.
pause
exit /b 0

:error
echo.
echo [ERROR] Build failed. See the log above.
pause
exit /b 1
