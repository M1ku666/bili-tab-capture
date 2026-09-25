"""打包前置检查：确认 venv 里所有运行依赖都能真正导入。

为什么需要它：打包脚本以前只安装 PyInstaller、不安装 `requirements.txt`，
于是“venv 里漏了某个包”（例如后来新增的 pymupdf）时打包照样成功，
产物却一运行就报缺库。本脚本在**打包前**先验一遍，快速失败并明确指出缺哪个。

注意用 `import_module` 真导入，而不是 `find_spec` 只找文件——像 pymupdf 这种
带原生库（_mupdf / libmupdf*）的包，可能“找得到但加载失败”。

用法：python build_preflight.py
退出码：0 = 全部可用；1 = 有缺失（会打印缺失清单）
"""

from __future__ import annotations

import importlib
import sys

# 与 requirements.txt 对应的**导入名**（发行名 ≠ 导入名，如 Pillow→PIL、opencv-python→cv2）
REQUIRED_MODULES = [
    ("Flask", "flask"),
    ("numpy", "numpy"),
    ("opencv-python", "cv2"),
    ("Pillow", "PIL"),
    ("curl_cffi", "curl_cffi"),
    ("qrcode", "qrcode"),
    ("pymupdf", "pymupdf"),  # PDF 渲染（导入名与发行名一致）
    ("certifi", "certifi"),  # HTTPS CA bundle（缺失会导致更新检查报证书校验失败）
]


def main() -> int:
    missing: list[str] = []
    for dist_name, module_name in REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - 要把任何加载失败都报出来
            missing.append(f"{dist_name} (import {module_name} 失败: {exc})")

    if missing:
        print("[ERROR] 以下依赖无法导入，请先执行：")
        print("    pip install -r requirements.txt")
        print("缺失清单：")
        for item in missing:
            print(f"  - {item}")
        return 1

    print("    所有关键依赖均可正常导入：")
    print("      " + ", ".join(dist for dist, _ in REQUIRED_MODULES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
