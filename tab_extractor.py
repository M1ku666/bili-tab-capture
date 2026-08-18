import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat

try:
    from yt_dlp import YoutubeDL
except ImportError:
    YoutubeDL = None


# Compatibilidad con distintas versiones de Pillow
if hasattr(Image, "Resampling"):
    RESAMPLE = Image.Resampling.LANCZOS
else:
    RESAMPLE = Image.LANCZOS


# --- PDF 页眉样式（字体 / 字号可在脚本顶端统一调整）---
# 可选字体：msyh(微软雅黑) simsun(宋体) simhei(黑体) simkai(楷体)
#          arial segoe calibri verdana
HEADER_FONT_FAMILY = "msyh"   # 标题与作者的字体
HEADER_TITLE_SIZE = 64        # 标题字号，作者/链接按比例缩小
HEADER_HEIGHT_RATIO = 0.2     # 标题/作者占页面高度的比例（1=整页，0.1=10%）
HEADER_LINE_HEIGHT_RATIO = 1.2  # 标题/作者行高 = 字号 × 该比例（与前端 CSS line-height 一致）


# --- Bilibili support -----------------------------------------------------

from runtime_paths import ensure_bilix

BILIX_EXE = ensure_bilix()
VIDEO_FILE_EXTENSIONS = (".mp4", ".mkv", ".webm", ".mov")
BILIBILI_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_BILIBILI_BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
_BILIBILI_AV_RE = re.compile(r"\bav(\d+)\b", re.IGNORECASE)

# Bilibili is reachable directly; skip any system proxy so the API responds correctly.
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class VideoMetadata:
    raw_title: Optional[str] = None
    display_title: Optional[str] = None
    channel: Optional[str] = None
    source_url: Optional[str] = None


@dataclass
class ExtractionOptions:
    sample_every_sec: float = 2.0
    crop_y_start_ratio: float = 0.0
    crop_y_end_ratio: float = 1.0
    crop_x_start_ratio: float = 0.0
    crop_x_end_ratio: float = 1.0
    hash_threshold: int = 16
    hash_size: int = 12
    diff_threshold: float = 0.010
    compare_window: int = 1
    debug_diffs: bool = False
    start_sec: float = 0.0
    end_sec: Optional[float] = None
    save_cleaned: bool = False
    band_half_width: int = 90
    min_band_pixels: int = 20
    target_tolerance: int = 48


@dataclass
class ExtractionStats:
    duration: float = 0.0
    start_sec: float = 0.0
    end_sec: float = 0.0
    frames_checked: int = 0
    duplicates_skipped: int = 0
    captures_kept: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "duration": self.duration,
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "frames_checked": self.frames_checked,
            "duplicates_skipped": self.duplicates_skipped,
            "captures_kept": self.captures_kept,
        }


ProgressCallback = Callable[[str, ExtractionStats], None]


def clean_video_title(raw_title: Optional[str]) -> Optional[str]:
    if not raw_title:
        return None

    original = raw_title.strip()
    title = original

    title = re.sub(r"^\([^)]{1,100}\)\s*", "", title).strip()

    parts = re.split(r"\s+-\s+", title)
    if len(parts) > 1:
        suffix = " - ".join(parts[1:]).lower()
        descriptor_keywords = (
            "tab",
            "tabs",
            "lesson",
            "tutorial",
            "guitar",
            "cover",
            "sheet",
            "chord",
        )
        if any(keyword in suffix for keyword in descriptor_keywords):
            title = parts[0].strip()

    return title or original or None


def build_video_metadata(
    raw_title: Optional[str] = None,
    channel: Optional[str] = None,
    source_url: Optional[str] = None,
    title_override: Optional[str] = None,
    channel_override: Optional[str] = None,
) -> VideoMetadata:
    title_override = title_override.strip() if title_override else None
    channel_override = channel_override.strip() if channel_override else None
    raw_title = raw_title.strip() if raw_title else None
    channel = channel.strip() if channel else None

    return VideoMetadata(
        raw_title=raw_title,
        display_title=title_override or clean_video_title(raw_title),
        channel=channel_override or channel,
        source_url=source_url,
    )


def youtube_ydl_base_opts(quiet: bool = False) -> Dict[str, Any]:
    return {
        "quiet": quiet,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["default"],
            }
        },
    }


def youtube_video_format(max_height: int = 1080) -> str:
    return (
        f"bestvideo[height<={max_height}][ext=mp4][vcodec^=avc1]/"
        f"bestvideo[height<={max_height}][vcodec^=avc1]/"
        f"bestvideo[height<={max_height}]/"
        f"best[height<={max_height}][ext=mp4]/"
        f"best[height<={max_height}]/"
        "best[ext=mp4]/best"
    )


def metadata_from_yt_info(info: Dict[str, Any], fallback_url: str) -> VideoMetadata:
    return build_video_metadata(
        raw_title=info.get("title"),
        channel=info.get("channel") or info.get("uploader"),
        source_url=info.get("webpage_url") or fallback_url,
    )


def probe_youtube_metadata(url: str) -> Tuple[VideoMetadata, Optional[float]]:
    if YoutubeDL is None:
        raise RuntimeError("未安装 yt-dlp，请执行：pip install -r requirements.txt")

    ydl_opts = youtube_ydl_base_opts(quiet=True)
    ydl_opts["skip_download"] = True

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return metadata_from_yt_info(info, url), info.get("duration")


def download_video(
    url: str,
    output_dir: Path,
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
    max_height: int = 1080,
) -> Tuple[Path, VideoMetadata, float]:
    """
    Descarga un video desde YouTube usando yt-dlp.

    Importante:
    Como solo necesitamos frames, bajamos video sin audio. El recorte se hace
    luego sobre el archivo local porque los range-downloads de YouTube pueden
    quedarse colgados o devolver 403 en URLs de googlevideo.
    """
    if YoutubeDL is None:
        raise RuntimeError("未安装 yt-dlp，请执行：pip install -r requirements.txt")

    output_template = str(output_dir / "video.%(ext)s")

    ydl_opts = youtube_ydl_base_opts(quiet=False)
    ydl_opts.update({
        "format": youtube_video_format(max_height=max_height),
        "outtmpl": output_template,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
    })

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    candidates = []
    for ext in ("mp4", "mkv", "webm", "mov"):
        candidates.extend(output_dir.glob(f"video*.{ext}"))

    if not candidates:
        raise FileNotFoundError("未找到已下载的视频。")

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    metadata = metadata_from_yt_info(info, url)

    return candidates[0], metadata, 0.0


