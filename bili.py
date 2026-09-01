"""纯 Python 实现的哔哩哔哩扫码登录与视频下载。

直接用 curl_cffi 调用 B 站扫码登录 / 播放地址接口，纯 Python 实现，可跨
macOS / Linux / Windows 运行。
"""

import base64
import io
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import qrcode
from curl_cffi import requests as curl_requests

from runtime_paths import data_dir, resource_dir

COOKIE_PATH = data_dir() / "cookie.txt"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0"
_BASE_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}

_session = curl_requests.Session(headers=_BASE_HEADERS, impersonate="chrome124")

_PLAYINFO_RE = re.compile(r"window\.__playinfo__\s*=\s*(\{.*?})\s*</script>", re.DOTALL)
_INITIAL_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?})\s*;", re.DOTALL)
_PLAYURL_SSR_RE = re.compile(r"const\s+playurlSSRData\s*=\s*(\{.*?})\s", re.DOTALL)


def read_cookie() -> Optional[str]:
    if COOKIE_PATH.exists():
        return COOKIE_PATH.read_text(encoding="utf-8").strip() or None
    return None


def write_cookie(cookie: str) -> None:
    COOKIE_PATH.write_text(cookie, encoding="utf-8")


def clear_cookie() -> None:
    if COOKIE_PATH.exists():
        COOKIE_PATH.unlink()


def qrcode_login_generate() -> "tuple[str, str]":
    """生成登录二维码，返回 (qrcode_key, data-uri 格式的 PNG)。"""
    url = (
        "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
        "?source=main-fe-header&go_url=https:%2F%2Fwww.bilibili.com%2F&web_location=333.1007"
    )
    resp = _session.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()["data"]

    img = qrcode.make(data["url"])
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return data["qrcode_key"], f"data:image/png;base64,{encoded}"


def qrcode_login_poll(qrcode_key: str, timeout: float = 180.0, interval: float = 1.5) -> str:
    """轮询扫码状态，登录成功后返回可用的 Cookie 字符串。"""
    url = (
        "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
        f"?qrcode_key={qrcode_key}&source=main_web&web_location=333.1228"
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = _session.get(url, timeout=15)
        resp.raise_for_status()
        body = resp.json()["data"]
        code = body["code"]

        if code == 0:
            cookie_str = "; ".join(f"{k}={v}" for k, v in _session.cookies.items())
            if not cookie_str:
                raise RuntimeError("登录成功但未获取到 Cookie，请重试。")
            return cookie_str
        if code == 86038:
            raise RuntimeError("二维码已失效，请重新获取。")

        time.sleep(interval)
    raise TimeoutError("登录超时，请重试。")


def _extract_json(pattern: re.Pattern, text: str):
    match = pattern.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _parse_page(url: str, cookie: Optional[str]) -> dict:
    headers = dict(_BASE_HEADERS)
    headers["Referer"] = url
    if cookie:
        headers["Cookie"] = cookie
    resp = _session.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    html = resp.text
    return {
        "playinfo": _extract_json(_PLAYINFO_RE, html),
        "initial_state": _extract_json(_INITIAL_STATE_RE, html),
        "playurl_ssr_data": _extract_json(_PLAYURL_SSR_RE, html),
    }


def _find_dash(parsed: dict) -> dict:
    playurl_ssr = parsed.get("playurl_ssr_data")
    if playurl_ssr:
        result = playurl_ssr.get("result")
        raw = playurl_ssr.get("raw")
        if result:
            dash = result.get("video_info", {}).get("dash")
            if dash:
                return dash
        if raw:
            dash = raw.get("data", {}).get("video_info", {}).get("dash")
            if dash:
                return dash

    playinfo = parsed.get("playinfo")
    if playinfo:
        dash = playinfo.get("data", {}).get("dash")
        if dash:
            return dash

    raise RuntimeError("无法获取播放地址，可能需要登录或该视频不支持在线播放。")


def _download_stream(url: str, headers: dict, dest: Path) -> None:
    resp = _session.get(url, headers=headers, stream=True, timeout=30)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)


def find_ffmpeg() -> str:
    """查找可用的 ffmpeg。

    打包时（build_mac.sh / build_exe.bat）会把 ffmpeg 二进制带进包内，
    这里优先使用随包附带的版本（无需在目标机器额外安装）；未打包运行或
    打包脚本未附带上时，回退到系统 PATH 中的 ffmpeg。
    """
    # 随包附带的 ffmpeg：macOS 二进制名 ffmpeg；Windows 为 ffmpeg.exe。
    candidates = [
        resource_dir() / "ffmpeg",
        resource_dir() / "ffmpeg.exe",
        data_dir() / "ffmpeg",
        data_dir() / "ffmpeg.exe",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)

    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError(
            "未找到 ffmpeg。请安装它（macOS：brew install ffmpeg；Windows/Linux："
            "下载 ffmpeg 并加入 PATH），或在打包时随程序附带 ffmpeg 二进制。"
        )
    return path


def merge_av(video_file: Path, audio_file: Path, output_file: Path) -> None:
    ffmpeg = find_ffmpeg()
    command = [ffmpeg, "-y", "-i", str(video_file), "-i", str(audio_file), "-c", "copy", str(output_file)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"ffmpeg 合并音视频失败：{detail[-500:]}")


def download_bilibili_video_native(
    url: str,
    output_dir: Path,
    quality: Optional[int] = None,
    cookie: Optional[str] = None,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    parsed = _parse_page(url, cookie)
    dash = _find_dash(parsed)

    videos = dash.get("video") or []
    audios = dash.get("audio") or []
    if not videos or not audios:
        raise RuntimeError("未找到可下载的音视频流。")

    selected = None
    if quality:
        selected = next((v for v in videos if v.get("id") == quality), None)
    if not selected:
        selected = max(videos, key=lambda v: v.get("id", 0))
    audio = max(audios, key=lambda a: a.get("bandwidth", 0))

    headers = dict(_BASE_HEADERS)
    headers["Referer"] = url
    if cookie:
        headers["Cookie"] = cookie

    video_tmp = output_dir / "_video.m4s"
    audio_tmp = output_dir / "_audio.m4s"
    try:
        _download_stream(selected.get("baseUrl") or selected.get("base_url"), headers, video_tmp)
        _download_stream(audio.get("baseUrl") or audio.get("base_url"), headers, audio_tmp)

        output_path = output_dir / "video.mp4"
        merge_av(video_tmp, audio_tmp, output_path)
    finally:
        video_tmp.unlink(missing_ok=True)
        audio_tmp.unlink(missing_ok=True)

    return output_path
