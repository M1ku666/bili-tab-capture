"""纯 Python 实现的哔哩哔哩扫码登录与视频下载。

直接用 curl_cffi 调用 B 站扫码登录 / 播放地址接口，纯 Python 实现，可跨
macOS / Linux / Windows 运行。
"""

import base64
import io
import json
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

# 音频轨固定存这个文件名（和视频同目录）。**扩展名不能在 VIDEO_FILE_EXTENSIONS 里**，
# 否则 `find_video_file` 会把音频当成视频挑走；`.m4a` 正好也是这段内容的正确后缀。
AUDIO_FILE_NAME = "audio.m4a"

# DASH 音频轨里能直接当 .m4a 播的 AAC 档：30216=64k / 30232=132k / 30280=192k。
# **认的是音频轨的 `id`，不是 `codecid`**（实测音频轨的 codecid 一律是 0；`mimeType` 都是 audio/mp4）。
# 杜比(EC-3)与 Hi-Res(FLAC) 分别在 dash.dolby / dash.flac 下、不在 dash.audio 里，浏览器也未必解得了。
_AAC_AUDIO_IDS = (30216, 30232, 30280)


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


# --- 统一请求入口：浏览器指纹 + 主页热身 + 风控(412)降级 ---------------------
#
# 为什么 B 站请求不能走标准库 urllib / 裸 requests：
# B 站风控按 **TLS/HTTP 指纹** 判定脚本，命中即返回 `HTTP 412 Precondition Failed`
# （实测：urllib 请求 view 接口与视频页均为 412，即使补齐 Cookie 与整套浏览器头也一样；
# 换成 curl_cffi 的 impersonate 立刻 200）。海外 / 机房 IP 的判定阈值更低，
# 所以海外用户"一导入就 412"。本模块统一走下面的入口，避免各处各写一套。

_warmed_up = False

_RISK_CONTROL_HINT = (
    "B 站风控拦截(HTTP 412)：当前网络环境被判定为异常请求，常见于海外或机房 IP。"
    "已自动降级重试仍失败，请稍后重试或更换网络。"
)


def warm_up(force: bool = False) -> None:
    """访问一次 B 站主页，让会话带上 buvid3 / b_nut 等风控 Cookie。

    指纹问题由 `impersonate` 解决；这里再补一份 Cookie 画像，进一步降低被拦概率。
    失败不抛异常（只是少一层保险，不影响后续请求）。
    """
    global _warmed_up
    if _warmed_up and not force:
        return
    _warmed_up = True
    try:
        _session.get("https://www.bilibili.com/", timeout=10, impersonate="chrome124")
    except Exception:
        pass


def bili_get(url: str, cookie: Optional[str] = None, timeout: float = 15,
             headers: Optional[dict] = None):
    """**所有 B 站请求的统一入口**：浏览器指纹 + 热身，412(风控) 时自动降级重试。

    重试阶梯：先用传入的 Cookie（通常是登录态），被拦则换游客态并重新热身
    （换一份新的 buvid）。返回 curl_cffi 的 Response。
    """
    plan: list = [(cookie, False)] if cookie else [(None, False)]
    plan.append((None, True))  # 游客态 + 重新热身

    last_error: Optional[Exception] = None
    for use_cookie, force in plan:
        merged = _session_headers(url, use_cookie)
        if headers:
            merged.update(headers)
        warm_up(force=force)
        try:
            resp = _session.get(url, headers=merged, timeout=timeout,
                                impersonate="chrome124")
        except Exception as exc:
            last_error = exc
            continue
        if resp.status_code != 412:
            return resp
        try:
            resp.close()
        except Exception:
            pass
        last_error = RuntimeError(_RISK_CONTROL_HINT)

    raise last_error if last_error is not None else RuntimeError("B 站请求失败。")


def get_json(url: str, cookie: Optional[str] = None, timeout: float = 15) -> dict:
    """请求一个 B 站 JSON 接口并解析（含 412 风控降级）。"""
    resp = bili_get(url, cookie=cookie, timeout=timeout,
                    headers={"Accept": "application/json, text/plain, */*"})
    resp.raise_for_status()
    return resp.json()


def resolve_short_url(url: str, timeout: float = 20) -> str:
    """展开 b23.tv 短链等跳转，返回最终 URL；失败时原样返回。"""
    try:
        resp = bili_get(url, timeout=timeout,
                        headers={"Accept": "text/html,application/xhtml+xml"})
        return str(resp.url or url)
    except Exception:
        return url


def extract_part(url: str) -> int:
    """链接里的分 P 号（`?p=5` → 5），缺省 1。"""
    m = re.search(r"[?&]p=(\d+)", url or "")
    return max(1, int(m.group(1))) if m else 1


def _get_cid(url: str, cookie: Optional[str]) -> int:
    """从 view 接口拿视频 cid；分 P 视频按链接里的 `p` 取对应那一 P（缺省第 1 P）。"""
    bvid = extract_bvid(url)
    view_url = "https://api.bilibili.com/x/web-interface/view?bvid=" + bvid
    data = get_json(view_url, cookie=cookie, timeout=15).get("data") or {}
    pages = data.get("pages") or []
    part = extract_part(url)
    if pages and part > len(pages):
        raise RuntimeError("该视频只有 %d 个分 P，没有第 %d P。" % (len(pages), part))
    idx = part - 1 if pages else 0
    cid = (pages[idx].get("cid") if pages else None) or data.get("cid")
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
        data = get_json(playurl, cookie=cookie, timeout=15).get("data") or {}
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


