#!/usr/bin/env bash
# build_mac.sh —— 在 macOS 上一键打包出「无需任何环境」即可运行的终端程序，
# 行为与 Windows 的 build_exe.bat（--onefile 控制台程序）一致：运行时有可见的
# 终端窗口显示实时日志，并自动打开浏览器访问本地 Web 界面。
#
# 产物：dist/BiliTabCapture_mac
#   单文件可执行程序（控制台）。拷到任意 Mac，在“终端”中运行它（或双击它，
#   macOS 会让它在终端窗口里跑）即可，无需安装 Python / 依赖
#
# 脚本会自动补齐缺失的运行依赖（读取 requirements.txt），
# 因此新增依赖后无需手动 pip install，直接重跑本脚本即可。
set -euo pipefail
# 脚本含中文注释/输出，强制 UTF-8 区域，避免 bash 在 set -u 下把变量名后紧跟的
# 全角字符误判为变量名的一部分（否则会报 “MACH: unbound variable”）。
export LC_ALL="${LC_ALL:-C.UTF-8}"
export LANG="${LANG:-C.UTF-8}"
cd "$(dirname "$0")"

PY=".venv/bin/python"
REQ="requirements.txt"

echo "==> [1/4] 检查虚拟环境"
if [ ! -x "$PY" ]; then
    echo "[ERROR] 未找到虚拟环境：$PY"
    echo "请先创建并安装依赖："
    echo "    python3 -m venv .venv"
    echo "    .venv/bin/pip install -r requirements.txt"
    exit 1
fi

echo "==> [2/4] 安装运行依赖（自动补齐 requirements.txt 中缺失/过期的包）"
# 关键：以前这里只装 PyInstaller，不装运行依赖，导致“venv 里漏了某个包”
# （例如后来新增的 pymupdf）时，打包照样成功，但产物一运行就报缺库。
"$PY" -m pip install --upgrade -r "$REQ"

echo "==> [3/4] 安装 / 升级 PyInstaller"
"$PY" -m pip install --upgrade pyinstaller

# 打包前自检：确认关键依赖在 venv 里真的能导入，避免打出“缺库”的包。
echo "==> 依赖自检"
"$PY" build_preflight.py

echo "==> [4/4] 构建单文件终端可执行程序（含 templates/static/VERSION）"
# 让 PyInstaller 的缓存/临时目录放在本项目 build/ 下（避免写入 ~/Library 权限不足）。
export PYINSTALLER_CONFIG_DIR="$(pwd)/build/.pyinstaller"
mkdir -p build/.pyinstaller
# pymupdf 不带 PyInstaller hook，且含原生库（_mupdf / libmupdf*），必须用
# --collect-all 才能把「二进制 + 数据 + 子模块」一起收进去；fitz 是其旧别名模块。
"$PY" -m PyInstaller --noconfirm --clean --onefile --name BiliTabCapture_mac \
    --add-data "templates:templates" \
    --add-data "static:static" \
    --add-data "VERSION:." \
    --collect-submodules "cv2" \
    --collect-submodules "curl_cffi" \
    --collect-submodules "qrcode" \
    --hidden-import "qrcode" \
    --collect-all "pymupdf" \
    --collect-all "fitz" \
    app.py

echo "==> 完成"
echo
echo "可执行程序 : dist/BiliTabCapture_mac"
echo "用法       : 把 BiliTabCapture_mac 拷到任意 Mac（无需装 Python/ffmpeg），"
echo "             双击（系统会用终端打开）或在终端里运行它即可。"
echo "             首次运行会在程序旁创建 BiliTabCapture_cache/ 存放缓存与 B 站登录 cookie。"
exit 0
