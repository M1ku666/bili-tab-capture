#!/usr/bin/env bash
# build_mac.sh —— 在 macOS 上一键打包出「无需任何环境」即可运行的终端程序，
# 行为与 Windows 的 build_exe.bat（--onefile 控制台程序）一致：运行时有可见的
# 终端窗口显示实时日志，并自动打开浏览器访问本地 Web 界面。
#
# 产物：dist/BiliTabCapture_mac
#   单文件可执行程序（控制台）。拷到任意 Mac，在“终端”中运行它（或双击它，
#   macOS 会让它在终端窗口里跑）即可，无需安装 Python / 依赖
#
# 依赖：本机需已安装 Python 虚拟环境 .venv（含 PyInstaller）。
set -euo pipefail
# 脚本含中文注释/输出，强制 UTF-8 区域，避免 bash 在 set -u 下把变量名后紧跟的
# 全角字符误判为变量名的一部分（否则会报 “MACH: unbound variable”）。
export LC_ALL="${LC_ALL:-C.UTF-8}"
export LANG="${LANG:-C.UTF-8}"
cd "$(dirname "$0")"

PY=".venv/bin/python"

echo "==> [1/3] 检查虚拟环境"
if [ ! -x "$PY" ]; then
    echo "[ERROR] 未找到虚拟环境：$PY"
    echo "请先创建并安装依赖："
    echo "    python3 -m venv .venv"
    echo "    .venv/bin/pip install -r requirements.txt"
    exit 1
fi

echo "==> [2/3] 安装 / 升级 PyInstaller"
"$PY" -m pip install --upgrade pyinstaller

echo "==> [3/3] 构建单文件终端可执行程序（含 templates/static/VERSION）"
# 让 PyInstaller 的缓存/临时目录放在本项目 build/ 下（避免写入 ~/Library 权限不足）。
export PYINSTALLER_CONFIG_DIR="$(pwd)/build/.pyinstaller"
mkdir -p build/.pyinstaller
"$PY" -m PyInstaller --noconfirm --clean --onefile --name BiliTabCapture_mac \
    --add-data "templates:templates" \
    --add-data "static:static" \
    --add-data "VERSION:." \
    --collect-submodules "cv2" \
    --collect-submodules "curl_cffi" \
    --collect-submodules "qrcode" \
    --hidden-import "qrcode" \
    app.py

echo "==> 完成"
echo
echo "可执行程序 : dist/BiliTabCapture_mac"
echo "用法       : 把 BiliTabCapture_mac 拷到任意 Mac（无需装 Python/ffmpeg），"
echo "             双击（系统会用终端打开）或在终端里运行它即可。"
echo "             首次运行会在程序旁创建 BiliTabCapture_cache/ 存放缓存与 B 站登录 cookie。"
exit 0
