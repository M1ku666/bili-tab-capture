"""打包后（PyInstaller）与源码运行时的路径解析。

单文件（onefile）模式下，PyInstaller 会把模板、静态文件、bilix.exe 解压到
一个临时目录（sys._MEIPASS），而可写的数据（缓存、B 站登录 cookie）则放在
exe 旁边的目录里，这样每次运行后数据不会丢失。
"""

import shutil
import sys
from pathlib import Path

_FROZEN = bool(getattr(sys, "frozen", False))


def is_frozen() -> bool:
    return _FROZEN


def resource_dir() -> Path:
    """只读的打包资源目录：模板、静态文件、内置的 bilix.exe。"""
    if _FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """可写的数据目录：exe 所在目录（源码运行时则为源码目录）。"""
    if _FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ensure_bilix() -> Path:
    """返回可用的 bilix.exe 路径。

    单文件模式下首次运行会把内置的 bilix.exe 解压到 exe 旁边，
    这样 bilix 登录生成的 cookie.txt 也能持久保存在 exe 旁边。
    """
    bundled = resource_dir() / "bilix.exe"
    target = data_dir() / "bilix.exe"

    if bundled.exists() and bundled.resolve() != target.resolve():
        try:
            if not target.exists() or bundled.stat().st_size != target.stat().st_size:
                shutil.copy2(bundled, target)
        except OSError:
            return bundled

    return target if target.exists() else bundled
