"""打包后（PyInstaller）与源码运行时的路径解析。

单文件（onefile）/应用包模式下，PyInstaller 会把模板、静态文件等资源解压到
一个临时目录（sys._MEIPASS），而可写的数据（缓存、B 站登录 cookie）则放在
可执行文件旁边的目录里，这样每次运行后数据不会丢失。
"""

import sys
from pathlib import Path

_FROZEN = bool(getattr(sys, "frozen", False))


def is_frozen() -> bool:
    return _FROZEN


def resource_dir() -> Path:
    """只读的打包资源目录：模板、静态文件等。"""
    if _FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """可写的数据目录：可执行文件所在目录（源码运行时则为源码目录）。"""
    if _FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