def is_bilibili_url(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    host = urlparse(value).netloc.lower()
    return "bilibili.com" in host or "b23.tv" in host


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _resolve_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": BILIBILI_USER_AGENT})
    with _NO_PROXY_OPENER.open(request, timeout=20) as response:
        return response.geturl()


def extract_bilibili_id(url: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract a (bvid, aid) pair from a Bilibili URL, resolving short links."""
    host = urlparse(url).netloc.lower()
    if "b23.tv" in host:
        try:
            url = _resolve_url(url)
        except Exception:
            url = url

    match = _BILIBILI_BV_RE.search(url)
    if match:
        return match.group(0), None

    match = _BILIBILI_AV_RE.search(url)
    if match:
        return None, int(match.group(1))

    return None, None


def normalize_bilibili_url(value: str) -> str:
    """Turn a bare Bilibili id (BV…/av…) into a canonical video URL."""
    value = (value or "").strip()
    bvid, aid = extract_bilibili_id(value)
    if not bvid and not aid:
        raise ValueError("请输入有效的 Bilibili BV 号。")
    return f"https://www.bilibili.com/video/{bvid or f'av{aid}'}"


def _bilibili_api_json(url: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": BILIBILI_USER_AGENT,
            "Referer": "https://www.bilibili.com/",
        },
    )
    with _NO_PROXY_OPENER.open(request, timeout=20) as response:
        body = response.read()
    return json.loads(body.decode("utf-8"))


def probe_bilibili_metadata(url: str) -> Tuple[VideoMetadata, Optional[float]]:
    """Fetch title, uploader and duration for a Bilibili video URL."""
    bvid, aid = extract_bilibili_id(url)
    if not bvid and not aid:
        raise ValueError("无法在此 Bilibili 链接中找到视频 ID。")

    params = {"bvid": bvid} if bvid else {"aid": aid}
    api_url = "https://api.bilibili.com/x/web-interface/view?" + urllib.parse.urlencode(params)
    data = _bilibili_api_json(api_url)

    if data.get("code") != 0:
        message = data.get("message") or f"code {data.get('code')}"
        raise RuntimeError(f"Bilibili API 错误：{message}")

    info = data.get("data") or {}
    owner = info.get("owner") or {}
    duration = info.get("duration")
    duration_float = float(duration) if duration is not None else None

    canonical = f"https://www.bilibili.com/video/{bvid or f'av{aid}'}"
    metadata = build_video_metadata(
        raw_title=info.get("title"),
        channel=owner.get("name"),
        source_url=canonical,
    )
    return metadata, duration_float


def find_video_file(directory: Path) -> Optional[Path]:
    """Return the newest non-empty video file inside a directory, if any."""
    directory = Path(directory)
    candidates = []
    for ext in VIDEO_FILE_EXTENSIONS:
        candidates.extend(directory.glob(f"*{ext}"))
    candidates = [p for p in candidates if p.is_file() and p.stat().st_size > 0]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def download_bilibili_video(
    url: str,
    output_dir: Path,
    quality: Optional[int] = None,
) -> Path:
    """Download a Bilibili video with the bundled bilix.exe, returning the file path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not BILIX_EXE.exists():
        raise RuntimeError(f"未找到 bilix.exe：{BILIX_EXE}")

    command = [str(BILIX_EXE), "-s", str(output_dir)]
    if quality is not None:
        command += ["-q", str(quality)]
    command.append(url)

    completed = subprocess.run(
        command,
        capture_output=True,
        cwd=str(BILIX_EXE.parent),
    )
    stdout = decode_bytes(completed.stdout)
    stderr = decode_bytes(completed.stderr)

    if completed.returncode != 0:
        detail = (stderr or stdout).strip()
        raise RuntimeError(detail or f"bilix 退出，返回码 {completed.returncode}")

    for line in (stdout + "\n" + stderr).splitlines():
        line = line.strip()
        if line:
            print(f"[bilix] {line}")

    video_path = find_video_file(output_dir)
    if video_path is None:
        raise FileNotFoundError("bilix 已结束，但未找到视频文件。")

    return video_path


def is_mostly_dark_or_blank(image: Image.Image, std_threshold: float = 8.0) -> bool:
    """
    Filtra imágenes casi vacías o muy uniformes.
    """
    gray = ImageOps.grayscale(image)
    stat = ImageStat.Stat(gray)
    stddev = stat.stddev[0]
    return stddev < std_threshold


def create_blue_green_mask(
    image: Image.Image,
    target_rgb: Tuple[int, int, int] = (204, 216, 240),  # #ccd8f0
    target_tolerance: int = 48,
) -> np.ndarray:
    """
    Crea una máscara de píxeles que probablemente pertenezcan a la barra:
    - el color exacto aproximado #ccd8f0
    - tonos azules/celestes
    - tonos verdes

    Devuelve una máscara uint8 con valores 0 o 255.
    """
    rgb = np.array(image.convert("RGB"), dtype=np.uint8)

    # 1) Detección por cercanía al color #ccd8f0
    rgb_i32 = rgb.astype(np.int32)
    target = np.array(target_rgb, dtype=np.int32)

    diff = rgb_i32 - target
    dist_sq = np.sum(diff * diff, axis=2)
    target_mask = (dist_sq <= target_tolerance * target_tolerance).astype(np.uint8) * 255

    # 2) Detección general por HSV: azul/celeste/verde
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)

    # OpenCV HSV:
    # H va de 0 a 179.
    # Estos rangos son deliberadamente amplios porque YouTube comprime y cambia tonos.
    blue_lower = np.array([80, 20, 50])
    blue_upper = np.array([145, 255, 255])
    blue_mask = cv2.inRange(hsv, blue_lower, blue_upper)

    green_lower = np.array([35, 20, 40])
    green_upper = np.array([90, 255, 255])
    green_mask = cv2.inRange(hsv, green_lower, green_upper)

    mask = cv2.bitwise_or(target_mask, blue_mask)
    mask = cv2.bitwise_or(mask, green_mask)

    return mask


def detect_vertical_playhead_band(
    color_mask: np.ndarray,
    min_band_pixels: int = 20,
    smooth_width: int = 31,
) -> Optional[Tuple[int, float]]:
    """
    Detecta la columna x donde probablemente está la franja vertical.

    En vez de borrar todos los píxeles azules/verdes sin pensar,
    miramos en qué columna se concentra más ese color.
    """
    if color_mask.ndim != 2:
        raise ValueError("color_mask 必须是灰度图像。")

    h, w = color_mask.shape

    # Cantidad de píxeles detectados por columna
    col_scores = np.sum(color_mask > 0, axis=0).astype(np.float32)

    if smooth_width < 3:
        smooth_width = 3

    if smooth_width % 2 == 0:
        smooth_width += 1

    smooth_width = min(smooth_width, max(3, w // 2))

    kernel = np.ones(smooth_width, dtype=np.float32) / smooth_width
    smoothed = np.convolve(col_scores, kernel, mode="same")

    center_x = int(np.argmax(smoothed))
    peak_score = float(smoothed[center_x])

    if peak_score < min_band_pixels:
        return None

    return center_x, peak_score


def remove_playhead_for_comparison(
    image: Image.Image,
    band_half_width: int = 60,
    min_band_pixels: int = 20,
    target_tolerance: int = 48,
    remove_color_pixels_too: bool = True,
) -> Tuple[Image.Image, Optional[int], float]:
    """
    Devuelve una versión de la imagen con la franja vertical ignorada.

    Estrategia:
    1. Detecta píxeles azules/verdes/#ccd8f0.
    2. Busca la columna donde más se concentran.
    3. Borra una franja vertical completa alrededor.
    4. Como fallback, también puede borrar píxeles azules/verdes sueltos.

    Esto se usa para comparar duplicados, no necesariamente para guardar el PDF.
    """
    rgb = np.array(image.convert("RGB"), dtype=np.uint8)

    color_mask = create_blue_green_mask(
        image,
        target_rgb=(204, 216, 240),
        target_tolerance=target_tolerance,
    )

    # Suavizamos un poco la máscara para unir bordes de la barra/playhead
    small_kernel = np.ones((3, 3), np.uint8)
    color_mask = cv2.dilate(color_mask, small_kernel, iterations=1)

    detected = detect_vertical_playhead_band(
        color_mask,
        min_band_pixels=min_band_pixels,
        smooth_width=31,
    )

    h, w, _ = rgb.shape
    removal_mask = np.zeros((h, w), dtype=np.uint8)

    band_center = None
    peak_score = 0.0

    if detected is not None:
        band_center, peak_score = detected

        x1 = max(0, band_center - band_half_width)
        x2 = min(w, band_center + band_half_width)

        # Borramos toda la franja vertical alrededor del playhead.
        removal_mask[:, x1:x2] = 255

    if remove_color_pixels_too:
        # Fallback: también borramos restos azules/verdes fuera de la franja.
        # Útil cuando las notas que están sonando cambian de color.
        color_cleanup_kernel = np.ones((5, 5), np.uint8)
        expanded_color_mask = cv2.dilate(color_mask, color_cleanup_kernel, iterations=1)
        removal_mask = cv2.bitwise_or(removal_mask, expanded_color_mask)

    cleaned = rgb.copy()
    cleaned[removal_mask > 0] = [255, 255, 255]

    return Image.fromarray(cleaned), band_center, peak_score


@dataclass
class ComparisonFrame:
    original: Image.Image
    normalized: Image.Image
    band_center: Optional[int]
    peak_score: float
    time_sec: float


def normalize_tab_for_hash(image: Image.Image) -> Image.Image:
    """
    Normaliza la imagen para comparación:
    - escala de grises
    - binarización suave

    Esto reduce diferencias menores por compresión del video.
    """
    gray = ImageOps.grayscale(image)
    arr = np.array(gray)

    # Threshold: fondo claro queda blanco, líneas/texto quedan negro.
    arr = np.where(arr < 185, 0, 255).astype(np.uint8)

    return Image.fromarray(arr)


def binarize_luminance(
    image: Image.Image,
    threshold: Optional[int] = None,
    dark_note: bool = True,
    foreground_rgb: Tuple[int, int, int] = (24, 24, 24),
    background_rgb: Tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """
    按亮度阈值把图像压成两种颜色：谱面（线条/音符）→ foreground_rgb、背景 → background_rgb。

    dark_note=True 表示谱面是深色（比背景暗）；False 表示谱面是浅色（比背景亮）。
    threshold=None 时用 Otsu 自动计算；若 Otsu 退化（背景/线条占比极端悬殊），
    回退到固定阈值 185（与 normalize_tab_for_hash 一致）。
    """
    gray = np.array(ImageOps.grayscale(image), dtype=np.uint8)
    if threshold is None:
        otsu, _ = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        threshold = 185 if otsu <= 5 or otsu >= 250 else int(otsu)

    mask = gray < threshold if dark_note else gray >= threshold  # True = 谱面
    out = np.where(mask[..., None], foreground_rgb, background_rgb).astype(np.uint8)
    return Image.fromarray(out)


def extract_note_mask(
    image: Image.Image,
    note_rgb: Tuple[int, int, int],
    tolerance: float = 60.0,
    softness: float = 20.0,
) -> Image.Image:
    """按音符颜色把图像转成「音符黑、其它白」的灰度图（平滑过渡）。

    逐像素计算与 note_rgb 的 RGB 欧氏距离，再用 smoothstep 在容差附近做平滑
    过渡：距离小于 (tolerance - softness) 判为音符(黑 0)，大于
    (tolerance + softness) 判为背景(白 255)，中间平滑过渡，避免锯齿硬边。
    """
    rgb = np.array(image.convert("RGB"), dtype=np.float32)
    note = np.asarray(note_rgb, dtype=np.float32)
    dist = np.sqrt(np.sum((rgb - note) ** 2, axis=-1))

    softness = max(1.0, float(softness))
    edge0 = float(tolerance) - softness
    edge1 = float(tolerance) + softness
    t = np.clip((dist - edge0) / (edge1 - edge0), 0.0, 1.0)
    smooth = t * t * (3.0 - 2.0 * t)  # smoothstep：0=音符，1=背景
    gray = (smooth * 255.0).astype(np.uint8)
    return Image.fromarray(gray, mode="L")


def recolor_gray(
    gray: Image.Image,
    text_rgb: Tuple[int, int, int],
    bg_rgb: Tuple[int, int, int],
) -> Image.Image:
    """把「音符黑、背景白」的灰度图染成 text_rgb / bg_rgb，边缘平滑过渡。"""
    g = np.array(gray.convert("L"), dtype=np.float32) / 255.0  # 0=音符，1=背景
    text = np.asarray(text_rgb, dtype=np.float32)
    bg = np.asarray(bg_rgb, dtype=np.float32)
    out = text[None, None, :] * (1.0 - g[..., None]) + bg[None, None, :] * g[..., None]
    return Image.fromarray(np.clip(out, 0.0, 255.0).astype(np.uint8))


def preprocess_for_detection(
    image: Image.Image,
    note_rgb: Optional[Tuple[int, int, int]] = None,
    tolerance: float = 60.0,
    softness: float = 20.0,
) -> Image.Image:
    """自动检测前的预处理。

    指定 note_rgb 时按音符颜色二值化（音符黑、其它白，去掉彩色背景与高亮）；
    否则回退到 neutralize_highlight（只中和彩色高亮）。
    """
    if note_rgb is not None:
        return extract_note_mask(image, note_rgb, tolerance, softness).convert("RGB")
    return neutralize_highlight(image)


def detect_playhead_in_image(
    image: Image.Image,
    min_band_pixels: int = 20,
    target_tolerance: int = 48,
) -> Tuple[Optional[int], float]:
    """
    Detecta la columna central del playhead sin borrar píxeles de color sueltos.
    """
    color_mask = create_blue_green_mask(
        image,
        target_rgb=(204, 216, 240),
        target_tolerance=target_tolerance,
    )

    small_kernel = np.ones((3, 3), np.uint8)
    color_mask = cv2.dilate(color_mask, small_kernel, iterations=1)

    detected = detect_vertical_playhead_band(
        color_mask,
        min_band_pixels=min_band_pixels,
        smooth_width=31,
    )

    if detected is None:
        return None, 0.0

    return detected


def build_playhead_mask(
    shape: Tuple[int, int],
    centers: List[Optional[int]],
    band_half_width: int,
) -> np.ndarray:
    """
    Construye una máscara única para ignorar las bandas de ambos frames.
    """
    h, w = shape
    mask = np.zeros((h, w), dtype=bool)

    for center in centers:
        if center is None:
            continue

        x1 = max(0, center - band_half_width)
        x2 = min(w, center + band_half_width)
        mask[:, x1:x2] = True

    return mask


def apply_ignore_mask(image: Image.Image, mask: np.ndarray) -> Image.Image:
    arr = np.array(image.convert("L"), dtype=np.uint8)
    arr[mask] = 255
    return Image.fromarray(arr)


def prepare_comparison_frame(
    original_img: Image.Image,
    time_sec: float,
    min_band_pixels: int,
    target_tolerance: int,
) -> ComparisonFrame:
    band_center, peak_score = detect_playhead_in_image(
        original_img,
        min_band_pixels=min_band_pixels,
        target_tolerance=target_tolerance,
    )
    normalized = normalize_tab_for_hash(original_img)

    return ComparisonFrame(
        original=original_img,
        normalized=normalized,
        band_center=band_center,
        peak_score=peak_score,
        time_sec=time_sec,
    )


def masked_diff_ratio(
    previous: ComparisonFrame,
    current: ComparisonFrame,
    band_half_width: int,
) -> Tuple[float, np.ndarray, Image.Image, Image.Image, Image.Image]:
    """
    Compara dos frames usando la misma máscara de playhead para ambos.
    """
    prev_arr = np.array(previous.normalized.convert("L"), dtype=np.uint8)
    curr_arr = np.array(current.normalized.convert("L"), dtype=np.uint8)

    if prev_arr.shape != curr_arr.shape:
        raise ValueError("比较图像必须尺寸相同。")

    ignore_mask = build_playhead_mask(
        prev_arr.shape,
        [previous.band_center, current.band_center],
        band_half_width=band_half_width,
    )
    compare_mask = ~ignore_mask

    if not np.any(compare_mask):
        return 1.0, ignore_mask, previous.normalized, current.normalized, current.normalized

    changed = (prev_arr != curr_arr) & compare_mask
    diff_ratio = float(np.count_nonzero(changed) / np.count_nonzero(compare_mask))

    prev_masked = prev_arr.copy()
    curr_masked = curr_arr.copy()
    prev_masked[ignore_mask] = 255
    curr_masked[ignore_mask] = 255

    diff_vis = np.full(curr_arr.shape, 255, dtype=np.uint8)
    diff_vis[changed] = 0

    return (
        diff_ratio,
        ignore_mask,
        Image.fromarray(prev_masked),
        Image.fromarray(curr_masked),
        Image.fromarray(diff_vis),
    )


def save_debug_images(
    comparison_dir: Path,
    index: int,
    current: ComparisonFrame,
    decision: str,
    masked_current: Optional[Image.Image] = None,
    diff_image: Optional[Image.Image] = None,
):
    safe_decision = decision.replace(" ", "_")
    prefix = f"{index:04d}_t{int(current.time_sec):05d}_{safe_decision}"

    current.normalized.convert("RGB").save(comparison_dir / f"{prefix}_normalized.png")

    if masked_current is not None:
        masked_current.convert("RGB").save(comparison_dir / f"{prefix}_masked.png")

    if diff_image is not None:
        diff_image.convert("RGB").save(comparison_dir / f"{prefix}_diff.png")


def mask_playhead_in_original(
    image: Image.Image,
    band_center: Optional[int],
    band_half_width: int,
) -> Image.Image:
    arr = np.array(image.convert("RGB"), dtype=np.uint8)
    h, w, _ = arr.shape
    mask = build_playhead_mask((h, w), [band_center], band_half_width)
    arr[mask] = [255, 255, 255]
    return Image.fromarray(arr)


def validate_crop_ratios(crop_y_start_ratio: float, crop_y_end_ratio: float) -> None:
    if not 0.0 <= crop_y_start_ratio < crop_y_end_ratio <= 1.0:
        raise ValueError(
            "裁剪范围必须满足 0 <= crop_y_start < crop_y_end <= 1。"
        )
    if crop_y_end_ratio - crop_y_start_ratio < 0.05:
        raise ValueError("垂直裁剪至少需要覆盖视频的 5%。")


def validate_crop_x_ratios(crop_x_start_ratio: float, crop_x_end_ratio: float) -> None:
    if not 0.0 <= crop_x_start_ratio < crop_x_end_ratio <= 1.0:
        raise ValueError(
            "裁剪范围必须满足 0 <= crop_x_start < crop_x_end <= 1。"
        )
    if crop_x_end_ratio - crop_x_start_ratio < 0.01:
        raise ValueError("水平裁剪至少需要覆盖视频的 1%。")


def crop_frame_rgb(
    frame_rgb: np.ndarray,
    crop_y_start_ratio: float,
    crop_y_end_ratio: float,
    crop_x_start_ratio: float = 0.0,
    crop_x_end_ratio: float = 1.0,
) -> np.ndarray:
    validate_crop_ratios(crop_y_start_ratio, crop_y_end_ratio)
    validate_crop_x_ratios(crop_x_start_ratio, crop_x_end_ratio)
    h, w, _ = frame_rgb.shape
    y1 = int(round(h * crop_y_start_ratio))
    y2 = int(round(h * crop_y_end_ratio))
    y1 = max(0, min(h - 1, y1))
    y2 = max(y1 + 1, min(h, y2))
    x1 = int(round(w * crop_x_start_ratio))
    x2 = int(round(w * crop_x_end_ratio))
    x1 = max(0, min(w - 1, x1))
    x2 = max(x1 + 1, min(w, x2))
    return frame_rgb[y1:y2, x1:x2, :]


def save_video_frame(
    video_path: Path,
    output_path: Path,
    time_sec: float = 0.0,
    max_width: int = 1280,
) -> Path:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{video_path}")

    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, time_sec) * 1000)
    ok, frame = cap.read()
    cap.release()

    if not ok:
        raise RuntimeError(f"无法在 t={time_sec:.2f}s 读取帧")

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(frame_rgb)

    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, int(image.height * ratio)), RESAMPLE)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_path, quality=90)
    return output_path


