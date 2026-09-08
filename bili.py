"""纯 Python 实现的哔哩哔哩扫码登录与视频下载。

直接用 curl_cffi 调用 B 站扫码登录 / 播放地址接口，纯 Python 实现，可跨
macOS / Linux / Windows 运行。
"""

import base64
import io
import re
import time
from pathlib import Path
from typing import Optional

import qrcode
from curl_cffi import requests as curl_requests

from runtime_paths import data_dir

COOKIE_PATH = data_dir() / "cookie.txt"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0"
_BASE_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}

_session = curl_requests.Session(headers=_BASE_HEADERS, impersonate="chrome124")

# 单文件 MP4 流的可尝试清晰度（qn），从高到低。未登录时 B 站会自动降到可用档。
_FALLBACK_QN = (116, 112, 80, 64, 32, 16)


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


def _session_headers(url: str, cookie: Optional[str]) -> dict:
    headers = dict(_BASE_HEADERS)
    headers["Referer"] = url
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _get_cid(url: str, cookie: Optional[str]) -> int:
    """从 view 接口拿视频 cid（分 P 取第一个）。"""
    bvid = extract_bvid(url)
    view_url = "https://api.bilibili.com/x/web-interface/view?bvid=" + bvid
    resp = _session.get(view_url, headers=_session_headers(url, cookie), timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    pages = data.get("pages") or []
    cid = (pages[0].get("cid") if pages else None) or data.get("cid")
    if not cid:
        raise RuntimeError("无法获取该视频的 cid。")
    return int(cid)


def extract_bvid(url: str) -> str:
    m = re.search(r"BV[0-9A-Za-z]{10}", url)
    if not m:
        raise ValueError("无法从链接中解析 BV 号。")
    return m.group(0)


def _probe_ok(url: str, headers: dict) -> bool:
    """试探该直链能否真正下到第一块(而非返回 4xx 放防盗页面)。"""
    try:
        resp = _session.get(url, headers=headers, stream=True, timeout=12,
                            impersonate="chrome124")
        try:
            if resp.status_code != 200:
                return False
            next(resp.iter_content(chunk_size=1), None)  # 真实读，有些会延迟返回状态
            return True
        finally:
            resp.close()
    except Exception:
        return False


def _find_durl(url: str, cid: int, cookie: Optional[str], quality: Optional[int]) -> "tuple[str, int]":
    """请求 playurl 拿单文件 MP4 直链；返回 (可下载url, 所用清晰度qn)。

    登录态下个别视频高清单文件流会 404(防盗链); 这里逐档试到能真正取到为止。
    """
    bvid = extract_bvid(url)
    attempts = []
    if quality is not None:
        attempts.append(quality)
    for q in _FALLBACK_QN:
        if q not in attempts:
            attempts.append(q)

    for q in attempts:
        playurl = (
            "https://api.bilibili.com/x/player/playurl?bvid=%s&cid=%s&qn=%s&fnval=0&fnver=0&fourk=1"
            % (bvid, cid, q)
        )
        resp = _session.get(playurl, headers=_session_headers(url, cookie), timeout=15,
                            impersonate="chrome124")
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        durl = data.get("durl") or []
        if not durl:
            continue
        direct = durl[0].get("url")
        if not direct:
            continue
        if _probe_ok(direct, _session_headers(url, cookie)):
            return direct, q
    raise RuntimeError("无法获取可下载的 MP4 播放地址，可能需要登录。")


def _download_stream(url: str, headers: dict, dest: Path) -> None:
    resp = _session.get(url, headers=headers, stream=True, timeout=30,
                        impersonate="chrome124")
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)


def dash_video_candidates(url: str, cookie: Optional[str], max_qn: Optional[int]) -> list:
    """从视频页 SSR(playinfo) 取 DASH 视频轨候选；码率 aac? 只要 video codecid=AVC(7) 可读。

    返回 [(videoid, codecid, baseUrl, hasUrl)]
    """
    import re as r, json as j
    try:
        h = _session_headers(url, cookie)
        html = _session.get(url, headers=h, timeout=15, impersonate="chrome124").text
    except Exception:
        return []
    m = r.search(r'window\.__playinfo__\s*=\s*(\{.*?\})\s*</script>', html, r.S)
    if not m:
        return []
    try:
        data = j.loads(m.group(1)).get("data") or {}
    except Exception:
        return []
    dash = data.get("dash") or {}
    out = []
    for v in dash.get("video") or []:
        cc = int(v.get("codecid") or -1)
        base = v.get("baseUrl") or v.get("base_url")
        if cc != 7 or not base:
            continue
        vid = int(v.get("id") or 0)
        if max_qn and vid > max_qn:
            continue
        out.append((vid, cc, base))
    return out


def download_bilibili_video_native(
    url: str,
    output_dir: Path,
    quality: Optional[int] = None,
    cookie: Optional[str] = None,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        cid = _get_cid(url, cookie)
    except Exception:
        cid = _get_cid(url, None)
    qmap = {6:6,16:16,32:32,64:64,74:74,80:80,112:112,116:116,120:120}

    def _record(path, qn):
        # 角标清晰度以“文件实测高”为准（更不容易标题骗过）。取不到再用 qn。
        try:
            import cv2
            cap = cv2.VideoCapture(str(path))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) if cap.isOpened() else 0
            cap.release()
        except Exception:
            h = 0
        try:
            (output_dir / ".dlqh.txt").write_text(str(h) if h else "", encoding="utf-8")
            (output_dir / ".dlqn.txt").write_text(str(qn or ""), encoding="utf-8")
        except OSError:
            pass

    modes = [cookie] if cookie else [None]
    if cookie is not None:
        modes.append(None)
    last = None
    for use_cookie in dict.fromkeys(modes):  # 先去重用次
        # 1) DASH 视频轨(无音频、不合并) —— SSR; 仅视频便于 OpenCV/取帧
        try:
            picks = dash_video_candidates(url, use_cookie, quality)
            picks.sort(key=lambda x: x[0], reverse=True)
            for vid, cc, base in picks[:6]:
                if not _probe_ok(base, _session_headers(url, use_cookie)):
                    continue
                out = output_dir / "video.m4s"
                _download_stream(base, _session_headers(url, use_cookie), out)
                _record(out, vid)
                return out
        except Exception as exc:
            last = exc
        # 2) 回退单文件 mp4(durl)
        try:
            direct, qn = _find_durl(url, cid, use_cookie, quality)
            out = output_dir / "video.mp4"
            _download_stream(direct, _session_headers(url, use_cookie), out)
            _record(out, qn)
            return out
        except Exception as exc:
            last = exc
    raise last if last else RuntimeError("下载失败。")
