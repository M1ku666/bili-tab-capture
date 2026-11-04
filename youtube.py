"""YouTube 支持：链接解析、元数据探测、视频/音频下载、封面。

与 `bili.py` 同一套约定（见 AGENTS.md「关键约定」第 2、4 条）：
- **不做 ffmpeg 合并**：只下**单条**视频轨（优先 H.264/avc1 的 mp4，OpenCV 一定能读），
  抽帧只需要画面；`with_audio=True` 时另下一条 m4a 音轨存成同目录的 `audio.m4a`，
  只给第 4 步导出 psz 当伴奏用。
- 视频文件统一命名为 `<video_id>.<ext>`；音轨只能叫 `audio.m4a`，
  不能落进 `VIDEO_FILE_EXTENSIONS`，否则会被 `find_video_file()` 当成视频挑走。
- 下载后写 `.dlqh.txt`（OpenCV 实测帧高），预览角标以它为准。

yt-dlp 是**可选依赖、延迟导入**：没装时只有真正导入 YouTube 视频才报错，
B 站 / 本地 / 图片 / PDF 都不受影响。

YouTube 风控提示：遇到 “Sign in to confirm you're not a bot” 时，可把浏览器导出的
Netscape 格式 cookies 放到数据目录下的 `youtube_cookies.txt`（与 B 站 cookie 同目录）。
新版 yt-dlp 解析 YouTube 还可能需要 JS 运行时（如 deno），见 yt-dlp 文档。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, urlparse

from runtime_paths import data_dir

AUDIO_FILE_NAME = "audio.m4a"
COOKIE_FILE_NAME = "youtube_cookies.txt"
DEFAULT_MAX_HEIGHT = 1080

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")


# --------------------------------------------------------------------------
# 链接解析
# --------------------------------------------------------------------------
def _host(value: str) -> str:
    try:
        return urlparse(value).netloc.lower().split(":")[0]
    except ValueError:
        return ""


def is_youtube_url(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    host = _host(value)
    return any(host == h or host.endswith("." + h) for h in _YT_HOSTS)


def extract_video_id(value: str) -> Optional[str]:
    """从各种 YouTube 链接（watch / youtu.be / shorts / embed / live）取 11 位视频 ID。

    也接受裸 ID（11 位 `[A-Za-z0-9_-]`；B 站 BV 号是 12 位，不会冲突）。
    """
    value = (value or "").strip()
    if not value:
        return None
    if _ID_RE.match(value):
        return value
    if not is_youtube_url(value):
        return None
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    host = _host(value)
    parts = [p for p in parsed.path.split("/") if p]
    candidate: Optional[str] = None
    if host == "youtu.be" or host.endswith(".youtu.be"):
        candidate = parts[0] if parts else None
    else:
        qs = parse_qs(parsed.query)
        if qs.get("v"):
            candidate = qs["v"][0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v", "e"):
            candidate = parts[1]
    if candidate and _ID_RE.match(candidate):
        return candidate
    return None


def looks_like_youtube(value: str) -> bool:
    """导入框里的内容是不是 YouTube（链接或裸 ID）。"""
    return extract_video_id(value) is not None


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def thumbnail_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


# --------------------------------------------------------------------------
# yt-dlp
# --------------------------------------------------------------------------
def _yt_dlp():
    try:
        import yt_dlp  # noqa: WPS433 - 延迟导入：可选依赖
    except ImportError as exc:  # pragma: no cover - 取决于环境
        raise RuntimeError(
            "缺少 YouTube 支持库 yt-dlp，请先执行：pip install yt-dlp"
        ) from exc
    return yt_dlp


def cookie_path() -> Path:
    return data_dir() / COOKIE_FILE_NAME


def _base_opts(quiet: bool = True) -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "quiet": quiet,
        "no_warnings": quiet,
        "noprogress": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "overwrites": True,
        "continuedl": True,
    }
    cookies = cookie_path()
    if cookies.is_file():
        opts["cookiefile"] = str(cookies)
    return opts


def video_format(max_height: int = DEFAULT_MAX_HEIGHT) -> str:
    """单文件视频格式（**不需要 ffmpeg 合并**）。

    依次：H.264 mp4 纯视频轨 → 任意 mp4 纯视频轨 → 任意纯视频轨 → 带音频的单文件。
    优先 avc1 是因为 opencv-python 自带的解码器对 VP9/AV1 的支持因平台而异。
    """
    h = int(max_height)
    return "/".join([
        f"bv[vcodec^=avc1][height<={h}][ext=mp4]",
        f"bv[height<={h}][ext=mp4]",
        f"bv[height<={h}]",
        f"b[height<={h}][ext=mp4]",
        f"b[height<={h}]",
        "b",
    ])


AUDIO_FORMAT = "ba[ext=m4a]/ba[acodec^=mp4a]"


def _clean_error(exc: Exception) -> str:
    msg = str(exc).strip()
    msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)  # 去掉终端颜色码
    if msg.startswith("ERROR: "):
        msg = msg[len("ERROR: "):]
    if "confirm you" in msg and "bot" in msg:
        msg += f"（可把浏览器导出的 cookies 放到 {cookie_path()} 后重试）"
    return msg or exc.__class__.__name__


def probe_metadata(url: str) -> Dict[str, Any]:
    """返回 {id, title, channel, duration, url}；不下载。"""
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("无法识别该 YouTube 链接。")
    yt_dlp = _yt_dlp()
    opts = _base_opts()
    opts["skip_download"] = True
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical_url(video_id), download=False) or {}
    except Exception as exc:
        raise RuntimeError(f"YouTube 信息获取失败：{_clean_error(exc)}") from exc
    duration = info.get("duration")
    return {
        "id": info.get("id") or video_id,
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration": float(duration) if duration is not None else None,
        "url": canonical_url(info.get("id") or video_id),
    }


def _record_quality(path: Path, output_dir: Path, format_height: Optional[int]) -> None:
    try:
        import cv2
        cap = cv2.VideoCapture(str(path))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) if cap.isOpened() else 0
        cap.release()
    except Exception:
        h = 0
    h = h or int(format_height or 0)
    try:
        (output_dir / ".dlqh.txt").write_text(str(h) if h else "", encoding="utf-8")
    except OSError:
        pass


def _download_audio(video_id: str, output_dir: Path) -> Optional[Path]:
    """下 m4a 音轨到 `output_dir/audio.m4a`；拿不到就 None（不影响视频）。"""
    yt_dlp = _yt_dlp()
    opts = _base_opts()
    opts["format"] = AUDIO_FORMAT
    opts["outtmpl"] = {"default": str(Path(output_dir) / "audio.%(ext)s")}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical_url(video_id), download=True) or {}
    except Exception as exc:
        print(f"音频轨下载失败：{_clean_error(exc)}")
        return None
    ext = (info.get("ext") or "").lower()
    out = Path(output_dir) / AUDIO_FILE_NAME
    if ext != "m4a":
        # 不是 m4a 就不要（且别留着：非 m4a 扩展名可能被当成视频文件挑走）。
        stray = Path(output_dir) / f"audio.{ext}" if ext else None
        if stray is not None and stray.exists() and stray != out:
            stray.unlink(missing_ok=True)
        return None
    return out if out.is_file() and out.stat().st_size > 0 else None


def download_video(
    url: str,
    output_dir: Path,
    max_height: int = DEFAULT_MAX_HEIGHT,
    with_audio: bool = False,
    progress: Optional[Callable[[float], None]] = None,
) -> Path:
    """下载 YouTube 视频（单条视频轨）到 `output_dir/<id>.<ext>`，返回文件路径。"""
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("无法识别该 YouTube 链接。")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    yt_dlp = _yt_dlp()
    opts = _base_opts()
    opts["format"] = video_format(max_height)
    opts["outtmpl"] = {"default": str(output_dir / "%(id)s.%(ext)s")}
    if progress is not None:
        def _hook(d: Dict[str, Any]) -> None:
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes")
            if total and done is not None:
                try:
                    progress(min(1.0, float(done) / float(total)))
                except Exception:
                    pass
        opts["progress_hooks"] = [_hook]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical_url(video_id), download=True) or {}
            filename = info.get("filepath") or (
                (info.get("requested_downloads") or [{}])[0].get("filepath")
            ) or ydl.prepare_filename(info)
    except Exception as exc:
        raise RuntimeError(f"YouTube 下载失败：{_clean_error(exc)}") from exc

    path = Path(filename)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("YouTube 下载失败：未得到视频文件。")
    _record_quality(path, output_dir, info.get("height"))

    if with_audio:
        audio = _download_audio(video_id, output_dir)
        print("音频轨：%s" % (audio.name if audio else "未取到，这次导出没有音频"))
    return path


def fetch_thumbnail(video_id: str, timeout: float = 8) -> Optional[bytes]:
    """视频封面（hqdefault.jpg）。失败返回 None。"""
    if not video_id or not _ID_RE.match(video_id):
        return None
    try:
        import net_tls
        data = net_tls.download_bytes(thumbnail_url(video_id), timeout=timeout)
    except Exception:
        return None
    return data or None