def get_video_duration(video_path: Path) -> float:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return frame_count / fps if fps > 0 else 0.0


def extract_unique_crops(
    video_path: Path,
    crops_dir: Path,
    comparison_dir: Optional[Path] = None,
    sample_every_sec: float = 2.0,
    crop_top_ratio: Optional[float] = 1.0,
    crop_y_start_ratio: Optional[float] = None,
    crop_y_end_ratio: Optional[float] = None,
    crop_x_start_ratio: float = 0.0,
    crop_x_end_ratio: float = 1.0,
    hash_threshold: int = 16,
    hash_size: int = 12,
    diff_threshold: float = 0.010,
    compare_window: int = 1,
    debug_diffs: bool = False,
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
    save_cleaned: bool = False,
    band_half_width: int = 90,
    min_band_pixels: int = 20,
    target_tolerance: int = 48,
    progress_callback: Optional[ProgressCallback] = None,
) -> ExtractionStats:
    """
    Extrae capturas cada X segundos, recorta la parte superior,
    elimina duplicados ignorando la franja vertical azul/verde móvil,
    y guarda las imágenes finales.
    """
    if crop_y_start_ratio is None:
        crop_y_start_ratio = 0.0
    if crop_y_end_ratio is None:
        crop_y_end_ratio = crop_top_ratio if crop_top_ratio is not None else 1.0
    validate_crop_ratios(crop_y_start_ratio, crop_y_end_ratio)
    validate_crop_x_ratios(crop_x_start_ratio, crop_x_end_ratio)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0

    if end_sec is None or end_sec > duration:
        end_sec = duration

    crops_dir.mkdir(parents=True, exist_ok=True)

    if comparison_dir is not None:
        comparison_dir.mkdir(parents=True, exist_ok=True)

    current_time = start_sec
    stats = ExtractionStats(
        duration=duration,
        start_sec=start_sec,
        end_sec=end_sec,
    )
    recent_kept: List[ComparisonFrame] = []
    saved_times: Dict[str, float] = {}
    compare_window = max(1, compare_window)

    print(f"检测到时长：{duration:.2f}s")
    print(f"处理范围：{start_sec:.2f}s 到 {end_sec:.2f}s")
    print(f"每隔 {sample_every_sec:.2f}s 截图")
    print(
        f"diff_threshold={diff_threshold:.4f}, "
        f"compare_window={compare_window}, band_half_width={band_half_width}"
    )
    print(
        f"crop_y_start={crop_y_start_ratio:.3f}, "
        f"crop_y_end={crop_y_end_ratio:.3f}"
    )
    if progress_callback is not None:
        progress_callback("started", stats)

    while current_time <= end_sec:
        cap.set(cv2.CAP_PROP_POS_MSEC, current_time * 1000)
        ok, frame = cap.read()
        if not ok:
            break

        stats.frames_checked += 1

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        cropped = crop_frame_rgb(
            frame_rgb,
            crop_y_start_ratio,
            crop_y_end_ratio,
            crop_x_start_ratio,
            crop_x_end_ratio,
        )

        original_img = Image.fromarray(cropped)

        if is_mostly_dark_or_blank(original_img):
            current_time += sample_every_sec
            continue

        current_comparison = prepare_comparison_frame(
            original_img,
            time_sec=current_time,
            min_band_pixels=min_band_pixels,
            target_tolerance=target_tolerance,
        )

        best_diff = None
        best_masked_current = None
        best_diff_image = None
        is_duplicate = False

        for previous_comparison in recent_kept[-compare_window:]:
            (
                diff_ratio,
                _ignore_mask,
                _masked_previous,
                masked_current,
                diff_image,
            ) = masked_diff_ratio(
                previous_comparison,
                current_comparison,
                band_half_width=band_half_width,
            )

            if best_diff is None or diff_ratio < best_diff:
                best_diff = diff_ratio
                best_masked_current = masked_current
                best_diff_image = diff_image

            if diff_ratio <= diff_threshold:
                is_duplicate = True
                break

        if is_duplicate:
            stats.duplicates_skipped += 1
            if comparison_dir is not None and debug_diffs:
                save_debug_images(
                    comparison_dir,
                    stats.frames_checked,
                    current_comparison,
                    decision=f"duplicate_diff_{best_diff:.4f}",
                    masked_current=best_masked_current,
                    diff_image=best_diff_image,
                )
            if progress_callback is not None:
                progress_callback("frame", stats)
            current_time += sample_every_sec
            continue

        output_path = crops_dir / (
            f"crop_{stats.captures_kept:04d}_t{int(current_time):05d}.png"
        )

        if save_cleaned:
            save_image = mask_playhead_in_original(
                original_img,
                current_comparison.band_center,
                band_half_width=band_half_width,
            )
        else:
            save_image = original_img

        save_image.convert("RGB").save(output_path)
        saved_times[output_path.name] = float(current_time)

        if comparison_dir is not None:
            save_debug_images(
                comparison_dir,
                stats.frames_checked,
                current_comparison,
                decision=(
                    f"kept_diff_{best_diff:.4f}"
                    if best_diff is not None
                    else "kept_first"
                ),
                masked_current=best_masked_current,
                diff_image=best_diff_image if debug_diffs else None,
            )

        stats.captures_kept += 1
        recent_kept.append(current_comparison)

        band_info = "sin banda detectada"
        if current_comparison.band_center is not None:
            band_info = (
                f"band x={current_comparison.band_center}, "
                f"peak={current_comparison.peak_score:.1f}"
            )

        diff_info = "diff=初始"
        if best_diff is not None:
            diff_info = f"diff={best_diff:.4f}"

        print(
            f"[{stats.captures_kept:03d}] 已保存 t={current_time:.2f}s | "
            f"{diff_info} | {band_info}"
        )
        if progress_callback is not None:
            progress_callback("frame", stats)

        current_time += sample_every_sec

    cap.release()

    print(f"已检查帧数：{stats.frames_checked}")
    print(f"跳过重复：{stats.duplicates_skipped}")
    print(f"最终截图：{stats.captures_kept}")
    if progress_callback is not None:
        progress_callback("finished", stats)

    times_path = crops_dir / "times.json"
    try:
        with times_path.open("w", encoding="utf-8") as fh:
            json.dump(saved_times, fh, ensure_ascii=False)
    except OSError:
        pass

    return stats


