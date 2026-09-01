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

rem ---- 准备随包附带的 ffmpeg.exe ----
if exist "ffmpeg.exe" (
    set "FFMPEG_EXE=ffmpeg.exe"
) else (
    echo [ERROR] 未找到 ffmpeg.exe 来随程序打包。
    echo         请下载 Windows 版 ffmpeg 并把 ffmpeg.exe 放到本项目根目录,
    echo         或用环境变量 FFMPEG 指定完整路径后重试,如:
    echo             set "FFMPEG=C:\ffmpeg\bin\ffmpeg.exe"
    exit /b 1
)

echo [1/4] Installing / upgrading PyInstaller ...
"%PY%" -m pip install --upgrade pyinstaller || goto :error

echo [2/4] Building single-file exe ...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --name BiliTabCapture ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "VERSION;." ^
    --add-binary "%FFMPEG_EXE%;." ^
    --collect-submodules "cv2" ^
    --collect-submodules "curl_cffi" ^
    --collect-submodules "qrcode" ^
    --hidden-import "qrcode" ^
    app.py || goto :error

echo [3/4] Done.
echo.
echo Output : %~dp0dist\BiliTabCapture.exe
echo Usage  : copy BiliTabCapture.exe to any Windows PC and double-click it.
echo          It self-extracts and starts the local web service, opening the
echo          browser automatically. No Python / ffmpeg needed (ffmpeg is bundled).
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