def _playinfo_dash(url: str, cookie: Optional[str]) -> dict:
    """取视频页 SSR(`window.__playinfo__`) 里的 `dash` 段；拿不到就返回 {}。

    视频轨与音频轨都在这一段里，所以一次取、两边用（别为音频再抓一遍页面）。
    """
    try:
        html = bili_get(url, cookie=cookie, timeout=15,
                        headers={"Accept": "text/html,application/xhtml+xml"}).text
    except Exception:
        return {}
    m = re.search(r'window\.__playinfo__\s*=\s*(\{.*?\})\s*</script>', html, re.S)
    if not m:
        return {}
    try:
        return (json.loads(m.group(1)).get("data") or {}).get("dash") or {}
    except Exception:
        return {}


def _video_picks(dash: dict, max_qn: Optional[int]) -> list:
    """DASH 视频轨候选 [(videoid, codecid, baseUrl)]；只要 AVC(codecid=7)，OpenCV 才读得了。"""
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


def _audio_picks(dash: dict) -> list:
    """DASH 音频轨候选 [(audioid, codecid, baseUrl)]，码率高的在前（id 越大码率越高）。"""
    tracks = [
        a for a in (dash.get("audio") or [])
        if (a.get("baseUrl") or a.get("base_url"))
    ]
    aac = [a for a in tracks if int(a.get("id") or 0) in _AAC_AUDIO_IDS]
    # id 认不出来时（B 站以后加了新档）退一步：dash.audio 里 mime 是 audio/mp4 的都能当 .m4a
    picks = aac or [a for a in tracks if (a.get("mimeType") or "") == "audio/mp4"]
    out = [
        (int(a.get("id") or 0), int(a.get("codecid") or 0), a.get("baseUrl") or a.get("base_url"))
        for a in picks
    ]
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def dash_video_candidates(url: str, cookie: Optional[str], max_qn: Optional[int]) -> list:
    """从视频页 SSR(playinfo) 取 DASH 视频轨候选；返回 [(videoid, codecid, baseUrl)]"""
    return _video_picks(_playinfo_dash(url, cookie), max_qn)


def dash_audio_candidates(url: str, cookie: Optional[str]) -> list:
    """从视频页 SSR(playinfo) 取 DASH 音频轨候选（只取能当 .m4a 播的 AAC 档）。"""
    return _audio_picks(_playinfo_dash(url, cookie))


def _download_audio_track(url: str, output_dir: Path, cookie: Optional[str], dash: dict) -> Optional[Path]:
    """跟着视频一起把 DASH 音频轨下到 `output_dir/audio.m4a`；下不到返回 None。

    **不抛异常**：音频只是 psz 的附加内容，不该因为它拖垮视频下载（制谱本来只要画面）。
    先写 `.part` 再改名，避免半个文件被当成可用音频捡走。
    """
    for _aid, _cc, base in _audio_picks(dash)[:3]:
        try:
            if not _probe_ok(base, _session_headers(url, cookie)):
                continue
            out = Path(output_dir) / AUDIO_FILE_NAME
            tmp = out.with_name(out.name + ".part")
            _download_stream(base, _session_headers(url, cookie), tmp)
            if tmp.stat().st_size > 0:
                tmp.replace(out)
                return out
            tmp.unlink(missing_ok=True)
        except Exception:
            continue
    return None


def download_bilibili_video_native(
    url: str,
    output_dir: Path,
    quality: Optional[int] = None,
    cookie: Optional[str] = None,
    with_audio: bool = False,
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
        # 1) DASH 视频轨 —— SSR; 仅视频便于 OpenCV/取帧（音频按需另下，见 with_audio）
        try:
            dash = _playinfo_dash(url, use_cookie)
            picks = _video_picks(dash, quality)
            picks.sort(key=lambda x: x[0], reverse=True)
            for vid, cc, base in picks[:6]:
                if not _probe_ok(base, _session_headers(url, use_cookie)):
                    continue
                out = output_dir / "video.m4s"
                _download_stream(base, _session_headers(url, use_cookie), out)
                _record(out, vid)
                if with_audio:
                    audio = _download_audio_track(url, output_dir, use_cookie, dash)
                    print("音频轨：%s" % (audio.name if audio else "未取到，这次导出没有音频"))
                return out
        except Exception as exc:
            last = exc
        # 2) 回退单文件 mp4(durl) —— 音视频是混在一起的，没有独立音轨可拿（不引入 ffmpeg 去拆），
        #    所以这条路上导出 psz 不会带音频。
        try:
            direct, qn = _find_durl(url, cid, use_cookie, quality)
            out = output_dir / "video.mp4"
            _download_stream(direct, _session_headers(url, use_cookie), out)
            _record(out, qn)
            return out
        except Exception as exc:
            last = exc
    raise last if last else RuntimeError("下载失败。")