_FONT_FILES = {
    "msyh": ["msyh.ttc", "msyh.ttf"],
    "simsun": ["simsun.ttc", "simsun.ttf"],
    "simhei": ["simhei.ttf"],
    "simkai": ["simkai.ttf"],
    "arial": ["arial.ttf"],
    "segoe": ["segoeui.ttf"],
    "calibri": ["calibri.ttf"],
    "verdana": ["verdana.ttf"],
}

# 兜底候选：优先中文字体，保证中文标题/作者正常渲染。
_DEFAULT_FONT_FILES = [
    "msyh.ttc",
    "msyh.ttf",
    "simhei.ttf",
    "simsun.ttc",
    "arial.ttf",
    "segoeui.ttf",
    "calibri.ttf",
    "verdana.ttf",
    "DejaVuSans.ttf",
]


def load_font(size: int, family: Optional[str] = None):
    windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    names = list(_FONT_FILES.get(family or "", [])) + _DEFAULT_FONT_FILES

    for name in names:
        for font_path in (
            windows_fonts / name,
            Path("/System/Library/Fonts/Supplemental") / name,
            Path("/Library/Fonts") / name,
            Path("/usr/share/fonts/truetype") / name,
            name,
        ):
            try:
                return ImageFont.truetype(font_path, size)
            except OSError:
                continue

    return ImageFont.load_default()


def hex_to_rgb(value: str, default: Tuple[int, int, int] = (24, 24, 24)) -> Tuple[int, int, int]:
    value = (value or "").strip().lstrip("#")
    if len(value) == 6:
        try:
            return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
        except ValueError:
            pass
    return default


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def header_line_height(font) -> int:
    """标题/作者行高 = 字号 × 固定比例，与前端 CSS line-height 保持一致。"""
    return max(1, int(round(font.size * HEADER_LINE_HEIGHT_RATIO)))


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: int,
) -> List[str]:
    # 按字符换行（中英文混排时逐字累加，超宽即断行），与前端 overflow-wrap:anywhere 一致。
    if not text:
        return []
    lines = []
    current = ""
    for ch in text:
        candidate = current + ch
        candidate_w, _ = text_size(draw, candidate, font)
        if current and candidate_w > max_width:
            lines.append(current.rstrip())
            current = ch.lstrip()
        else:
            current = candidate
    if current.strip():
        lines.append(current.rstrip())
    return lines


def draw_first_page_header(
    page: Image.Image,
    title_lines: Optional[List[str]],
    source_url: Optional[str],
    page_width: int,
    page_height: int,
    margin: int,
    text_color: str = "181818",
    title_spacing: Optional[int] = None,
) -> int:
    """在第一页顶部绘制多行标题，返回图片列表的起始 Y 坐标。

    title_lines[0] 按标题字号，其余行按作者字号；source_url 以小字右对齐。
    标题部分由 (title_spacing + 文字 + title_spacing) 组成，而非固定高度占比。
    """
    lines = [ln.strip() for ln in (title_lines or []) if ln.strip()]
    url = (source_url or "").strip()
    if not lines and not url:
        return margin

    title_size = max(16, int(HEADER_TITLE_SIZE))
    draw = ImageDraw.Draw(page)
    title_font = load_font(title_size, HEADER_FONT_FAMILY)
    author_font = load_font(max(14, int(round(title_size * 0.4375))), HEADER_FONT_FAMILY)
    source_font = load_font(max(12, int(round(title_size * 0.25))), HEADER_FONT_FAMILY)
    color = hex_to_rgb(text_color)
    max_text_width = page_width - 2 * margin

    spacing = title_spacing if title_spacing is not None else int(page_height * HEADER_HEIGHT_RATIO)

    # 逐行：第一行标题字号，其余作者字号；超宽自动换行。
    entries = []  # (text, font)
    for i, raw in enumerate(lines):
        font = title_font if i == 0 else author_font
        for wl in wrap_text(draw, raw, font, max_text_width) or [raw]:
            entries.append((wl, font))
    url_entries = [
        (wl, source_font)
        for wl in (wrap_text(draw, url, source_font, max_text_width)[:2] if url else [])
    ]

    # 文字块总高：标题/作者行间 8px，链接块前 12px、行间 4px。
    text_h = 0
    for idx, (txt, font) in enumerate(entries):
        text_h += header_line_height(font)
        if idx < len(entries) - 1:
            text_h += 8
    if url_entries:
        text_h += 12
        for idx, (txt, font) in enumerate(url_entries):
            text_h += header_line_height(font)
            if idx < len(url_entries) - 1:
                text_h += 4

    header_height = spacing + text_h + spacing
    y = margin + spacing

    for txt, font in entries:
        w_, _ = text_size(draw, txt, font)
        draw.text(((page_width - w_) / 2, y), txt, fill=color, font=font)
        y += header_line_height(font) + 8

    if url_entries:
        y += 4
        for txt, font in url_entries:
            w_, _ = text_size(draw, txt, font)
            draw.text((page_width - margin - w_, y), txt, fill=color, font=font)
            y += header_line_height(font) + 4

    return header_height


