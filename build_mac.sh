#!/usr/bin/env bash
# build_mac.sh —— 在 macOS 上一键打包出「无需任何环境」即可运行的终端程序，
# 行为与 Windows 的 build_exe.bat（--onefile 控制台程序）一致：运行时有可见的
# 终端窗口显示实时日志，并自动打开浏览器访问本地 Web 界面。
#
# 产物：dist/BiliTabCapture_mac
#   单文件可执行程序（控制台）。拷到任意 Mac，在“终端”中运行它（或双击它，
#   macOS 会让它在终端窗口里跑）即可，无需安装 Python / 依赖 / ffmpeg。
#
# ffmpeg 处理：默认自动获取一个「静态、不依赖 Homebrew」的 macOS ffmpeg 打进包里，
# 这样目标机器上不需要 ffmpeg。获取顺序：
#   1) 环境变量 FFMPEG=/path/to/ffmpeg 指定的静态 ffmpeg
#   2) 项目根目录已存在的 ./ffmpeg（静态）
#   3) 自动下载（arm64 用 osxexperts 的 arm 静态版；x86_64 用 evermeet 静态版）
#      并缓存为 ./ffmpeg，之后不再重复下载。
# 若你提供了动态（依赖 Homebrew）的 ffmpeg，产物将只能在装有该依赖库的机器上运行。
#
# 依赖：本机需已安装 Python 虚拟环境 .venv（含 PyInstaller）。
set -euo pipefail
# 脚本含中文注释/输出，强制 UTF-8 区域，避免 bash 在 set -u 下把变量名后紧跟的
# 全角字符误判为变量名的一部分（否则会报 “MACH: unbound variable”）。
export LC_ALL="${LC_ALL:-C.UTF-8}"
export LANG="${LANG:-C.UTF-8}"
cd "$(dirname "$0")"

PY=".venv/bin/python"
MACH="$(uname -m)"

echo "==> [1/5] 检查虚拟环境"
if [ ! -x "$PY" ]; then
    echo "[ERROR] 未找到虚拟环境：$PY"
    echo "请先创建并安装依赖："
    echo "    python3 -m venv .venv"
    echo "    .venv/bin/pip install -r requirements.txt"
    exit 1
fi

echo "==> [2/5] 准备静态 ffmpeg （架构: ${MACH}）"
fetch_static_ffmpeg() {
    local dest="$1" arch="$2"
    if [ "$arch" = "arm64" ]; then
        echo "   正在下载静态 ffmpeg（arm64，osxexperts）..."
        curl -fsSL -o /tmp/ffmpeg_arm.zip "https://www.osxexperts.net/ffmpeg7arm.zip"
        unzip -o -j /tmp/ffmpeg_arm.zip -d "$(dirname "$dest")" >/dev/null
        mv "$(dirname "$dest")/ffmpeg" "$dest"
    else
        echo "   正在下载静态 ffmpeg（x86_64，evermeet）..."
        curl -fsSL -o /tmp/ffmpeg_x86.zip "https://evermeet.cx/ffmpeg/getrelease/zip"
        unzip -o -j /tmp/ffmpeg_x86.zip -d "$(dirname "$dest")" >/dev/null
        mv "$(dirname "$dest")/ffmpeg" "$dest"
    fi
    chmod +x "$dest"
}

FF=""
if [ -n "${FFMPEG:-}" ] && [ -f "$FFMPEG" ]; then
    FF="$FFMPEG"
    echo "   使用环境变量 FFMPEG：$FF"
elif [ -f "./ffmpeg" ]; then
    FF="$(pwd)/ffmpeg"
    echo "   使用仓库内 ./ffmpeg：$FF"
else
    if curl -sIL --max-time 15 -o /dev/null "https://www.osxexperts.net/ffmpeg7arm.zip"; then
        echo "   [自动下载静态 ffmpeg]"
        fetch_static_ffmpeg "$(pwd)/ffmpeg" "$MACH"
        FF="$(pwd)/ffmpeg"
    else
        echo "[ERROR] 无法自动获取 ffmpeg。请把静态 ffmpeg 命名为 ./ffmpeg 放本项目根目录，"
        echo "       或设置环境变量 FFMPEG=/path/to/ffmpeg。"
        exit 1
    fi
fi
if ! "$FF" -version >/dev/null 2>&1; then
    echo "[ERROR] 无法运行 ffmpeg 二进制：$FF （可能是动态依赖或架构不匹配）"
    exit 1
fi
echo "   ffmpeg：$FF"

echo "==> [3/5] 安装 / 升级 PyInstaller"
"$PY" -m pip install --upgrade pyinstaller

echo "==> [4/5] 构建单文件终端可执行程序（含 templates/static/VERSION/ffmpeg）"
# 让 PyInstaller 的缓存/临时目录放在本项目 build/ 下（避免写入 ~/Library 权限不足）。
export PYINSTALLER_CONFIG_DIR="$(pwd)/build/.pyinstaller"
mkdir -p build/.pyinstaller
"$PY" -m PyInstaller --noconfirm --clean --onefile --name BiliTabCapture_mac \
    --add-data "templates:templates" \
    --add-data "static:static" \
    --add-data "VERSION:." \
    --add-binary "$FF:." \
    --collect-submodules "cv2" \
    --collect-submodules "curl_cffi" \
    --collect-submodules "qrcode" \
    --hidden-import "qrcode" \
    app.py

echo "==> [5/5] 完成"
echo
echo "可执行程序 : dist/BiliTabCapture_mac"
echo "用法       : 把 BiliTabCapture_mac 拷到任意 Mac（无需装 Python/ffmpeg），"
echo "             双击（系统会用终端打开）或在终端里运行它即可。"
echo "             首次运行会在程序旁创建 BiliTabCapture_cache/ 存放缓存与 B 站登录 cookie。"
exit 0