def crop_image_horizontal(img: Image.Image, left: float, right: float) -> Image.Image:
    w, h = img.size
    x0 = int(round(w * left))
    x1 = int(round(w * right))
    return img.crop((x0, 0, x1, h))


def crop_image_horizontal_centered(
    img: Image.Image, left: float, right: float, bg_color: str = "white"
) -> Image.Image:
    """水平裁剪后保持原图尺寸，居中显示，两侧用背景色填充。

    与 crop_image_horizontal 直接裁成窄图不同，这里把保留区域贴到一张
    与原图等宽的画布上居中，这样在 PDF 里不会被横向拉伸放大。
    """
    w, h = img.size
    x0 = max(0, min(w, int(round(w * left))))
    x1 = max(x0, min(w, int(round(w * right))))
    if x0 <= 0 and x1 >= w:
        return img

    cropped = img.crop((x0, 0, x1, h))
    canvas = Image.new("RGB", (w, h), bg_color)
    canvas.paste(cropped, ((w - cropped.width) // 2, 0))
    return canvas


# =====================================================================
# 鲁棒的小节线（竖线）检测 —— 移植自 score_capture_ref 的 image_process.py
# =====================================================================

@dataclass
class _StaffLine:
    """简化的线段表示。

    start 为法向起始坐标（横线=行号 y，竖线=列号 x），thickness 为线段粗细。
    direction："H" 表示横线，"V" 表示竖线。
    """

    start: int
    thickness: int
    direction: str

    @property
    def end_index(self) -> int:
        return self.start + self.thickness - 1


def detect_horizontal_lines(
    gray: np.ndarray,
    coefficient: float = 0.7,
    invert: bool = False,
    r_pixel_threshold: float = 255.0,
    r_thickness_threshold: int = 10,
) -> List[_StaffLine]:
    """识别白底图中的所有水平线（黑线），返回行线段列表。"""
    if gray.ndim != 2:
        gray = cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)
    if float(np.average(gray)) < 128:
        gray = 255 - gray

    img_adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 5, 7
    )
    average_row = np.average(img_adaptive, axis=1)
    if invert:
        hit = average_row >= r_pixel_threshold
    else:
        hit = average_row < 255 * coefficient

    lines: List[_StaffLine] = []
    current_y = 1  # adaptiveThreshold 结果比原图短约 2 像素，等效从第 1 像素开始
    point_y = 0
    for i in range(len(average_row)):
        if bool(hit[i]) and not point_y:
            point_y = current_y
        elif not bool(hit[i]) and point_y:
            thickness = current_y - point_y
            if not invert or thickness >= r_thickness_threshold:
                lines.append(
                    _StaffLine(start=point_y, thickness=thickness, direction="H")
                )
            point_y = 0
        current_y += 1
    return lines


def get_score_lines(horizontal_lines: List[_StaffLine]) -> List[_StaffLine]:
    """从水平线检测结果中筛选出谱表（staff）部分的横线。"""
    if len(horizontal_lines) < 3:
        return []
    ys = np.asarray([line.start for line in horizontal_lines])
    distance = ys[1:] - ys[:-1]
    index = (
        np.flatnonzero(
            (distance - np.average(distance)) / (np.std(distance) + 0.1) > 2
        )
        + 1
    )
    index = np.sort(np.append(index, [0, len(horizontal_lines)]))
    index = [(int(index[i]), int(index[i + 1])) for i in range(np.shape(index)[0] - 1)]
    index = [i for i in index if (i[1] - i[0]) > 3]
    try:
        result = [horizontal_lines[i:j] for i, j in index][-1]
    except IndexError:
        return []
    return result


def _image_preprocess_for_vertical_line_detect(gray: np.ndarray) -> np.ndarray:
    """将灰度图预处理为「黑底白线」的二值图，用于竖线检测。"""
    if gray.ndim != 2:
        img = cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)
    else:
        img = gray
    if float(np.average(img)) > 128:
        img = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 5, 7
        )
        img = 255 - img
    else:
        img = 255 - img
        img = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 5, 7
        )
        img = 255 - img
    return img


def _detect_bar_lines(
    img: np.ndarray,
    top_line_y: int,
    bottom_line_y: int,
    edge_top: int,
    edge_bottom: int,
    coefficient: float,
) -> List[np.ndarray]:
    """img 为「黑底白线」二值图，返回每条小节线对应的连续列索引组。"""
    sum_columns = np.sum(img[top_line_y:bottom_line_y], axis=0).astype(np.float64)
    sum_columns_ex = np.sum(img[edge_top:edge_bottom], axis=0).astype(np.float64)

    columns_midpoint = (np.max(sum_columns) + np.min(sum_columns)) // 2
    sum_columns[np.where(sum_columns < columns_midpoint)[0]] = 0
    columns_ex_midpoint = (np.max(sum_columns_ex) + np.min(sum_columns_ex)) // 2
    sum_columns_ex[np.where(sum_columns_ex < columns_ex_midpoint)[0]] = 0

    if sum_columns.shape[0] == 0 or sum_columns_ex.shape[0] == 0:
        return []
    bar_lines = np.where(
        (
            sum_columns / sum_columns.shape[0]
            - sum_columns_ex / sum_columns_ex.shape[0] * coefficient
        )
        > 0
    )[0]
    if bar_lines.size == 0:
        return []

    # 去除上下不对称（方差过大）的列，过滤音符符干等非小节线。
    std_y = np.std(img[top_line_y:bottom_line_y, bar_lines], axis=0)
    bar_lines = np.delete(bar_lines, np.where(std_y > 100)[0])
    if bar_lines.size == 0:
        return []

    # 去除前景（白色）占比过少的列。
    white_ratio_y = (
        np.sum(img[top_line_y:bottom_line_y, bar_lines], axis=0)
        / 255
        / (bottom_line_y - top_line_y)
    )
    bar_lines = np.delete(bar_lines, np.where(white_ratio_y < 0.93)[0])
    if bar_lines.size == 0:
        return []

    # 将连续的列合并成组，每组即一根小节线。
    split_index = np.where((bar_lines[1:] - bar_lines[:-1]) != 1)[0] + 1
    split_index = np.sort(np.append(split_index, [0, len(bar_lines)]))[1:-1]
    return list(np.split(bar_lines, split_index))


def detect_vertical_lines(
    gray: np.ndarray,
    horizontal_lines: Optional[List[_StaffLine]] = None,
    coefficient: float = 0.8,
) -> List[_StaffLine]:
    """识别谱表区域内的竖直线（小节线），返回竖线段列表。"""
    img = _image_preprocess_for_vertical_line_detect(gray)
    if horizontal_lines is None:
        horizontal_lines = detect_horizontal_lines(img)
    if not horizontal_lines:
        return []
    horizontal_lines = get_score_lines(horizontal_lines)
    if not horizontal_lines:
        return []

    top_line_y = horizontal_lines[0].start
    bottom_line_y = horizontal_lines[-1].end_index
    expand = int((bottom_line_y - top_line_y) / 5)
    edge_top = top_line_y - expand if top_line_y - expand > 0 else 0
    edge_bottom = bottom_line_y + expand
    if edge_bottom >= (h := img.shape[0]):
        edge_bottom = h - 1

    kernel_h = int((bottom_line_y - top_line_y) / 15)
    kernel_h = kernel_h if kernel_h >= 1 else 1
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, kernel_h))
    img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, vertical_kernel)

    groups = _detect_bar_lines(
        img, top_line_y, bottom_line_y, edge_top, edge_bottom, coefficient
    )
    result: List[_StaffLine] = []
    for group in groups:
        if group.size == 0:
            continue
        result.append(
            _StaffLine(start=int(group[0]), thickness=int(group.size), direction="V")
        )
    return result


def detect_barlines_robust(
    image: Image.Image,
    coefficient_horizontal: float = 0.7,
    coefficient_vertical: float = 0.8,
    min_margin: int = 3,
) -> List[int]:
    """鲁棒的小节线（竖线）检测，返回升序的 x 像素坐标。

    与简单的「逐列墨迹占比」方法不同，这里先定位谱表横线区域，再在该区域内做
    形态学闭运算连接断点，并利用上下对称性/白色占比过滤音符符干，最后合并
    反复记号（“||”“:|:”）等过近的双竖线。
    """
    gray = np.array(ImageOps.grayscale(image), dtype=np.uint8)
    horizontal_lines = detect_horizontal_lines(gray, coefficient_horizontal)
    vertical_lines = detect_vertical_lines(gray, horizontal_lines, coefficient_vertical)
    if not vertical_lines:
        return []

    centers = np.asarray(
        [line.start + (line.thickness - 1) / 2.0 for line in vertical_lines]
    )
    if centers.size > 1:
        distance = centers[1:] - centers[:-1]
        avg = float(np.average(distance))
        if avg > 0:
            # 合并过近的相邻竖线（反复记号的双竖线）。
            merged: List[float] = []
            i = 0
            while i < centers.size:
                j = i
                while j + 1 < centers.size and centers[j + 1] - centers[j] < avg / 5.0:
                    j += 1
                merged.append(float(np.mean(centers[i : j + 1])))
                i = j + 1
            centers = np.asarray(merged)

    w = image.width
    return [
        int(round(c))
        for c in centers
        if min_margin <= int(round(c)) <= w - min_margin
    ]


def _detect_measure_barlines_heuristic(
    image: Image.Image,
    ink_threshold: int = 150,
    staff_row_ratio: float = 0.30,
    span_ratio: float = 0.50,
    merge_gap: int = 4,
    min_margin: int = 3,
) -> List[int]:
    """旧版的逐列墨迹占比启发式，作为鲁棒检测无结果时的回退。"""
    gray = np.array(ImageOps.grayscale(image), dtype=np.uint8)
    if float(gray.mean()) < 128:
        gray = 255 - gray
    h, w = gray.shape
    ink = gray < ink_threshold

    row_ratio = ink.sum(axis=1).astype(np.float64) / max(1, w)
    staff_rows = np.where(row_ratio >= staff_row_ratio)[0]
    if staff_rows.size < 6:
        top, bottom = 0, h - 1
    else:
        top, bottom = int(staff_rows.min()), int(staff_rows.max())

    band_h = bottom - top + 1
    if band_h < 6:
        return []

    col_ink = ink[top:bottom + 1, :].sum(axis=0).astype(np.float64)
    col_ratio = col_ink / band_h
    candidates = np.where(col_ratio >= span_ratio)[0]

    if candidates.size == 0:
        return []

    groups: List[List[int]] = []
    cur = [int(candidates[0])]
    for x in candidates[1:]:
        if int(x) - cur[-1] <= merge_gap:
            cur.append(int(x))
        else:
            groups.append(cur)
            cur = [int(x)]
    groups.append(cur)

    centers = [int(round(sum(g) / len(g))) for g in groups]
    return [x for x in centers if min_margin <= x <= w - min_margin]


def detect_measure_barlines(
    image: Image.Image,
    ink_threshold: int = 150,
    staff_row_ratio: float = 0.30,
    span_ratio: float = 0.50,
    merge_gap: int = 4,
    min_margin: int = 3,
    coefficient_horizontal: float = 0.7,
    coefficient_vertical: float = 0.8,
) -> List[int]:
    """检测谱面（tab）里的小节线（竖线），返回升序的 x 像素坐标。

    优先使用鲁棒检测（先定位谱表横线，再做形态学竖线检测）；若未检出，
    回退到旧的逐列墨迹占比启发式。
    """
    bars = detect_barlines_robust(
        image,
        coefficient_horizontal=coefficient_horizontal,
        coefficient_vertical=coefficient_vertical,
        min_margin=min_margin,
    )
    if bars:
        return bars
    return _detect_measure_barlines_heuristic(
        image,
        ink_threshold=ink_threshold,
        staff_row_ratio=staff_row_ratio,
        span_ratio=span_ratio,
        merge_gap=merge_gap,
        min_margin=min_margin,
    )


def split_into_measures(image: Image.Image, bars: List[int]) -> List[Image.Image]:
    """把一张图按小节线（含图片左右边界）切成若干竖条。"""
    w, h = image.size
    cuts = [0] + sorted(set(int(x) for x in bars if 0 <= x <= w)) + [w]
    strips: List[Image.Image] = []
    for i in range(len(cuts) - 1):
        x0, x1 = cuts[i], cuts[i + 1]
        if x1 - x0 >= 1:
            strips.append(image.crop((x0, 0, x1, h)))
    return strips


def _best_stitch_offset(a: np.ndarray, b: np.ndarray) -> float:
    """返回 a、b（灰度图）之间最佳水平重叠偏移（相对 a 宽的 0..1 比例）。

    即 a 的右 d 列与 b 的左 d 列内容重合时，MSE 最小的 d。
    """
    h = min(a.shape[0], b.shape[0])
    a = a[:h, :]
    b = b[:h, :]
    wa, wb = a.shape[1], b.shape[1]
    max_d = min(wa, wb) - 1
    if max_d < 8:
        return 0.0

    d_min = max(1, int(max_d * 0.15))
    d_max = int(max_d * 0.85)
    step = max(1, (d_max - d_min) // 160)

    best_d, best_err = 0, float("inf")
    for d in range(d_min, d_max + 1, step):
        err = float(np.mean((a[:, -d:].astype(np.float64) - b[:, :d].astype(np.float64)) ** 2))
        if err < best_err:
            best_err, best_d = err, d
    # 局部细化
    lo = max(d_min, best_d - step)
    hi = min(d_max, best_d + step)
    for d in range(lo, hi + 1):
        err = float(np.mean((a[:, -d:].astype(np.float64) - b[:, :d].astype(np.float64)) ** 2))
        if err < best_err:
            best_err, best_d = err, d
    return best_d / wa


def _to_gray_resized(img: Image.Image, max_width: int) -> Tuple[np.ndarray, float]:
    """灰度化并按最大宽度缩放，返回 (灰度数组, 缩放比例)。"""
    g = np.array(ImageOps.grayscale(img), dtype=np.uint8)
    ratio = 1.0
    if g.shape[1] > max_width:
        ratio = max_width / g.shape[1]
        g = cv2.resize(
            g,
            (max_width, max(1, int(round(g.shape[0] * ratio)))),
            interpolation=cv2.INTER_AREA,
        )
    return g, ratio


def neutralize_highlight(
    image: Image.Image,
    saturation_threshold: int = 30,
    dark_ink_v: int = 140,
    light_ink_v: int = 140,
) -> Image.Image:
    """中和「当前小节」的彩色高亮背景，保留黑白谱线。

    谱面是黑/白（可能被高亮轻微染色），高亮背景是彩色且较饱和。思路：
      1) 饱和度通道 + 现有蓝/绿目标色共同定位「彩色」像素；
      2) 按整体明暗判断谱面极性，用亮度把「谱线（墨迹）」保护起来，避免
         高亮把黑/白谱线也轻微染色后被误擦；
      3) 用非彩色、非谱线的像素估算普通背景色，把高亮背景填回背景色，
         使高亮两侧的伪竖边消失、高亮区内的谱线保留。
    """
    rgb = np.array(image.convert("RGB"), dtype=np.uint8)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]

    # 彩色掩码：较饱和像素 + 现有蓝/绿/目标色（覆盖较淡的蓝绿高亮）
    color_mask = (sat > saturation_threshold).astype(np.uint8) * 255
    color_mask = cv2.bitwise_or(color_mask, create_blue_green_mask(image))
    # 轻微膨胀，把高亮的柔和边缘一并覆盖
    color_mask = cv2.dilate(color_mask, np.ones((5, 5), np.uint8), iterations=1)

    # 谱线（墨迹）保护：按整体明暗决定谱线是暗色还是亮色
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if float(gray.mean()) >= 128:
        ink = val < dark_ink_v  # 浅底深字：暗像素是谱线
    else:
        ink = val > light_ink_v  # 深底浅字：亮像素是谱线

    colored = color_mask > 0
    to_fill = colored & ~ink
    if not np.any(to_fill):
        return image

    # 普通背景 = 非彩色、非谱线；用它估算背景色，再把高亮填回背景色
    normal = ~colored & ~ink
    if int(normal.sum()) < 100:
        bg = np.median(rgb.reshape(-1, 3), axis=0)
    else:
        bg = np.median(rgb[normal], axis=0)

    out = rgb.copy()
    out[to_fill] = bg.astype(np.uint8)
    return Image.fromarray(out)


def _snap_to_barline(value: float, bars: List[int], width: int) -> float:
    """把归一化位置 value 吸附到最近的小节线（归一化），无小节线时原样返回。"""
    if not bars:
        return value
    norm = [b / width for b in bars]
    return min(norm, key=lambda x: abs(x - value))


def _best_barline_seam(
    img_a: Image.Image,
    img_b: Image.Image,
    bars_a: List[int],
    bars_b: List[int],
    max_width: int = 600,
) -> Optional[Tuple[float, float]]:
    """在相邻两张截图中寻找同一根小节线作为拼接缝。

    返回 (right_of_a, left_of_b)，均为归一化（0..1）的小节线位置：
    a 的右裁剪边界 = right_of_a，b 的左裁剪边界 = left_of_b。
    找不到可靠的小节线对时返回 None。

    对每个 (a 中的小节线 p, b 中的小节线 q) 组合，计算其对应的重叠宽度
    d = (宽_a - p) + q，并比较 a 右 d 列与 b 左 d 列的内容，MSE 最小者为
    最佳拼接缝——这就把拼接位置锁定在小节线上。
    """
    wa, wb = img_a.width, img_b.width
    ga, ra = _to_gray_resized(img_a, max_width)
    gb, rb = _to_gray_resized(img_b, max_width)
    h = min(ga.shape[0], gb.shape[0])
    ga = ga[:h]
    gb = gb[:h]
    dwa, dwb = ga.shape[1], gb.shape[1]

    best: Optional[Tuple[float, float, float]] = None  # (err, p_norm, q_norm)
    for x_p in bars_a:  # 原图像素坐标
        p = int(round(x_p * ra))
        for x_q in bars_b:
            q = int(round(x_q * rb))
            d = (dwa - p) + q  # 该小节线对对应的重叠宽度（缩放后像素）
            if d < 8 or d >= min(dwa, dwb):
                continue
            err = float(
                np.mean(
                    (ga[:, -d:].astype(np.float64) - gb[:, :d].astype(np.float64)) ** 2
                )
            )
            if best is None or err < best[0]:
                best = (err, x_p / wa, x_q / wb)

    if best is None:
        return None
    return (best[1], best[2])


def compute_stitch_seams(
    images: List[Image.Image],
    max_width: int = 600,
    coefficient_horizontal: float = 0.7,
    coefficient_vertical: float = 0.8,
    note_rgb: Optional[Tuple[int, int, int]] = None,
    tolerance: float = 60.0,
    softness: float = 20.0,
) -> List[Tuple[float, float]]:
    """返回相邻截图之间的拼接缝，长度 len(images)-1。

    每条缝为 (right_of_left, left_of_right)，均归一化到 0..1：
    - right_of_left：左侧截图的右裁剪边界（应落在小节线上）；
    - left_of_right：右侧截图的左裁剪边界（应落在小节线上）。

    拼接缝优先选择两张截图中共有的小节线，从而保证拼接处一定在小节线上；
    无法检出可靠小节线对时回退到旧的盲 MSE 重叠偏移。
    """
    cleaned = [
        preprocess_for_detection(im, note_rgb, tolerance, softness) for im in images
    ]
    # 与 /api/detect_measures 使用同一套检测（含启发式回退），保证拼接缝的小节线
    # 一定出现在前端拿到的 measures 列表中。
    bars = [
        detect_measure_barlines(
            im,
            coefficient_horizontal=coefficient_horizontal,
            coefficient_vertical=coefficient_vertical,
        )
        for im in cleaned
    ]

    seams: List[Tuple[float, float]] = []
    for i in range(len(images) - 1):
        seam = _best_barline_seam(
            cleaned[i], cleaned[i + 1], bars[i], bars[i + 1], max_width
        )
        if seam is None:
            ga, _ = _to_gray_resized(cleaned[i], max_width)
            gb, _ = _to_gray_resized(cleaned[i + 1], max_width)
            o = _best_stitch_offset(ga, gb)
            left = _snap_to_barline(o, bars[i + 1], images[i + 1].width)
            right = _snap_to_barline(1.0 - o, bars[i], images[i].width)
            seam = (right, left)
        seams.append(seam)
    return seams


def layout_rows(
    images: List[Image.Image],
    content_w: int,
    margin: int,
    spacing: int,
    fit_width: bool = True,
    align: str = "left",
    valign: str = "top",
) -> List[Tuple[List[Tuple[Image.Image, int, int, int, int]], int]]:
    """把图片从左到右排列、放满一行换行，返回 [(行内项, 行高), ...]。

    每个行内项为 (img, x, w, h, dy)。align 控制水平对齐（left/center/right），
    valign 控制同一行内不同高度图片的竖直对齐（top/center/bottom）。
    """
    rows: List[Tuple[List[Tuple[Image.Image, int, int, int, int]], int]] = []
    row: List[Tuple[Image.Image, int, int]] = []  # 暂存 (img, w, h)，x/dy 在换行时再定
    row_used = 0
    row_h = 0

    def flush() -> List[Tuple[Image.Image, int, int, int, int]]:
        nonlocal row, row_used
        offset = 0
        if align == "center" and row_used < content_w:
            offset = (content_w - row_used) // 2
        elif align == "right" and row_used < content_w:
            offset = content_w - row_used
        out: List[Tuple[Image.Image, int, int, int, int]] = []
        px = margin + offset
        for img, w, h in row:
            dy = 0
            if valign == "center":
                dy = (row_h - h) // 2
            elif valign == "bottom":
                dy = row_h - h
            out.append((img, px, w, h, dy))
            px += w
        row = []
        row_used = 0
        return out

    for img in images:
        w, h = img.size
        if fit_width and w > content_w:
            r = content_w / w
            w = content_w
            h = int(round(h * r))
            img = img.resize((w, h), RESAMPLE)
        if row and row_used + w > content_w:
            rows.append((flush(), row_h))
            row_h = 0
        row.append((img, w, h))
        row_used += w
        row_h = max(row_h, h)
    if row:
        rows.append((flush(), row_h))
    return rows


def build_pdf_from_images(
    images_dir: Path,
    output_pdf: Path,
    metadata: Optional[VideoMetadata] = None,
    page_width: int = 1654,   # aprox A4 a ~150 dpi
    page_height: int = 2339,
    orientation: str = "portrait",
    margin: int = 40,
    spacing: int = 25,
    bg_color: str = "white",
    text_color: str = "181818",
    align: str = "left",
    valign: str = "top",
    fit_width: bool = True,
    title_lines: Optional[List[str]] = None,
    title_spacing: Optional[int] = None,
    source_url: Optional[str] = None,
):
    """
    按小节横向排版生成 PDF：每张（已处理好的）图片从左到右排列、放满一行换行，
    超过一页时翻页。第一页顶部是标题/作者页头，每页底部有页码。
    """
    image_paths = sorted(images_dir.glob("*.png"))
    if not image_paths:
        raise RuntimeError("没有可用于生成 PDF 的图像。")

    footer_height = 80

    if orientation == "landscape":
        page_width, page_height = page_height, page_width

    content_w = page_width - 2 * margin
    images = [Image.open(p).convert("RGB") for p in image_paths]

    if title_lines is None and metadata is not None:
        title_lines = [
            ln for ln in [(metadata.display_title or "").strip(), (metadata.channel or "").strip()]
            if ln
        ]
    src_url = source_url if source_url is not None else (
        metadata.source_url if metadata is not None else None
    )

    rows = layout_rows(images, content_w, margin, spacing, fit_width, align=align, valign=valign)

    pages: List[Image.Image] = []
    page = Image.new("RGB", (page_width, page_height), bg_color)
    current_y = draw_first_page_header(
        page, title_lines, src_url, page_width, page_height, margin,
        text_color=text_color, title_spacing=title_spacing,
    )

    for row, row_h in rows:
        if current_y + row_h + margin + footer_height > page_height:
            pages.append(page)
            page = Image.new("RGB", (page_width, page_height), bg_color)
            current_y = margin
        for img, x, w, h, dy in row:
            page.paste(img, (x, current_y + dy))
        current_y += row_h + spacing

    pages.append(page)

    page_font = load_font(26)
    footer_color = hex_to_rgb(text_color)
    total = len(pages)
    for idx, page_img in enumerate(pages, start=1):
        draw = ImageDraw.Draw(page_img)
        label = f"{idx} / {total}"
        label_w, label_h = text_size(draw, label, page_font)
        footer_y = page_height - footer_height + (footer_height - label_h) // 2
        draw.text(
            ((page_width - label_w) / 2, footer_y),
            label,
            fill=footer_color,
            font=page_font,
        )

    pages[0].save(
        output_pdf,
        save_all=True,
        append_images=pages[1:],
        resolution=150.0,
    )

    return len(pages)


def build_long_image(
    images_dir: Path,
    output_png: Path,
    page_width: int = 1654,
    margin: int = 40,
    spacing: int = 25,
    bg_color: str = "white",
    text_color: str = "181818",
    align: str = "left",
    valign: str = "top",
    fit_width: bool = True,
    title_lines: Optional[List[str]] = None,
    title_spacing: Optional[int] = None,
    source_url: Optional[str] = None,
) -> int:
    """把图片按行横向排版，输出一张竖向长图，返回长图高度（像素）。"""
    image_paths = sorted(images_dir.glob("*.png"))
    if not image_paths:
        raise RuntimeError("没有可用于生成长图的图像。")

    content_w = page_width - 2 * margin
    images = [Image.open(p).convert("RGB") for p in image_paths]
    rows = layout_rows(images, content_w, margin, spacing, fit_width, align=align, valign=valign)

    total_h = margin
    header_h = draw_first_page_header(
        Image.new("RGB", (1, 1)), title_lines, source_url, page_width, 2339, margin,
        text_color=text_color, title_spacing=title_spacing,
    )
    # 重新量一次页头高度（上面的占位图只是用来量文字高度）
    if title_lines or source_url:
        total_h = header_h
    else:
        total_h = margin

    for _, row_h in rows:
        total_h += row_h + spacing

    canvas = Image.new("RGB", (page_width, max(1, total_h)), bg_color)
    if title_lines or source_url:
        current_y = draw_first_page_header(
            canvas, title_lines, source_url, page_width, 2339, margin,
            text_color=text_color, title_spacing=title_spacing,
        )
    else:
        current_y = margin

    for row, row_h in rows:
        for img, x, w, h, dy in row:
            canvas.paste(img, (x, current_y + dy))
        current_y += row_h + spacing

    canvas.save(output_png)
    return canvas.height


def main():
    parser = argparse.ArgumentParser(
        description="Extrae tablatura de un video y genera un PDF con capturas."
    )

    parser.add_argument(
        "source",
        help="URL de YouTube o ruta a archivo de video local",
    )

    parser.add_argument(
        "--output",
        default="tablatura.pdf",
        help="Nombre del PDF de salida (default: tablatura.pdf)",
    )

    parser.add_argument(
        "--title",
        default=None,
        help="Título a mostrar en la portada del PDF. Sobrescribe el título de YouTube.",
    )

    parser.add_argument(
        "--channel",
        default=None,
        help="Canal o autor a mostrar en la portada del PDF. Sobrescribe el canal de YouTube.",
    )

    parser.add_argument(
        "--sample-every",
        type=float,
        default=2.0,
        help="Tomar una captura cada X segundos (default: 2.0)",
    )

    parser.add_argument(
        "--crop-top-ratio",
        type=float,
        default=1.0,
        help="Compatibilidad: porcentaje superior a recortar (default: 1.0).",
    )

    parser.add_argument(
        "--crop-y-start",
        type=float,
        default=None,
        help="Inicio vertical del recorte, de 0.0 a 1.0. Útil para tabs abajo.",
    )

    parser.add_argument(
        "--crop-y-end",
        type=float,
        default=None,
        help="Final vertical del recorte, de 0.0 a 1.0. Útil para tabs abajo.",
    )

    parser.add_argument(
        "--crop-x-start",
        type=float,
        default=None,
        help="Inicio horizontal del recorte, de 0.0 a 1.0 (default: 0.0).",
    )

    parser.add_argument(
        "--crop-x-end",
        type=float,
        default=None,
        help="Final horizontal del recorte, de 0.0 a 1.0 (default: 1.0).",
    )

    parser.add_argument(
        "--hash-threshold",
        type=int,
        default=16,
        help="Compatibilidad: ya no se usa como criterio principal (default: 16)",
    )

    parser.add_argument(
        "--hash-size",
        type=int,
        default=12,
        help="Compatibilidad: ya no se usa como criterio principal (default: 12)",
    )

    parser.add_argument(
        "--diff-threshold",
        type=float,
        default=0.010,
        help="Máxima proporción de píxeles cambiados para considerar duplicado (default: 0.010)",
    )

    parser.add_argument(
        "--compare-window",
        type=int,
        default=1,
        help="Cantidad de capturas recientes contra las que comparar (default: 1)",
    )

    parser.add_argument(
        "--debug-diffs",
        action="store_true",
        help="Guarda imágenes de diff además de las imágenes normalizadas/enmascaradas.",
    )

    parser.add_argument(
        "--start",
        type=float,
        default=0.0,
        help="Segundo inicial desde donde procesar",
    )

    parser.add_argument(
        "--end",
        type=float,
        default=None,
        help="Segundo final hasta donde procesar",
    )

    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Si se pasa, conserva las capturas intermedias en una carpeta",
    )

    parser.add_argument(
        "--keep-comparison-images",
        action="store_true",
        help="Guarda las imágenes usadas para comparar duplicados. Muy útil para debug.",
    )

    parser.add_argument(
        "--save-cleaned",
        action="store_true",
        help="Guardar en el PDF las imágenes con la franja borrada en vez de las originales",
    )

    parser.add_argument(
        "--band-half-width",
        type=int,
        default=90,
        help="Medio ancho de la franja vertical a ignorar en píxeles (default: 90)",
    )

    parser.add_argument(
        "--min-band-pixels",
        type=int,
        default=20,
        help="Mínima concentración de píxeles azul/verde para detectar la franja (default: 20)",
    )

    parser.add_argument(
        "--target-tolerance",
        type=int,
        default=48,
        help="Tolerancia para detectar el color #ccd8f0 (default: 48)",
    )

    args = parser.parse_args()

    if args.start < 0:
        parser.error("--start 不能为负数")
    if args.end is not None and args.end <= args.start:
        parser.error("--end 必须大于 --start")
    if args.crop_y_start is not None or args.crop_y_end is not None:
        crop_y_start = args.crop_y_start if args.crop_y_start is not None else 0.0
        crop_y_end = args.crop_y_end if args.crop_y_end is not None else 1.0
    else:
        crop_y_start = 0.0
        crop_y_end = args.crop_top_ratio
    try:
        validate_crop_ratios(crop_y_start, crop_y_end)
    except ValueError as exc:
        parser.error(str(exc))

    crop_x_start = args.crop_x_start if args.crop_x_start is not None else 0.0
    crop_x_end = args.crop_x_end if args.crop_x_end is not None else 1.0
    try:
        validate_crop_x_ratios(crop_x_start, crop_x_end)
    except ValueError as exc:
        parser.error(str(exc))

    source = args.source
    output_pdf = Path(args.output).resolve()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        crops_dir = tmp_path / "crops"
        comparison_dir = tmp_path / "comparison" if args.keep_comparison_images else None

        if source.startswith("http://") or source.startswith("https://"):
            print("正在下载视频...")
            video_path, metadata, downloaded_start_sec = download_video(
                source,
                tmp_path,
                start_sec=args.start,
                end_sec=args.end,
            )
            metadata = build_video_metadata(
                raw_title=metadata.raw_title,
                channel=metadata.channel,
                source_url=metadata.source_url,
                title_override=args.title,
                channel_override=args.channel,
            )
        else:
            video_path = Path(source).resolve()
            if not video_path.exists():
                raise FileNotFoundError(f"文件不存在：{video_path}")
            downloaded_start_sec = 0.0
            metadata = build_video_metadata(
                raw_title=args.title,
                channel=args.channel,
                source_url=None,
                title_override=args.title,
                channel_override=args.channel,
            )

        print(f"源视频：{video_path}")
        if metadata.display_title:
            print(f"PDF 标题：{metadata.display_title}")
        if metadata.channel:
            print(f"PDF 署名：{metadata.channel}")

        extract_start_sec = max(0.0, args.start - downloaded_start_sec)
        extract_end_sec = args.end - downloaded_start_sec if args.end is not None else None
        if downloaded_start_sec > 0:
            print(
                f"已从 {downloaded_start_sec:.2f}s 开始下载片段；"
                "从本地文件的 0.00s 开始处理。"
            )

        options = ExtractionOptions(
            sample_every_sec=args.sample_every,
            crop_y_start_ratio=crop_y_start,
            crop_y_end_ratio=crop_y_end,
            crop_x_start_ratio=crop_x_start,
            crop_x_end_ratio=crop_x_end,
            hash_threshold=args.hash_threshold,
            hash_size=args.hash_size,
            diff_threshold=args.diff_threshold,
            compare_window=args.compare_window,
            debug_diffs=args.debug_diffs,
            start_sec=extract_start_sec,
            end_sec=extract_end_sec,
            save_cleaned=args.save_cleaned,
            band_half_width=args.band_half_width,
            min_band_pixels=args.min_band_pixels,
            target_tolerance=args.target_tolerance,
        )

        stats = extract_unique_crops(
            video_path=video_path,
            crops_dir=crops_dir,
            comparison_dir=comparison_dir,
            sample_every_sec=options.sample_every_sec,
            crop_y_start_ratio=options.crop_y_start_ratio,
            crop_y_end_ratio=options.crop_y_end_ratio,
            crop_x_start_ratio=options.crop_x_start_ratio,
            crop_x_end_ratio=options.crop_x_end_ratio,
            hash_threshold=options.hash_threshold,
            hash_size=options.hash_size,
            diff_threshold=options.diff_threshold,
            compare_window=options.compare_window,
            debug_diffs=options.debug_diffs,
            start_sec=options.start_sec,
            end_sec=options.end_sec,
            save_cleaned=options.save_cleaned,
            band_half_width=options.band_half_width,
            min_band_pixels=options.min_band_pixels,
            target_tolerance=options.target_tolerance,
        )

        if stats.captures_kept == 0:
            raise RuntimeError("未提取到任何有效截图。")

        print("正在生成 PDF...")
        build_pdf_from_images(crops_dir, output_pdf, metadata=metadata)

        print(f"PDF 已生成于：{output_pdf}")

        if args.keep_images:
            final_crops = Path.cwd() / "capturas_tablatura"
            if final_crops.exists():
                shutil.rmtree(final_crops)
            shutil.copytree(crops_dir, final_crops)
            print(f"截图已保存到：{final_crops}")

        if args.keep_comparison_images and comparison_dir is not None:
            final_comparison = Path.cwd() / "debug_comparacion_tablatura"
            if final_comparison.exists():
                shutil.rmtree(final_comparison)
            shutil.copytree(comparison_dir, final_comparison)
            print(f"比较图像已保存到：{final_comparison}")


if __name__ == "__main__":
    main()
