import contextlib
import hashlib
import io
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
import os
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bili
import pdf_render
from pdf_render import PDF_DPI_DEFAULT, PdfRenderError
from runtime_paths import data_dir, resource_dir
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps

from tab_extractor import (
    ExtractionOptions,
    ExtractionStats,
    RESAMPLE,
    VideoMetadata,
    build_long_image,
    build_pdf_from_images,
    build_video_metadata,
    compute_stitch_seams,
    detect_measure_barlines,
    download_bilibili_video,
    extract_bilibili_id,
    extract_note_mask,
    extract_unique_crops,
    find_video_file,
    get_video_duration,
    hex_to_rgb,
    normalize_bilibili_url,
    preprocess_for_detection,
    probe_bilibili_metadata,
    save_video_frame,
    split_into_measures,
    validate_crop_ratios,
    validate_crop_x_ratios,
)


ROOT_DIR = data_dir()
CACHE_DIR = ROOT_DIR / "BiliTabCapture_cache"
UPLOADS_DIR = CACHE_DIR / "uploads"
PREVIEWS_DIR = CACHE_DIR / "previews"
RUNS_DIR = CACHE_DIR / "runs"


def hash_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file's content, used as the local-video cache key."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bilibili_cache_dir(bvid: str) -> Path:
    return CACHE_DIR / "bv" / bvid


def local_cache_dir(file_hash: str) -> Path:
    return CACHE_DIR / "local" / file_hash


def image_cache_dir(file_hash: str) -> Path:
    """单张图片的哈希缓存目录（存原图 crop 与 state.json）。"""
    return CACHE_DIR / "img" / file_hash


def pdf_cache_dir(file_hash: str) -> Path:
    """PDF 的哈希缓存目录（存 master.pdf、逐页渲染图与 state.json）。"""
    return CACHE_DIR / "pdf" / file_hash


def _cache_clearable(cache_dir: Path) -> bool:
    """仅允许清除已知的缓存子目录，避免越界删除。"""
    try:
        cache_dir = cache_dir.resolve()
        root = CACHE_DIR.resolve()
        rel = cache_dir.relative_to(root)
    except (OSError, ValueError):
        return False
    return rel.parts and rel.parts[0] in {"bv", "local", "img", "pdf"}


def has_restorable_cache(cache_dir: Path, state: Optional[Dict[str, Any]] = None) -> bool:
    """是否有可“恢复进度”的内容 = 截图(captures+png) 或 保存过的第2步参数(params2)。

    截图前若只调过第2步参数(写进 params2)也算命中，导回时可弹“恢复/从新开始”。
    """
    if state is None:
        state = load_state_json(cache_dir)
    return _has_images(cache_dir, state) or _has_params(state)


def _has_images(cache_dir: Path, state: Optional[dict]) -> bool:
    if not state or not state.get("captures"):
        return False
    crops = cache_dir / "crops"
    files = (state.get("captures") or [])
    if not files:
        return False
    return any((crops / (f.get("file") or "")).exists() for f in files)


def _has_params(state: Optional[dict]) -> bool:
    if not state:
        return False
    p2 = state.get("params2")
    return isinstance(p2, dict) and any(
        p2.get(k) not in (None, PARAMS2_DEFAULTS.get(k)) for k in p2
    )


def load_state_json(cache_dir: Path) -> Optional[Dict[str, Any]]:
    p = cache_dir / "state.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state_json(cache_dir: Path, data: Dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "state.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def job_crops_dir(job_id: str) -> Path:
    """Crops dir for a job: cache-keyed sources persist under the cache dir."""
    with STORE_LOCK:
        job = JOBS.get(job_id)
    if job and job.get("crops_dir"):
        return Path(job["crops_dir"])
    return RUNS_DIR / job_id / "crops"


def current_version() -> str:
    """从本地 VERSION 文件读取当前版本号（打包时该文件会随资源一并打包）。"""
    candidates = [resource_dir() / "VERSION", ROOT_DIR / "VERSION", Path(__file__).resolve().parent / "VERSION"]
    for p in candidates:
        try:
            text = p.read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            continue
    return "0.0"


APP_VERSION = current_version()

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4s"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
ALLOWED_PDF_EXTENSIONS = {".pdf"}


def load_rendered_pages(pdf_path: Path, pages_dir: Path, dpi: int) -> List[Dict[str, Any]]:
    """把 PDF 逐页渲染成 pages_dir/page_XXXX.png，返回按页序的清单。

    每项：{"file","url","t","w","h","page"}；page 为 1 基页码，供卡片显示。
    """
    rendered = pdf_render.render_pdf_pages(pdf_path, pages_dir, dpi=dpi, prefix="page")
    pages = []
    for item in rendered:
        pages.append({
            "file": item["file"],
            "url": "",
            "t": 0.0,
            "w": item["w"],
            "h": item["h"],
            "page": item["index"] + 1,
        })
    return pages


def read_capture_dpi(value: Any) -> int:
    """第 2 步的 PDF 渲染 DPI（存进 params2，可恢复）。"""
    return pdf_render.clamp_dpi(value, PDF_DPI_DEFAULT)


def _pages_complete(pages_dir: Path, total_pages: int) -> bool:
    """cache/pages 里是否已按当前 DPI 渲染齐全部页面（缺页则需重渲）。"""
    if not pages_dir.exists():
        return False
    for i in range(1, total_pages + 1):
        if not (pages_dir / f"page_{i:04d}.png").exists():
            return False
    return True


MIN_SPLIT_PX = 30  # 横向分割后每段的最小绝对像素高度（与前端保持一致）

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

SOURCES: Dict[str, Dict[str, Any]] = {}
JOBS: Dict[str, Dict[str, Any]] = {}
STORE_LOCK = threading.Lock()

BILIBILI_LOGIN_LOCK = threading.Lock()
BILIBILI_LOGIN: Dict[str, Any] = {"status": "idle", "qr": None, "message": None}
BILIBILI_LOGIN_TOKEN: Optional[str] = None


def bilibili_cookie_path() -> Path:
    # 所有平台统一由 bili 模块管理的 cookie.txt。
    return bili.COOKIE_PATH


def run_bilibili_login_worker(token: str) -> None:
    """全平台统一的 B 站扫码登录。"""
    try:
        qrcode_key, qr_data_uri = bili.qrcode_login_generate()
    except Exception as exc:
        with BILIBILI_LOGIN_LOCK:
            if BILIBILI_LOGIN_TOKEN == token:
                BILIBILI_LOGIN.update(status="error", qr=None, message=f"无法生成二维码：{exc}")
        return

    with BILIBILI_LOGIN_LOCK:
        if BILIBILI_LOGIN_TOKEN != token:
            return
        BILIBILI_LOGIN.update(qr=qr_data_uri, message="请用哔哩哔哩扫描二维码登录")

    try:
        cookie = bili.qrcode_login_poll(qrcode_key)
    except Exception as exc:
        with BILIBILI_LOGIN_LOCK:
            if BILIBILI_LOGIN_TOKEN == token:
                BILIBILI_LOGIN.update(status="error", qr=None, message=str(exc))
        return

    bili.write_cookie(cookie)
    with BILIBILI_LOGIN_LOCK:
        if BILIBILI_LOGIN_TOKEN == token:
            BILIBILI_LOGIN.update(status="success", qr=None, message="登录成功。")
    return


def ensure_cache_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for directory in (UPLOADS_DIR, PREVIEWS_DIR, RUNS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def cleanup_orphan_transient() -> int:
    """删除“孤儿”中间产物：目录因没有对应的内存 source/job 而不被任何生命周期引用。

    runs/uploads/previews 只作为本机操作中的中间步骤(生成中的 final 分片、待导出的
    PDF/长图、预览缩略图、上传中转)，不参与持久缓存恢复(那是 bv/local/img)。
    干净的判据是状态而非时间：一旦其所属的 job/source 已结束(不在内存 SOURCES/JOBS)，
    该产物即为孤儿，可安全删除。返回清理的目录数。
    """
    with STORE_LOCK:
        live_source_ids = {str(s.get("id")) for s in SOURCES.values()}
        live_job_ids = set(JOBS.keys())
    removed = 0

    # uploads/<source_id>: 仅当该 source 已不存在且目录非空时清理。
    for d in UPLOADS_DIR.glob("*/"):
        if d.is_dir() and d.name not in live_source_ids:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1

    # previews: 顶层 <sourceid>_<ms>_<rand>.jpg 及 <sourceid>/(video) 均为该 source 的临时帧。
    for f in PREVIEWS_DIR.glob("*.jpg"):
        sid = (f.name or "").split("_", 1)[0]
        if sid not in live_source_ids:
            f.unlink(missing_ok=True)
            removed += 1
    for d in PREVIEWS_DIR.glob("*/"):
        if d.is_dir() and d.name not in live_source_ids:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1

    # runs/<job_id>: 当前无内存 job 引用即是孤儿。
    for d in RUNS_DIR.glob("*/"):
        if d.is_dir() and d.name not in live_job_ids:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


def cleanup_source_transient(source_id: str) -> None:
    """某源开始新一轮处理时的流程残档清理（基于生命周期状态）。

    预览缩略图由 /api/preview 每次按需重建，无需长期保留；在同一 source 下删掉即可。
    持久缓存(bv/local/img)不在此清理范围。
    """
    for f in PREVIEWS_DIR.glob(f"{source_id}_*.jpg"):
        f.unlink(missing_ok=True)
    vdir = PREVIEWS_DIR / source_id
    if vdir.exists():
        shutil.rmtree(vdir, ignore_errors=True)


def evict_superseded_jobs(source_id: str, keep_job_id: Optional[str] = None, run_dir_name: Optional[str] = None) -> None:
    """同源重新处理时代替式清理。

    当一个 job(为该 source)再次发起,旧的同源已完成 job 即被取代：移除其 runs 目录、
    从内存 JOBS 摘除，让 runs/ 不会同一 source 多次累积。
    keep_job_id: 若给，则跳过新保留的 job。
    run_dir_name：job 对应的 runs/<name>(缺省由 JOBS[crops?]推断)。
    """
    with STORE_LOCK:
        stale = []
        for jid, job in JOBS.items():
            if run_dir_name and jid == run_dir_name:
                continue
            if keep_job_id and jid == keep_job_id:
                continue
            if job.get("source_id") != source_id:
                continue
            if job.get("status") in ("queued", "running", "downloading"):
                continue  # 仍在进行中的不可删
            stale.append(jid)
        for jid in stale:
            JOBS.pop(jid, None)
        stale_dirs = list(stale)
    # 等在释放 STORE_LOCK 后再删盘
    for jid in stale_dirs:
        d = RUNS_DIR / jid
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

def metadata_to_dict(metadata: VideoMetadata) -> Dict[str, Optional[str]]:
    return {
        "raw_title": metadata.raw_title,
        "display_title": metadata.display_title,
        "channel": metadata.channel,
        "source_url": metadata.source_url,
    }


def metadata_from_dict(data: Dict[str, Any]) -> VideoMetadata:
    return VideoMetadata(
        raw_title=data.get("raw_title"),
        display_title=data.get("display_title"),
        channel=data.get("channel"),
        source_url=data.get("source_url"),
    )


def json_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def parse_float(value: Any, field_name: str, default: Optional[float] = None) -> float:
    if value in (None, ""):
        if default is None:
            raise ValueError(f"{field_name} 不能为空")
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是数字") from exc


def parse_optional_float(value: Any, field_name: str) -> Optional[float]:
    if value in (None, ""):
        return None
    return parse_float(value, field_name)


def parse_bool(value: Any) -> bool:
    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


def parse_hex_color(value: Any, default: str = "#181818") -> str:
    value = (value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value
    if re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return "#" + value
    return default


def parse_optional_note_color(value: Any) -> Optional[Tuple[int, int, int]]:
    """解析音符颜色；为空或非法时返回 None（表示不按音符颜色二值化）。"""
    value = (value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return hex_to_rgb(value)
    if re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return hex_to_rgb("#" + value)
    return None


def append_job_log(job_id: str, text: str) -> None:
    text = text.replace("\r", "\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return
    with STORE_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["logs"].extend(lines)
        job["logs"] = job["logs"][-300:]


def update_job(job_id: str, **updates: Any) -> None:
    with STORE_LOCK:
        job = JOBS.get(job_id)
        if job:
            job.update(updates)


class JobLogWriter:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def write(self, text: str) -> int:
        append_job_log(self.job_id, text)
        return len(text)

    def flush(self) -> None:
        pass


def make_progress_callback(job_id: str):
    def progress(phase: str, stats: ExtractionStats) -> None:
        update_job(job_id, phase=phase, stats=stats.to_dict(), updated_at=time.time())

    return progress


def source_or_error(source_id: str) -> Dict[str, Any]:
    with STORE_LOCK:
        source = SOURCES.get(source_id)
    if source is None:
        raise ValueError("未知的视频源，请先导入视频。")
    return source


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_output_name(value: str, ext: str) -> str:
    # 保留中文等 Unicode，只替换 Windows 文件名不允许的字符。
    filename = _INVALID_FILENAME_CHARS.sub("_", (value or "tablatura.pdf").strip()).strip(" .")
    # 只去掉结尾的 .pdf/.png 扩展名（保留标题中其它位置的「.」）。
    for existing in (".pdf", ".png"):
        if filename.lower().endswith(existing):
            filename = filename[: -len(existing)]
            break
    if not filename:
        filename = "tablatura"
    return filename + ext


def safe_pdf_name(value: str) -> str:
    return safe_output_name(value, ".pdf")


def cached_remote_preview_video(source: Dict[str, Any]) -> Path:
    # 仅 B 站远程源需要先下载再取帧；本地文件直接返回路径。
    preview_dir = PREVIEWS_DIR / source["id"] / "video"
    preview_dir.mkdir(parents=True, exist_ok=True)

    existing = find_video_file(preview_dir)
    if existing is not None:
        return existing

    if source["type"] == "bilibili":
        return download_bilibili_video(source["url"], preview_dir, quality=16)

    raise RuntimeError(f"不支持的远程源类型：{source.get('type')}")


def run_capture_job(job_id: str, payload: Dict[str, Any]) -> None:
    log_writer = JobLogWriter(job_id)
    with contextlib.redirect_stdout(log_writer), contextlib.redirect_stderr(log_writer):
        try:
            source = source_or_error(payload["source_id"])
            start_sec = parse_float(payload.get("start"), "start", 0.0)
            end_sec = parse_optional_float(payload.get("end"), "end")
            if start_sec < 0:
                raise ValueError("开始时间必须大于等于 0")
            if end_sec is not None and end_sec <= start_sec:
                raise ValueError("结束时间必须大于开始时间")

            crop_y_start = parse_float(payload.get("crop_y_start"), "crop_y_start", 0.0)
            crop_y_end = parse_float(payload.get("crop_y_end"), "crop_y_end", 1)
            crop_x_start = parse_float(payload.get("crop_x_start"), "crop_x_start", 0.0)
            crop_x_end = parse_float(payload.get("crop_x_end"), "crop_x_end", 1.0)
            validate_crop_ratios(crop_y_start, crop_y_end)
            validate_crop_x_ratios(crop_x_start, crop_x_end)

            options = ExtractionOptions(
                sample_every_sec=parse_float(payload.get("sample_every"), "sample_every", 2.0),
                crop_y_start_ratio=crop_y_start,
                crop_y_end_ratio=crop_y_end,
                crop_x_start_ratio=crop_x_start,
                crop_x_end_ratio=crop_x_end,
                diff_threshold=parse_float(payload.get("diff_threshold"), "diff_threshold", 0.010),
                compare_window=int(parse_float(payload.get("compare_window"), "compare_window", 1)),
                debug_diffs=parse_bool(payload.get("debug_diffs")),
                start_sec=start_sec,
                end_sec=end_sec,
                save_cleaned=parse_bool(payload.get("save_cleaned")),
                band_half_width=int(parse_float(payload.get("band_half_width"), "band_half_width", 90)),
                min_band_pixels=int(parse_float(payload.get("min_band_pixels"), "min_band_pixels", 20)),
                target_tolerance=int(parse_float(payload.get("target_tolerance"), "target_tolerance", 48)),
            )

            run_dir = RUNS_DIR / job_id
            cache_dir = Path(source["cache_dir"]) if source.get("cache_dir") else None
            if cache_dir is not None:
                # Cache-keyed sources (bilibili / local): persist crops under the cache dir.
                download_dir = cache_dir
                crops_dir = cache_dir / "crops"
                comparison_dir = cache_dir / "comparison" if options.debug_diffs else None
                crops_dir.mkdir(parents=True, exist_ok=True)
            else:
                download_dir = run_dir / "download"
                crops_dir = run_dir / "crops"
                comparison_dir = run_dir / "comparison" if options.debug_diffs else None
                run_dir.mkdir(parents=True, exist_ok=True)

            # 每次重新生成截图前清空上一次运行遗留的旧截图，避免调整起止时间再次
            # “生成图片”时把上一批已不生效的图片一起收集进来造成残留。
            for old in crops_dir.glob("*.png"):
                old.unlink(missing_ok=True)
            (crops_dir / "times.json").unlink(missing_ok=True)

            update_job(job_id, status="running", phase="downloading", updated_at=time.time())

            source_metadata = metadata_from_dict(source["metadata"])
            if source["type"] == "bilibili":
                video_path = Path(source.get("video_path") or "")
                if not video_path.exists():
                    print("正在下载 Bilibili 视频...")
                    video_path = download_bilibili_video(source["url"], download_dir)
                downloaded_start_sec = 0.0
                metadata = build_video_metadata(
                    raw_title=source_metadata.raw_title,
                    channel=source_metadata.channel,
                    source_url=source_metadata.source_url,
                    title_override=payload.get("title"),
                    channel_override=payload.get("channel"),
                )
            else:
                video_path = Path(source["path"])
                downloaded_start_sec = 0.0
                metadata = build_video_metadata(
                    raw_title=source_metadata.raw_title,
                    channel=source_metadata.channel,
                    source_url=None,
                    title_override=payload.get("title"),
                    channel_override=payload.get("channel"),
                )

            extract_start_sec = max(0.0, options.start_sec - downloaded_start_sec)
            extract_end_sec = (
                options.end_sec - downloaded_start_sec
                if options.end_sec is not None
                else None
            )

            update_job(job_id, phase="extracting", updated_at=time.time())
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
                start_sec=extract_start_sec,
                end_sec=extract_end_sec,
                save_cleaned=options.save_cleaned,
                band_half_width=options.band_half_width,
                min_band_pixels=options.min_band_pixels,
                target_tolerance=options.target_tolerance,
                progress_callback=make_progress_callback(job_id),
            )
            if stats.captures_kept == 0:
                raise RuntimeError("未能提取到有效画面。")

            times = {}
            times_path = crops_dir / "times.json"
            if times_path.exists():
                try:
                    with times_path.open("r", encoding="utf-8") as fh:
                        times = json.load(fh)
                except (OSError, ValueError):
                    times = {}

            captures = []
            for p in sorted(crops_dir.glob("*.png")):
                t = float(times.get(p.name, 0.0))
                try:
                    with Image.open(p) as img:
                        w, h = img.size
                except Exception:
                    w, h = 0, 0
                captures.append(
                    {
                        "file": p.name,
                        "url": f"/api/captures/{job_id}/{p.name}",
                        "t": t,
                        "w": w,
                        "h": h,
                    }
                )

            capture_params = {
                "crop_x_start": options.crop_x_start_ratio,
                "crop_x_end": options.crop_x_end_ratio,
                "crop_y_start": options.crop_y_start_ratio,
                "crop_y_end": options.crop_y_end_ratio,
                "diff_threshold": options.diff_threshold,
                "band_half_width": options.band_half_width,
                "compare_window": options.compare_window,
                "min_band_pixels": options.min_band_pixels,
                "target_tolerance": options.target_tolerance,
            }

            update_job(
                job_id,
                status="done",
                phase="done",
                stats=stats.to_dict(),
                captures=captures,
                video_path=str(video_path),
                capture_params=capture_params,
                metadata=metadata_to_dict(metadata),
                updated_at=time.time(),
            )
            if cache_dir is not None:
                update_job(
                    job_id,
                    crops_dir=str(crops_dir),
                    cache_dir=str(cache_dir),
                )
                save_state_json(
                    cache_dir,
                    {
                        "captures": captures,
                        "capture_params": capture_params,
                        "metadata": metadata_to_dict(metadata),
                    },
                )
            print(f"已生成 {len(captures)} 张截图。")
        except Exception as exc:
            update_job(
                job_id,
                status="error",
                phase="error",
                error=str(exc),
                updated_at=time.time(),
            )
            print(f"错误：{exc}")


def start_image_capture(source: Dict[str, Any], payload: Dict[str, Any]):
    """图片源不走视频提取，直接按裁剪参数切一张截图、立即产出任务。

    PDF 源同路复用：按 crop* 裁切每一页渲染图，一页一张截图 = 第 3 步一张卡片。
    """
    crop_y_start = parse_float(payload.get("crop_y_start"), "crop_y_start", 0.0)
    crop_y_end = parse_float(payload.get("crop_y_end"), "crop_y_end", 1)
    crop_x_start = parse_float(payload.get("crop_x_start"), "crop_x_start", 0.0)
    crop_x_end = parse_float(payload.get("crop_x_end"), "crop_x_end", 1.0)
    validate_crop_ratios(crop_y_start, crop_y_end)
    validate_crop_x_ratios(crop_x_start, crop_x_end)

    job_id = uuid.uuid4().hex
    # 重新生成即取代旧的同源已完成 job；并发中在进行的保留。
    evict_superseded_jobs(source["id"], run_dir_name=job_id)
    cleanup_source_transient(source["id"])
    run_dir = RUNS_DIR / job_id
    # 有缓存目录的源（图片/PDF）把截图持久化到 cache/crops，历史记录与恢复才拿得到；
    # 与视频源同一约定：job 的 crops_dir 指向缓存目录。
    cache_dir = Path(source["cache_dir"]) if source.get("cache_dir") else None
    crops_dir = (cache_dir / "crops") if cache_dir is not None else (run_dir / "crops")
    crops_dir.mkdir(parents=True, exist_ok=True)

    metadata = metadata_from_dict(source.get("metadata", {}))
    is_pdf = source.get("type") == "pdf"
    dpi = parse_float(payload.get("pdf_dpi"), "pdf_dpi", PDF_DPI_DEFAULT)

    captures: List[Dict[str, Any]] = []
    if is_pdf:
        # 页码区间（1 基，闭区间）：与视频的起止时间同一套交互，只是单位换成页。
        total_pages = pdf_render.pdf_page_count(Path(source["path"]))
        start_page = int(parse_float(payload.get("start_page"), "start_page", 1))
        end_page = int(parse_float(payload.get("end_page"), "end_page", total_pages))
        start_page = max(1, min(start_page, total_pages))
        end_page = max(start_page, min(end_page, total_pages))

        if not payload.get("pdf_dpi") and source.get("pdf_dpi"):
            dpi = parse_float(source.get("pdf_dpi"), "pdf_dpi", PDF_DPI_DEFAULT)
        dpi = pdf_render.clamp_dpi(dpi)

        # 渲染缓存：整份 PDF 按当前 DPI 渲染到 cache/pages，换区间/重生成都不必重渲。
        pages_dir = (cache_dir / "pages") if cache_dir is not None else crops_dir
        stamp = pages_dir / f".dpi{dpi}.txt"
        with tempfile.TemporaryDirectory() as tmp:
            if cache_dir is not None and not (stamp.exists() and _pages_complete(pages_dir, total_pages)):
                shutil.rmtree(pages_dir, ignore_errors=True)
                load_rendered_pages(Path(source["path"]), pages_dir, dpi)
                stamp.write_text(str(dpi), encoding="utf-8")
            source_pages = pages_dir if cache_dir is not None else Path(tmp)
            if cache_dir is None:
                load_rendered_pages(Path(source["path"]), source_pages, dpi)

            # 重新生成本源：先清掉上一批截图，避免改页码范围后留下不再生效的旧页。
            for old in crops_dir.glob("page_*.png"):
                old.unlink(missing_ok=True)

            for page_no in range(start_page, end_page + 1):
                page_file = source_pages / f"page_{page_no:04d}.png"
                if not page_file.exists():
                    continue
                img = Image.open(page_file).convert("RGB")
                w, h = img.size
                box = (
                    int(round(w * crop_x_start)),
                    int(round(h * crop_y_start)),
                    int(round(w * crop_x_end)),
                    int(round(h * crop_y_end)),
                )
                img = img.crop(box)
                out_name = f"page_{page_no:04d}.png"
                img.save(crops_dir / out_name)
                captures.append({
                    "file": out_name,
                    "url": f"/api/captures/{job_id}/{out_name}",
                    "t": 0.0,
                    "w": img.width,
                    "h": img.height,
                    "page": page_no,
                })
        if not captures:
            raise ValueError("所选页码范围没有可用页面。")
    else:
        image = Image.open(source["path"]).convert("RGB")
        w, h = image.size
        box = (
            int(round(w * crop_x_start)),
            int(round(h * crop_y_start)),
            int(round(w * crop_x_end)),
            int(round(h * crop_y_end)),
        )
        image = image.crop(box)
        out_name = "crop_0000_t00000.png"
        image.save(crops_dir / out_name)
        captures.append({
            "file": out_name,
            "url": f"/api/captures/{job_id}/{out_name}",
            "t": 0.0,
            "w": image.width,
            "h": image.height,
        })

    stats = ExtractionStats(captures_kept=len(captures)).to_dict()
    with STORE_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "source_id": source["id"],
            "status": "done",
            "phase": "done",
            "logs": [f"已从 PDF 生成 {len(captures)} 张（每页一张）。" if is_pdf else "已导入图片。"],
            "stats": stats,
            "captures": captures,
            "metadata": metadata_to_dict(metadata),
            "error": None,
            "pdf_url": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        if cache_dir is not None:
            JOBS[job_id]["crops_dir"] = str(crops_dir)
            JOBS[job_id]["cache_dir"] = str(cache_dir)

    # 持久化截图态：历史记录/恢复进度都依赖 cache/crops + state.json。
    if cache_dir is not None:
        state = load_state_json(cache_dir) or {}
        state["captures"] = captures
        state["images"] = restore_images({"captures": captures})
        state["metadata"] = state.get("metadata") or metadata_to_dict(metadata)
        if is_pdf:
            state["pdf_dpi"] = dpi
            state["page_count"] = total_pages
            state["page_range"] = {"start": start_page, "end": end_page}
        state.setdefault("capture_params", {})
        state.setdefault("maxStage", 3)
        save_state_json(cache_dir, state)
    return jsonify({"job_id": job_id})


@app.route("/")
def index():
    return render_template("index.html", app_version=APP_VERSION)


@app.get("/api/version")
def api_version():
    return jsonify({"version": APP_VERSION})


SKIPPED_VERSION_FILE = CACHE_DIR / "skipped_version.txt"


@app.get("/api/skipped_version")
def api_skipped_version():
    value = ""
    try:
        value = SKIPPED_VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return jsonify({"skipped_version": value})


@app.post("/api/skipped_version")
def api_set_skipped_version():
    data = request.get_json(silent=True) or {}
    value = str(data.get("version") or "").strip()
    try:
        ensure_cache_dirs()
        if value:
            SKIPPED_VERSION_FILE.write_text(value, encoding="utf-8")
        else:
            SKIPPED_VERSION_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return jsonify({"ok": True})


def run_bilibili_download(source_id: str, url: str, cache_dir: Path, bvid: str) -> None:
    """Background Bilibili download started at import time."""
    try:
        path = download_bilibili_video(url, cache_dir)
        # 统一按 BV 命名(保留实际后缀 .mp4/.m4s)，避免标题的非法字符作文件名。
        target = cache_dir / (f"{bvid}" + Path(path).suffix.lower())
        if path.resolve() != target.resolve():
            shutil.move(str(path), str(target))
        path = target
        with STORE_LOCK:
            src = SOURCES.get(source_id)
            if src:
                src["video_path"] = str(path)
                src["download"] = {"status": "done", "message": None}
    except Exception as exc:
        with STORE_LOCK:
            src = SOURCES.get(source_id)
            if src:
                src["download"] = {"status": "error", "message": str(exc)}


def make_cached_job(source_id: str, cache_dir: Path, state: Dict[str, Any]) -> str:
    """Create a done job from persisted cache state; returns the job_id."""
    job_id = uuid.uuid4().hex
    captures = state.get("captures") or []
    with STORE_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "source_id": source_id,
            "status": "done",
            "phase": "done",
            "logs": ["已从缓存恢复。"],
            "stats": {"captures_kept": len(captures)},
            "captures": captures,
            "metadata": state.get("metadata"),
            "error": None,
            "pdf_url": None,
            "crops_dir": str(cache_dir / "crops"),
            "cache_dir": str(cache_dir),
            "capture_params": state.get("capture_params") or {},
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    return job_id


def restore_images(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reconstruct the frontend images array from persisted state."""
    images = state.get("images")
    if images is not None:
        return images
    return [
        {
            "file": c.get("file"),
            "t": c.get("t", 0),
            "w": c.get("w"),
            "h": c.get("h"),
            "hidden": False,
            "crop": {"l": 0, "r": 1, "t": 0, "b": 1},
            "measures": [],
        }
        for c in (state.get("captures") or [])
    ]


def source_title_from_filename(raw_name: str) -> str:
    """从上传文件的**原始文件名**取出可读标题。

    注意：`secure_filename()` 会剥掉全部非 ASCII 字符（中文名会整个消失，
    "肖邦夜曲.pdf" → "pdf"），因此**标题绝不能从 secure_filename 的结果取**，
    必须用 `upload.filename` 本名，只做最小清理（去扩展名/去目录成分）。
    """
    name = (raw_name or "").replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "").strip()
    stem = Path(name).stem if name else ""
    return stem.strip() or "未命名"


def safe_upload_name(raw_name: str, suffix: str) -> str:
    """给**落盘**用的安全文件名（ASCII 兜底，避免路径穿越/非法字符）。

    中文名会被剥空，此处回退成 "upload<扩展名>"——文件本身以哈希目录存储，
    磁盘上的名字只用于中转，可读性无关紧要。
    """
    cleaned = secure_filename((raw_name or "").replace("\\", "/").split("/")[-1])
    if not cleaned or cleaned == suffix.lstrip("."):
        return f"upload{suffix}"
    return cleaned


@app.post("/api/import")
def import_source():
    ensure_cache_dirs()
    bvid = (request.form.get("bvid") or "").strip()
    upload = request.files.get("file")

    try:
        if bvid:
            full_url = normalize_bilibili_url(bvid)
            metadata, duration = probe_bilibili_metadata(full_url)
            source_id = uuid.uuid4().hex
            bvid_id, aid = extract_bilibili_id(full_url)
            cache_dir = bilibili_cache_dir(bvid_id or f"av{aid}")
            # 提前写占位 state(含标题等元数据)：即使只下载还没截图，也让历史记录能看到该目录
            ensure_placeholder_state(cache_dir, metadata_to_dict(metadata))
            source = {
                "id": source_id,
                "type": "bilibili",
                "url": full_url,
                "metadata": metadata_to_dict(metadata),
                "duration": duration,
                "cache_dir": str(cache_dir),
                "download": {"status": "idle", "message": None},
            }
            state = load_state_json(cache_dir)
            cached_video = find_video_file(cache_dir)
            has_img = _has_images(cache_dir, state)
            has_par = _has_params(state)
            if has_img or has_par:
                # 有可恢复进度(截图或只存过第2步参数)即命中：交前端弹窗选“恢复/从新开始”。
                source["has_cache"] = True
                source["cache"] = {"cache_dir": str(cache_dir), "type": "bilibili", "key": bvid_id or f"av{aid}", "title": metadata.display_title or metadata.raw_title}
                source["params2"] = read_capture_prefs(state)
                if cached_video is not None:
                    source["download"]["status"] = "done"
                    source["video_path"] = str(cached_video)
                if has_img:
                    job_id = make_cached_job(source_id, cache_dir, state)
                    source["restore"] = {"job_id": job_id, "images": restore_images(state), "layout": state.get("layout"), "maxStage": state.get("maxStage")}
                    source["download"]["status"] = "done"
            elif cached_video is not None:
                source["video_path"] = str(cached_video)
                source["download"]["status"] = "done"
            else:
                source["download"]["status"] = "downloading"
                threading.Thread(
                    target=run_bilibili_download,
                    args=(source_id, full_url, cache_dir, bvid_id or f"av{aid}"),
                    daemon=True,
                ).start()
        elif upload and upload.filename:
            raw_name = upload.filename
            # 标题取原始文件名（保住中文）；落盘名用 ASCII 安全版。
            display_title = source_title_from_filename(raw_name)
            original_name = safe_upload_name(raw_name, Path(raw_name).suffix.lower())
            suffix = Path(original_name).suffix.lower()
            source_id = uuid.uuid4().hex
            upload_dir = UPLOADS_DIR / source_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            saved_path = upload_dir / original_name
            upload.save(saved_path)

            if suffix in ALLOWED_IMAGE_EXTENSIONS:
                metadata = build_video_metadata(raw_title=display_title)
                file_hash = hash_file(saved_path)
                cache_dir = image_cache_dir(file_hash)
                cache_dir.mkdir(parents=True, exist_ok=True)
                crops = cache_dir / "crops"
                crops.mkdir(parents=True, exist_ok=True)

                # 缓存主图（供二次命中时原样恢复）。
                master = cache_dir / f"master{suffix}"
                if not master.exists():
                    with open(master, "wb") as mf:
                        mf.write(saved_path.read_bytes())

                # 首导即把整图作为一张 baseline crop 持久化（单图即态）。
                out_name = "import.png"
                baseline = crops / out_name
                prior = load_state_json(cache_dir)
                hit = has_restorable_cache(cache_dir, prior)
                if not baseline.exists():
                    _im = Image.open(str(master)).convert("RGB")
                    _im.save(baseline)
                    _w, _h = _im.size
                    _caps = [{"file": out_name, "url": "x", "t": 0.0, "w": _w, "h": _h}]
                    save_state_json(
                        cache_dir,
                        {
                            "captures": _caps,
                            "images": restore_images({"captures": _caps}),
                            "capture_params": {},
                            "metadata": metadata_to_dict(metadata),
                        },
                    )

                source = {
                    "id": source_id,
                    "type": "image",
                    "path": str(master),
                    "metadata": metadata_to_dict(metadata),
                    "duration": None,
                    "cache_dir": str(cache_dir),
                    "download": {"status": "done", "message": None},
                }

                # 有可恢复截图才真正命中显示（再次导入同一张图时的情形）。
                if hit:
                    state = load_state_json(cache_dir)
                    job_id = make_cached_job(source_id, cache_dir, state)
                    source["restore"] = {
                        "job_id": job_id,
                        "images": restore_images(state),
                        "layout": state.get("layout"),
                        "maxStage": state.get("maxStage"),
                    }
                    source["has_cache"] = True
                    source["cache"] = {"cache_dir": str(cache_dir), "type": "image", "key": file_hash,
                                       "title": metadata.display_title or metadata.raw_title}
            elif suffix in ALLOWED_PDF_EXTENSIONS:
                file_hash = hash_file(saved_path)
                metadata = build_video_metadata(raw_title=display_title)
                cache_dir = pdf_cache_dir(file_hash)
                cache_dir.mkdir(parents=True, exist_ok=True)
                master = cache_dir / "master.pdf"
                if not master.exists():
                    shutil.move(str(saved_path), str(master))
                else:
                    saved_path.unlink(missing_ok=True)

                dpi = read_capture_dpi((load_state_json(cache_dir) or {}).get("pdf_dpi"))
                page_count = pdf_render.pdf_page_count(master)
                source = {
                    "id": source_id,
                    "type": "pdf",
                    "path": str(master),
                    "metadata": metadata_to_dict(metadata),
                    "duration": None,
                    "page_count": page_count,
                    "dpi": dpi,
                    "pdf_dpi": dpi,
                    "cache_dir": str(cache_dir),
                    "download": {"status": "done", "message": None},
                }
                state = load_state_json(cache_dir)
                has_img = _has_images(cache_dir, state)
                has_par = _has_params(state)
                if has_img or has_par:
                    source["has_cache"] = True
                    source["cache"] = {"cache_dir": str(cache_dir), "type": "pdf", "key": file_hash,
                                       "title": metadata.display_title or metadata.raw_title}
                    source["params2"] = read_capture_prefs(state)
                    if has_img:
                        job_id = make_cached_job(source_id, cache_dir, state)
                        source["restore"] = {"job_id": job_id, "images": restore_images(state),
                                             "layout": state.get("layout"), "maxStage": state.get("maxStage")}
            elif suffix in ALLOWED_VIDEO_EXTENSIONS:
                duration = get_video_duration(saved_path)
                metadata = build_video_metadata(raw_title=display_title)
                file_hash = hash_file(saved_path)
                cache_dir = local_cache_dir(file_hash)
                cache_dir.mkdir(parents=True, exist_ok=True)
                # 提前占位 state：导入本地视频即写（即使未截图，历史也可见标题）
                ensure_placeholder_state(cache_dir, metadata_to_dict(metadata))
                cached_video = cache_dir / f"video{suffix}"
                if cached_video.exists():
                    saved_path.unlink(missing_ok=True)
                else:
                    shutil.move(str(saved_path), str(cached_video))
                source = {
                    "id": source_id,
                    "type": "local",
                    "path": str(cached_video),
                    "metadata": metadata_to_dict(metadata),
                    "duration": duration,
                    "cache_dir": str(cache_dir),
                    "download": {"status": "done", "message": None},
                    "video_path": str(cached_video),
                }
                state = load_state_json(cache_dir)
                has_img = _has_images(cache_dir, state)
                has_par = _has_params(state)
                if has_img or has_par:
                    source["has_cache"] = True
                    source["cache"] = {"cache_dir": str(cache_dir), "type": "local", "key": file_hash,
                                       "title": metadata.display_title or metadata.raw_title}
                    source["params2"] = read_capture_prefs(state)
                    if has_img:
                        job_id = make_cached_job(source_id, cache_dir, state)
                        source["restore"] = {"job_id": job_id, "images": restore_images(state), "layout": state.get("layout"), "maxStage": state.get("maxStage")}
            else:
                return json_error("不支持的文件格式，请使用视频（mp4/mov/mkv/webm/m4s）、图片（png/jpg/webp/bmp/gif）或 PDF。")
        else:
            return json_error("请填写 BV 号，或选择本地视频。")

        # 文件导入后内容均已进入持久缓存(bv/local/img)：清理 uploads 里的上传中转。
        # 图片已复制到 img/<hash>/master、视频已 move 到 local/<hash>/；
        # 该 uploads/<source_id> 只是过渡，可一并删除，避免目录越攒越多。
        if "upload_dir" in locals() and upload_dir is not None and upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)

        with STORE_LOCK:
            SOURCES[source_id] = source

        return jsonify(source)
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


@app.get("/api/source/<source_id>/download")
def source_download_status(source_id: str):
    with STORE_LOCK:
        source = SOURCES.get(source_id)
    if source is None:
        return json_error("未知的视频源。", 404)
    return jsonify(source.get("download") or {"status": "idle", "message": None})


@app.post("/api/cache_clear")
def cache_clear():
    """按导入类型清除该源的缓存（截图/裁剪进度；可选整目录删除）。

    参数：type ∈ {bilibili, local, image}；key = bvid | 哈希；
        full=true -> 整缓存目录全部删除（“从新开始”），
        否则只清 crops+state(仍保留下载好的视频等)。
    仅允许删除 CACHE/bv、/local、/img 下的已知目录。
    """
    payload = request.get_json(force=True, silent=True) or {}
    kind = payload.get("type")
    key = (payload.get("key") or "").strip()
    full = bool(payload.get("full"))
    safe_key = Path(key).name if key else ""
    if not safe_key or safe_key != key.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]:
        return json_error("非法 key。", 400)

    if kind == "bilibili":
        cache_dir = bilibili_cache_dir(safe_key)
    elif kind in _CACHE_DIR_BY_KIND:
        cache_dir = _CACHE_DIR_BY_KIND[kind](safe_key)
    else:
        return json_error("未知缓存类型。", 400)

    if not _cache_clearable(cache_dir):
        return json_error("不允许清除该目录。", 403)

    if full:
        import shutil as _sh
        _sh.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)   # 保留空目录让后续照常写入
        return jsonify({"ok": True})

    for old in (cache_dir / "crops").glob("*.png"):
        old.unlink(missing_ok=True)
    # PDF：渲染图也要一并清掉，否则“从新开始”后仍会命中旧 DPI 的渲染缓存。
    for old in (cache_dir / "pages").glob("*.png"):
        old.unlink(missing_ok=True)
    for old in (cache_dir / "pages").glob(".dpi*.txt"):
        old.unlink(missing_ok=True)
    (cache_dir / "state.json").unlink(missing_ok=True)
    # 注意：不清除 SOURCES/JOBS 里的内存 source——用户“从新开始”后仍要沿用同一个
    # source 继续处理当前文件，只是不再命中旧缓存。
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# 历史记录（bv/img/local 持久缓存里可恢复的条目）
# --------------------------------------------------------------------------
_CACHE_KIND_DIR = {
    "bilibili": "bv",
    "image": "img",
    "local": "local",
    "pdf": "pdf",
}
_CACHE_DIR_BY_KIND = {
    "bilibili": bilibili_cache_dir,
    "image": image_cache_dir,
    "local": local_cache_dir,
    "pdf": pdf_cache_dir,
}
# PDF 源在“卡片/截图”层面完全复用图片的那套逻辑（裁剪、去色、分页排版），
# 因此除缓存目录与渲染方式不同外，其余分支都与 image 合并处理。
IMAGE_LIKE_TYPES = {"image", "pdf"}
_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _pick_cover_image(cache_dir: Path, state: Optional[Dict] = None) -> Optional[Path]:
    """挑选用于列表封面的本地 PNG：优先 state.images[0].file 所在 crops，否则 crops 里第一张。"""
    if state is None:
        state = load_state_json(cache_dir)
    crops = cache_dir / "crops"
    name = None
    if state:
        first_img = (state.get("images") or [{}])[0]
        name = first_img.get("file")
        if not name:
            first_cap = (state.get("captures") or [{}])[0]
            name = first_cap.get("file")
    if name:
        p = crops / name
        if p.exists():
            return p
    st = sorted(crops.glob("*.png"), key=lambda q: q.stat().st_ctime if q.exists() else 0)
    st += sorted(crops.glob("import.png"), key=lambda q: 0)  # import already covered
    for cand in sorted(crops.glob("*.png"), key=lambda q: q.name):
        if cand.exists():
            return cand
    return None


def _dir_size(p: "Path") -> int:
    total = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return total


# 第 2 步截图参数默认(旧版缓存无这些时也应回退)  —— 前向兼容
PARAMS2_DEFAULTS = {
    "startSeconds": 0.0,
    "endSeconds": None,
    "sample_every": 2.0,
    "diff_threshold": 0.01,
    "band_half_width": 90,
    "compare_window": 1,
    "tolerance": 300.0,
    "softness": 90.0,
    "coeff_horizontal": 0.7,
    "coeff_vertical": 0.8,
    "stitch_max_width": 600,
    # 抽帧前裁切(第2步裁剪框)归一化比率
    "cropStart": 0.0,
    "cropEnd": 1.0,
    "cropLeft": 0.0,
    "cropRight": 1.0,
    # PDF 逐页渲染分辨率（仅 PDF 源使用；默认 200，可在第 2 步修改）
    "pdf_dpi": PDF_DPI_DEFAULT,
    # PDF 页码区间（1 基闭区间；仅 PDF 源使用）
    "startPage": 1,
    "endPage": None,
}


def read_capture_prefs(state: Optional[dict]) -> dict:
    """把 state.params2 与该类型参数默认合并，缺失字段回退默认(兼容旧版)."""
    prefs = dict(PARAMS2_DEFAULTS)
    if state and isinstance(state.get("params2"), dict):
        for k, v in state["params2"].items():
            if k in prefs and v is not None:
                prefs[k] = v
    return prefs


def ensure_placeholder_state(cache_dir: Path, metadata: Dict[str, Any], params: Optional[dict] = None) -> bool:
    """若该 cache 目录还没有 state，写占位 state 并(可选)埋伏 params2(第2步可恢复)."""
    pfile = cache_dir / "state.json"
    if pfile.exists():
        return False
    save_state_json(
        cache_dir,
        {
            "captures": [],
            "images": [],
            "capture_params": {},
            "metadata": metadata,
            "layout": None,
            "maxStage": None,
            **({"params2": params} if params else {}),
        },
    )
    return True


def _entry_title(state: Optional[Dict]) -> str:
    if not state:
        return ""
    md = state.get("metadata") or {}
    return md.get("display_title") or md.get("raw_title") or ""


def _history_entries():
    """遍历 bv/img/local 中所有子目录，每条一律作为一条历史。

    该功能用于“管理本地存储占用”，因此不能像按 state.json 存在与否来筛——
    即使只下载好视频、还没走到截图/写 state，也应列出（那常是最占空间的）。
    """
    out = []
    for kind, sub in _CACHE_KIND_DIR.items():
        base = CACHE_DIR / sub
        if not base.exists():
            continue
        for cd in sorted(base.iterdir()):
            if not cd.is_dir():
                continue
            key = cd.name
            state = load_state_json(cd)  # 可能为空
            meta = (state or {}).get("metadata") or {}
            title = _entry_title(state) or key
            chnl = meta.get("channel") or ""
            kind_label = {"bilibili": "B站视频", "image": "图片", "local": "本地视频", "pdf": "PDF"}.get(kind, kind)
            mg = (state or {}).get("maxStage") if state else None

            def _playable(directory: Path, exts=(".mp4", ".mkv", ".webm", ".mov", ".m4s", ".m4s")):
                for p in directory.iterdir():
                    if p.is_file() and p.name.lower().endswith(exts):
                        return p
                return None

            resumable = False
            if kind in ("local", "bilibili"):
                # 能提供可播放文件即可继续(无论是否有截图 state)
                resumable = bool(_playable(cd)) or bool(state and state.get("captures"))
            elif kind == "image":
                master = next((p for p in cd.iterdir()
                               if p.is_file() and p.name.lower().startswith("master")), None)
                resumable = bool(master) or bool(state and state.get("captures"))
            elif kind == "pdf":
                # PDF：master.pdf 在就能重新渲染 → 可恢复；渲染图缺失时重导会重渲。
                master = (cd / "master.pdf")
                resumable = master.exists() or bool(state and state.get("captures"))
            out.append({
                "kind": kind,          # bilibili|image|local
                "label": kind_label,
                "key": key,            # bvid/hash
                "title": title,
                "channel": chnl,
                "mtime": float(cd.stat().st_mtime) if cd.exists() else 0.0,
                "size": _dir_size(cd),
                "resumable": resumable,
                "stage": mg or 0,
            })
    out.sort(key=lambda e: e["mtime"], reverse=True)
    return out


@app.get("/api/history")
def api_history():
    return jsonify({"entries": _history_entries()})


import time as _time  # noqa

_BILI_COVER_CACHE = {}      # bvid -> (ts, bytes)
_BILI_COVER_TTL = 600      # 秒


def _bilibili_real_cover(key: str) -> Optional[bytes]:
    """拉取 B 站视频真实封面(pic)到内存(短 TTL)。失败返回 None。"""
    import time as _t
    now = _t.time()
    cached = _BILI_COVER_CACHE.get(key)
    if cached and now - cached[0] < _BILI_COVER_TTL:
        return cached[1]
    try:
        import bili as _bili
        url = "https://api.bilibili.com/x/web-interface/view?bvid=" + key
        r = _bili._session.get(url, timeout=8)
        r.raise_for_status()
        pic = (r.json().get("data") or {}).get("pic")
        if not pic:
            return None
        pr = _bili._session.get(pic, timeout=8,
                                headers={"Referer": "https://www.bilibili.com/"})
        pr.raise_for_status()
        content = pr.content
        if content:
            _BILI_COVER_CACHE[key] = (now, content)
            if len(_BILI_COVER_CACHE) > 200:
                _BILI_COVER_CACHE.clear()
            return content
    except Exception:
        pass
    return None


@app.get("/api/history/cover")
def api_history_cover():
    kind = request.args.get("kind") or ""
    key = request.args.get("key") or ""
    safe_key = Path(key).name if key else ""
    if kind not in _CACHE_DIR_BY_KIND or not safe_key:
        return json_error("参数错误。", 400)
    cache_dir = _CACHE_DIR_BY_KIND[kind](safe_key)
    if not _cache_clearable(cache_dir):
        return json_error("不允许访问该目录。", 403)

    # B 站用真实封面(pic)优先；失败或非 bilibili 退回本地首帧。
    if kind == "bilibili":
        real = _bilibili_real_cover(safe_key)
        if real:
            from flask import Response
            return Response(real, mimetype="image/jpeg")

    cover = _pick_cover_image(cache_dir)
    if not cover:
        return json_error("没有封面。", 404)
    return send_file(str(cover), mimetype="image/png")


@app.post("/api/history/delete")
def api_history_delete():
    """多选/全选删除：删除选中的 cache 目录(bv/img/local 之一)。"""
    payload = request.get_json(force=True, silent=True) or {}
    items = payload.get("items") or []
    removed = 0
    for it in items:
        kind = (it or {}).get("kind")
        key = (it or {}).get("key") or ""
        safe_key = Path(key).name if isinstance(key, str) else ""
        if kind not in _CACHE_DIR_BY_KIND or not safe_key:
            continue
        cache_dir = _CACHE_DIR_BY_KIND[kind](safe_key)
        if not _cache_clearable(cache_dir):
            continue
        try:
            import shutil as _sh
            with STORE_LOCK:
                for sid, src in list(SOURCES.items()):
                    if Path(str(src.get("cache_dir") or "")).resolve() == cache_dir.resolve():
                        SOURCES.pop(sid, None)
                for jid, job in list(JOBS.items()):
                    if Path(str(job.get("cache_dir") or "")).resolve() == cache_dir.resolve():
                        JOBS.pop(jid, None)
            _sh.rmtree(cache_dir, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    return jsonify({"removed": removed})


@app.post("/api/history/restore")
def api_history_restore():
    """按 cache 类型/键重建 source 返回。

    有 state(可恢复截图/裁剪) 时带 .restore；否则(如只下载好视频还没截图)只返回
    基础 source(前端当作“继续/新开始”处理，走到截图步骤)。此功能管理本地占用，
    故“无截图但有原文件”也能打开继续。
    """
    payload = request.get_json(force=True, silent=True) or {}
    kind = payload.get("kind") or ""
    key = (payload.get("key") or "").strip()
    safe_key = Path(key).name if key else ""
    if kind not in _CACHE_DIR_BY_KIND or not safe_key:
        return json_error("参数错误。", 400)
    cache_dir = _CACHE_DIR_BY_KIND[kind](safe_key)
    if not _cache_clearable(cache_dir):
        return json_error("不允许访问该目录。", 403)

    state = load_state_json(cache_dir)
    has_images = bool(state and (state.get("captures") or state.get("images")))
    meta = (state or {}).get("metadata") or {}

    source_id = uuid.uuid4().hex
    if kind == "bilibili":
        fid = next((p for p in cache_dir.iterdir()
                    if p.is_file() and p.name.lower().endswith((".mp4", ".mkv", ".webm", ".mov", ".m4s"))), None)
        try:
            dl = get_video_duration(fid) if fid is not None else None
        except Exception:
            dl = None
        source = {
            "id": source_id, "type": "bilibili",
            "url": meta.get("source_url") or f"https://www.bilibili.com/video/{safe_key}",
            "metadata": meta,
            "duration": dl,
            "cache_dir": str(cache_dir),
            "download": {"status": "done", "message": None},
        }
        if fid:
            source["video_path"] = str(fid)
    elif kind in ("image", "pdf"):
        master = next((p for p in cache_dir.iterdir()
                       if p.is_file() and p.name.lower().startswith("master")), None)
        if kind == "pdf":
            if master is None:
                return json_error("PDF 原文件缺失。", 404)
            state = load_state_json(cache_dir) or {}
            source = {
                "id": source_id, "type": "pdf",
                "path": str(master),
                "metadata": meta, "duration": None,
                "page_count": state.get("page_count"),
                "dpi": read_capture_dpi(state.get("pdf_dpi")),
                "pdf_dpi": read_capture_dpi(state.get("pdf_dpi")),
                "cache_dir": str(cache_dir),
                "download": {"status": "done", "message": None},
            }
        else:
            source = {
                "id": source_id, "type": "image",
                "path": str(master) if master else (next((p for p in cache_dir.iterdir()
                                                          if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")), None)),
                "metadata": meta, "duration": None,
                "cache_dir": str(cache_dir),
                "download": {"status": "done", "message": None},
            }
            if not source["path"]:
                return json_error("图片原文件缺失。", 404)
            if not has_images:
                # 无截图态：走 /start_image_capture 前前端会直接读原图
                has_images = False
    else:  # local
        vid = next((p for p in cache_dir.iterdir()
                    if p.is_file() and p.name.lower().endswith((".mp4", ".mkv", ".webm", ".mov", ".m4s"))), None)
        if not vid:
            return json_error("本地视频文件缺失。", 404)
        try:
            dl = get_video_duration(vid)
        except Exception:
            dl = None
        source = {
            "id": source_id, "type": "local", "path": str(vid),
            "metadata": meta, "duration": dl, "cache_dir": str(cache_dir),
            "download": {"status": "done", "message": None}, "video_path": str(vid),
        }

    if has_images:
        job_id = make_cached_job(source_id, cache_dir, state)
        source["restore"] = {
            "job_id": job_id,
            "images": restore_images(state),
            "layout": (state or {}).get("layout"),
            "maxStage": (state or {}).get("maxStage"),
        }
    # 截图参数(第2步)一并带出（含占位/旧版无则回退默认）
    source["params2"] = read_capture_prefs(state)
    with STORE_LOCK:
        SOURCES[source_id] = source
    return jsonify(source)


@app.post("/api/save_capture_prefs")
def api_save_capture_prefs():
    """第 2 步(截图)参数变动即存——无需已生成截图，让“截图前”也能恢复进度。"""
    payload = request.get_json(force=True, silent=True) or {}
    source_id = payload.get("source_id")
    if not source_id:
        return json_error("缺少 source_id。", 400)
    with STORE_LOCK:
        src = SOURCES.get(source_id)
    if not src:
        return json_error("未知的视频源。", 404)
    cache_dir_str = src.get("cache_dir")
    if not cache_dir_str:
        return json_error("该源无缓存目录。", 409)
    cache_dir = Path(cache_dir_str)

    allowed = set(PARAMS2_DEFAULTS.keys())
    params = (payload.get("params") or {})
    clean = {k: v for k, v in params.items() if k in allowed}
    state = load_state_json(cache_dir) or {
        "captures": [], "images": [], "capture_params": {},
        "metadata": src.get("metadata") or {},
    }
    state["params2"] = clean
    # PDF 的 DPI 也单独存一份：导入/恢复时无需解 params2 就能拿到渲染分辨率。
    if "pdf_dpi" in clean:
        state["pdf_dpi"] = read_capture_dpi(clean["pdf_dpi"])
        src["pdf_dpi"] = state["pdf_dpi"]
    if "maxStage" not in state or state.get("maxStage") in (None, 0):
        state["maxStage"] = 2
    save_state_json(cache_dir, state)
    return jsonify({"ok": True})


@app.post("/api/save_state")
def save_state():
    """Persist the frontend adjustment state (images) into the job's cache dir."""
    payload = request.get_json(force=True, silent=True) or {}
    try:
        job_id = payload.get("job_id")
        with STORE_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            return json_error("未知的任务。", 404)
        cache_dir_str = job.get("cache_dir")
        if not cache_dir_str:
            return json_error("该任务没有缓存目录。", 409)
        cache_dir = Path(cache_dir_str)
        state = load_state_json(cache_dir) or {}
        state.setdefault("images", [])
        if payload.get("images") is not None:
            # 完整列表（结构性变更：分割/合并/插入/排序/删除等）。
            state["images"] = payload["images"]
        elif payload.get("image") is not None:
            # 单张图片的增量补丁（裁剪/小节线/隐藏）。
            patch = payload["image"]
            target = next((img for img in state["images"] if img.get("file") == patch.get("file")), None)
            if target is None:
                state["images"].append(patch)
            else:
                if "crop" in patch:
                    target["crop"] = patch["crop"]
                if "measures" in patch:
                    target["measures"] = patch["measures"]
                if "hidden" in patch:
                    target["hidden"] = patch["hidden"]
        if payload.get("layout") is not None:
            state["layout"] = payload["layout"]
        if payload.get("maxStage") is not None:
            state["maxStage"] = payload["maxStage"]
        save_state_json(cache_dir, state)
        return jsonify({"ok": True})
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/bilibili/login")
def bilibili_login_start():
    global BILIBILI_LOGIN_TOKEN

    with BILIBILI_LOGIN_LOCK:
        if BILIBILI_LOGIN["status"] == "running":
            return jsonify(dict(BILIBILI_LOGIN))

    token = uuid.uuid4().hex
    with BILIBILI_LOGIN_LOCK:
        BILIBILI_LOGIN_TOKEN = token
        BILIBILI_LOGIN.update(status="running", qr=None, message=None)

    threading.Thread(target=run_bilibili_login_worker, args=(token,), daemon=True).start()

    with BILIBILI_LOGIN_LOCK:
        return jsonify(dict(BILIBILI_LOGIN))


@app.get("/api/bilibili/login")
def bilibili_login_status():
    with BILIBILI_LOGIN_LOCK:
        snapshot = dict(BILIBILI_LOGIN)
    # cookie.txt is the source of truth for "logged in", not the in-memory
    # process status (which can stay "success" after the cookie is removed).
    if bilibili_cookie_path().exists():
        snapshot.update(status="success", qr=None, message="已登录。")
    elif snapshot["status"] == "success":
        snapshot.update(status="idle", qr=None, message=None)
    return jsonify(snapshot)


@app.post("/api/bilibili/logout")
def bilibili_logout():
    global BILIBILI_LOGIN_TOKEN

    with BILIBILI_LOGIN_LOCK:
        BILIBILI_LOGIN_TOKEN = None
        BILIBILI_LOGIN.update(status="idle", qr=None, message=None)

    cookie_path = bilibili_cookie_path()
    if cookie_path.exists():
        cookie_path.unlink()

    return jsonify({"status": "idle", "qr": None, "message": None})


@app.post("/api/preview")
def preview_source():
    ensure_cache_dirs()
    data = request.get_json(force=True, silent=True) or {}
    try:
        source = source_or_error(data.get("source_id"))
        time_sec = parse_float(data.get("time"), "time", 0.0)
        if time_sec < 0:
            raise ValueError("时间必须大于等于 0")

        # PDF 源：time 是页号（1 基），预览 = 该页渲染图缩成 jpg（与视频预览同一套返回结构）。
        if source["type"] == "pdf":
            page_no = max(1, int(round(time_sec)) or 1)
            dpi = read_capture_dpi(data.get("dpi") if data.get("dpi") else source.get("pdf_dpi"))
            total = pdf_render.pdf_page_count(Path(source["path"]))
            page_no = min(page_no, total)
            preview_name = f"{source['id']}_p{page_no}_{uuid.uuid4().hex[:8]}.jpg"
            preview_path = PREVIEWS_DIR / preview_name
            image = pdf_render.render_pdf_page(Path(source["path"]), page_no - 1, dpi)
            if image.width > 1400:
                ratio = 1400 / image.width
                image = image.resize((1400, max(1, int(image.height * ratio))), RESAMPLE)
            image.convert("RGB").save(preview_path, quality=88)
            image.close()
            return jsonify({
                "preview_url": f"/api/previews/{preview_name}",
                "duration": None,
                "quality": None,
                "page": page_no,
                "page_count": total,
            })

        preview_name = f"{source['id']}_{int(time_sec * 1000)}_{uuid.uuid4().hex[:8]}.jpg"
        preview_path = PREVIEWS_DIR / preview_name

        resp_quality = None
        if source["type"] == "bilibili":
            cached = Path(source.get("video_path") or "")
            base_dir = Path(source.get("cache_dir")) if source.get("cache_dir") else cached.parent
            if cached.exists():
                video_path = cached
            else:
                # 预览也用“最终下载的同一清晰度”：缓存目录下载整份（非 low 预览副本）
                video_path = download_bilibili_video(source["url"], base_dir)
                source["video_path"] = str(video_path)
            save_video_frame(video_path, preview_path, time_sec=time_sec)
            # 诚实清晰度：优先 .dlqh(实测像素高度)；否则退 .dlqn(请求档位)
            dlh = base_dir / ".dlqh.txt"
            if dlh.exists():
                try:
                    hv = dlh.read_text(encoding="utf-8").strip()
                    if hv:
                        resp_quality = "px:" + hv
                except OSError:
                    pass
            if not resp_quality:
                dl = base_dir / ".dlqn.txt"
                if dl.exists():
                    try:
                        qv = dl.read_text(encoding="utf-8").strip()
                        if qv:
                            resp_quality = "q:" + qv
                    except OSError:
                        pass
        else:
            save_video_frame(Path(source["path"]), preview_path, time_sec=time_sec)

        return jsonify(
            {
                "preview_url": f"/api/previews/{preview_name}",
                "duration": source.get("duration"),
                "quality": resp_quality,
            }
        )
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/captures")
def start_captures():
    ensure_cache_dirs()
    payload = request.get_json(force=True, silent=True) or {}
    try:
        source = source_or_error(payload.get("source_id"))
        if source["type"] in IMAGE_LIKE_TYPES:
            return start_image_capture(source, payload)
        start_sec = parse_float(payload.get("start"), "start", 0.0)
        end_sec = parse_optional_float(payload.get("end"), "end")
        if start_sec < 0:
            return json_error("开始时间必须大于等于 0。")
        if end_sec is not None and end_sec <= start_sec:
            return json_error("结束时间必须大于开始时间。")
        validate_crop_ratios(
            parse_float(payload.get("crop_y_start"), "crop_y_start", 0.0),
            parse_float(payload.get("crop_y_end"), "crop_y_end", 1),
        )

        job_id = uuid.uuid4().hex
        # 重新生成为同一 source，取代旧同源已完成 job（进行中的保留），清掉旧 preview。
        evict_superseded_jobs(source["id"], keep_job_id=job_id)
        cleanup_source_transient(source["id"])
        with STORE_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "source_id": payload.get("source_id"),
                "status": "queued",
                "phase": "queued",
                "logs": [],
                "stats": None,
                "captures": [],
                "metadata": None,
                "error": None,
                "pdf_url": None,
                "created_at": time.time(),
                "updated_at": time.time(),
            }

        thread = threading.Thread(
            target=run_capture_job,
            args=(job_id, payload),
            daemon=True,
        )
        thread.start()
        return jsonify({"job_id": job_id})
    except Exception as exc:
        return json_error(str(exc))


@app.get("/api/captures/<job_id>/<path:filename>")
def capture_file(job_id: str, filename: str):
    return send_from_directory(job_crops_dir(job_id), filename, as_attachment=False)


@app.get("/api/capture_preview/<job_id>/<path:filename>")
def capture_preview(job_id: str, filename: str):
    """按当前去色/反色/配色设置实时返回处理后的单张截图。

    流程：原图 → (可选)按音符颜色二值化 → (可选)染色为文字/背景色 → (可选)反色。
    """
    crops_dir = job_crops_dir(job_id)
    src = crops_dir / filename
    if not src.exists():
        return json_error("未知的截图。", 404)

    invert = parse_bool(request.args.get("invert"))
    binarize = parse_bool(request.args.get("binarize"))

    note_rgb = parse_optional_note_color(request.args.get("note_color"))
    tolerance = parse_float(request.args.get("tolerance"), "tolerance", 300.0)
    softness = parse_float(request.args.get("softness"), "softness", 90.0)

    try:
        img = Image.open(src).convert("RGB")
        if binarize and note_rgb is not None:
            img = extract_note_mask(img, note_rgb, tolerance, softness).convert("RGB")
        if invert:
            img = ImageOps.invert(img)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    except Exception as exc:
        return json_error(str(exc), 500)


def _parse_layout_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    margin = int(parse_float(payload.get("margin"), "margin", 40))
    spacing = int(parse_float(payload.get("spacing"), "spacing", 25))
    title_spacing = int(parse_float(payload.get("title_spacing"), "title_spacing", 130))
    scale = parse_float(payload.get("scale"), "scale", 1.0)
    scale = max(0.05, min(10.0, scale))
    bg_color = (payload.get("bg_color") or "white").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}|[a-zA-Z]+", bg_color):
        bg_color = "white"
    text_color = parse_hex_color(payload.get("text_color"), "#181818")
    binarize = parse_bool(payload.get("binarize"))
    invert = parse_bool(payload.get("invert"))
    note_rgb = parse_optional_note_color(payload.get("note_color"))
    tolerance = parse_float(payload.get("tolerance"), "tolerance", 300.0)
    softness = parse_float(payload.get("softness"), "softness", 90.0)
    orientation = payload.get("orientation") or "portrait"
    if orientation not in ("portrait", "landscape"):
        orientation = "portrait"
    align = payload.get("align") or "left"
    if align not in ("left", "center", "right"):
        align = "left"
    valign = payload.get("valign") or "top"
    if valign not in ("top", "center", "bottom"):
        valign = "top"
    title = (payload.get("title") or "").strip()
    title_lines = [ln for ln in title.splitlines() if ln.strip()]
    return {
        "margin": margin,
        "spacing": spacing,
        "title_spacing": title_spacing,
        "scale": scale,
        "bg_color": bg_color,
        "text_color": text_color,
        "binarize": binarize,
        "invert": invert,
        "note_rgb": note_rgb,
        "tolerance": tolerance,
        "softness": softness,
        "orientation": orientation,
        "align": align,
        "valign": valign,
        "title_lines": title_lines,
    }


def prepare_final_strips(
    job_id: str, payload: Dict[str, Any], opts: Dict[str, Any]
) -> tuple[Path, int]:
    """把每张截图按小节线拆成竖条、缩放并二值化/反色，写到 final 目录。

    返回 (final_dir, strip_count)。
    """
    crops_dir = job_crops_dir(job_id)
    final_dir = RUNS_DIR / job_id / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    for old in final_dir.glob("*.png"):
        old.unlink()

    scale = opts["scale"]
    index = 0
    for item in payload.get("images") or []:
        src_path = crops_dir / item.get("file", "")
        if not src_path.exists():
            continue
        img = Image.open(src_path).convert("RGB")
        iw, ih = img.size
        crop = item.get("crop") or {}
        c_l = max(0.0, min(1.0, float(crop.get("l", 0.0))))
        c_r = max(c_l, min(1.0, float(crop.get("r", 1.0))))
        c_t = max(0.0, min(1.0, float(crop.get("t", 0.0))))
        c_b = max(c_t, min(1.0, float(crop.get("b", 1.0))))
        y0 = int(round(ih * c_t))
        y1 = int(round(ih * c_b))
        measures = [float(m) for m in (item.get("measures") or [])]
        bounds = [c_l] + sorted(m for m in measures if c_l < m < c_r) + [c_r]
        bounds = sorted(set(bounds))
        for i in range(len(bounds) - 1):
            x0 = int(round(iw * bounds[i]))
            x1 = int(round(iw * bounds[i + 1]))
            if x1 - x0 < 1:
                continue
            strip = img.crop((x0, y0, x1, y1))
            if scale != 1.0:
                nw = max(1, int(round(strip.width * scale)))
                nh = max(1, int(round(strip.height * scale)))
                strip = strip.resize((nw, nh), RESAMPLE)
            if opts["binarize"] and opts["note_rgb"] is not None:
                strip = extract_note_mask(strip, opts["note_rgb"], opts["tolerance"], opts["softness"]).convert("RGB")
            if opts["invert"]:
                strip = ImageOps.invert(strip)
            strip.save(final_dir / f"final_{index:04d}.png")
            index += 1
    return final_dir, index


@app.post("/api/pdf")
def build_pdf():
    ensure_cache_dirs()
    payload = request.get_json(force=True, silent=True) or {}
    try:
        job_id = payload.get("job_id")
        with STORE_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            return json_error("未知的任务。", 404)

        source = SOURCES.get(job.get("source_id"), {})
        source_metadata = metadata_from_dict(source.get("metadata", {}))
        opts = _parse_layout_payload(payload)

        final_dir, index = prepare_final_strips(job_id, payload, opts)
        if index == 0:
            return json_error("没有可导出的截图。")

        output_pdf = RUNS_DIR / job_id / safe_pdf_name(payload.get("output") or "tablatura.pdf")
        page_count = build_pdf_from_images(
            final_dir,
            output_pdf,
            margin=opts["margin"],
            spacing=opts["spacing"],
            bg_color=opts["bg_color"],
            text_color=opts["text_color"],
            orientation=opts["orientation"],
            align=opts["align"],
            valign=opts["valign"],
            fit_width=True,
            title_lines=opts["title_lines"],
            title_spacing=opts["title_spacing"],
            source_url=source_metadata.source_url,
        )

        update_job(job_id, pdf_name=output_pdf.name, pdf_url=f"/api/jobs/{job_id}/pdf")
        return jsonify({
            "pdf_url": f"/api/jobs/{job_id}/pdf",
            "pdf_name": output_pdf.name,
            "page_count": page_count,
        })
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/long_image")
def build_long_image_route():
    ensure_cache_dirs()
    payload = request.get_json(force=True, silent=True) or {}
    try:
        job_id = payload.get("job_id")
        with STORE_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            return json_error("未知的任务。", 404)

        source = SOURCES.get(job.get("source_id"), {})
        source_metadata = metadata_from_dict(source.get("metadata", {}))
        opts = _parse_layout_payload(payload)

        final_dir, index = prepare_final_strips(job_id, payload, opts)
        if index == 0:
            return json_error("没有可导出的截图。")

        output_png = RUNS_DIR / job_id / safe_pdf_name(payload.get("output")).replace(".pdf", ".png")
        build_long_image(
            final_dir,
            output_png,
            page_width=1654,
            margin=opts["margin"],
            spacing=opts["spacing"],
            bg_color=opts["bg_color"],
            text_color=opts["text_color"],
            align=opts["align"],
            valign=opts["valign"],
            fit_width=True,
            title_lines=opts["title_lines"],
            title_spacing=opts["title_spacing"],
            source_url=source_metadata.source_url,
        )
        update_job(job_id, long_name=output_png.name)
        return jsonify({
            "long_url": f"/api/jobs/{job_id}/long_image",
            "long_name": output_png.name,
        })
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/detect_measures")
def detect_measures():
    ensure_cache_dirs()
    payload = request.get_json(force=True, silent=True) or {}
    try:
        job_id = payload.get("job_id")
        with STORE_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            return json_error("未知的任务。", 404)
        crops_dir = job_crops_dir(job_id)
        files = payload.get("files") or []
        coefficient_horizontal = parse_float(
            payload.get("coefficient_horizontal"), "coefficient_horizontal", 0.7
        )
        coefficient_vertical = parse_float(
            payload.get("coefficient_vertical"), "coefficient_vertical", 0.8
        )
        note_rgb = parse_optional_note_color(payload.get("note_color"))
        tolerance = parse_float(payload.get("tolerance"), "tolerance", 300.0)
        softness = parse_float(payload.get("softness"), "softness", 90.0)
        results: Dict[str, List[float]] = {}
        for name in files:
            src = crops_dir / name
            if not src.exists():
                continue
            img = Image.open(src).convert("RGB")
            w = img.width
            cleaned = preprocess_for_detection(img, note_rgb, tolerance, softness)
            bars = detect_measure_barlines(
                cleaned,
                coefficient_horizontal=coefficient_horizontal,
                coefficient_vertical=coefficient_vertical,
            )
            results[name] = [round(b / w, 5) for b in bars]
        return jsonify({"measures": results})
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/stitch")
def stitch_offsets():
    ensure_cache_dirs()
    payload = request.get_json(force=True, silent=True) or {}
    try:
        job_id = payload.get("job_id")
        with STORE_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            return json_error("未知的任务。", 404)
        crops_dir = job_crops_dir(job_id)
        files = payload.get("files") or []
        coefficient_horizontal = parse_float(
            payload.get("coefficient_horizontal"), "coefficient_horizontal", 0.7
        )
        coefficient_vertical = parse_float(
            payload.get("coefficient_vertical"), "coefficient_vertical", 0.8
        )
        max_width = int(parse_float(payload.get("max_width"), "max_width", 600))
        note_rgb = parse_optional_note_color(payload.get("note_color"))
        tolerance = parse_float(payload.get("tolerance"), "tolerance", 300.0)
        softness = parse_float(payload.get("softness"), "softness", 90.0)
        images: List[Image.Image] = []
        for name in files:
            src = crops_dir / name
            if not src.exists():
                continue
            images.append(Image.open(src).convert("RGB"))
        seams = (
            compute_stitch_seams(
                images,
                max_width=max_width,
                coefficient_horizontal=coefficient_horizontal,
                coefficient_vertical=coefficient_vertical,
                note_rgb=note_rgb,
                tolerance=tolerance,
                softness=softness,
            )
            if len(images) >= 2
            else []
        )
        return jsonify({
            "seams": [
                [round(s[0], 5), round(s[1], 5)] for s in seams
            ]
        })
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/import_image")
def import_image():
    ensure_cache_dirs()
    job_id = request.form.get("job_id")
    upload = request.files.get("file")
    try:
        if not job_id:
            return json_error("缺少 job_id。")
        with STORE_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            return json_error("未知的任务。", 404)
        if not upload or not upload.filename:
            return json_error("没有收到图片。")
        original_name = secure_filename(upload.filename)
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            return json_error("不支持的图片格式。")
        crops_dir = job_crops_dir(job_id)
        crops_dir.mkdir(parents=True, exist_ok=True)
        out_name = f"img_{uuid.uuid4().hex[:10]}{suffix}"
        upload.save(crops_dir / out_name)
        with Image.open(crops_dir / out_name) as im:
            w, h = im.size
        return jsonify({
            "file": out_name,
            "url": f"/api/captures/{job_id}/{out_name}",
            "w": w,
            "h": h,
        })
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/insert_captures")
def insert_captures():
    ensure_cache_dirs()
    payload = request.get_json(force=True, silent=True) or {}
    try:
        job_id = payload.get("job_id")
        with STORE_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            return json_error("未知的任务。", 404)

        video_path_str = job.get("video_path")
        capture_params = job.get("capture_params") or {}
        if not video_path_str or not Path(video_path_str).exists():
            return json_error("视频源不可用，无法插入。", 409)

        t_start = parse_float(payload.get("t_start"), "t_start")
        t_end = parse_float(payload.get("t_end"), "t_end")
        if t_end <= t_start:
            return json_error("t_end 必须大于 t_start。")

        sample_every = parse_float(payload.get("sample_every"), "sample_every", 0.5)
        eps = max(sample_every, 0.1)
        start = t_start + eps
        end = t_end - eps
        if end <= start:
            return jsonify({"captures": []})

        crops_dir = job_crops_dir(job_id)
        crops_dir.mkdir(parents=True, exist_ok=True)

        band_half_width = int(capture_params.get("band_half_width", 90))
        min_band_pixels = int(capture_params.get("min_band_pixels", 20))
        target_tolerance = int(capture_params.get("target_tolerance", 48))
        diff_threshold = float(capture_params.get("diff_threshold", 0.010))
        compare_window = int(capture_params.get("compare_window", 1))
        crop_y_start = float(capture_params.get("crop_y_start", 0.0))
        crop_y_end = float(capture_params.get("crop_y_end", 1))
        crop_x_start = float(capture_params.get("crop_x_start", 0.0))
        crop_x_end = float(capture_params.get("crop_x_end", 1.0))

        with STORE_LOCK:
            job_captures = list(job.get("captures", []))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_crops = Path(tmp) / "crops"
            stats = extract_unique_crops(
                video_path=Path(video_path_str),
                crops_dir=tmp_crops,
                sample_every_sec=sample_every,
                crop_y_start_ratio=crop_y_start,
                crop_y_end_ratio=crop_y_end,
                crop_x_start_ratio=crop_x_start,
                crop_x_end_ratio=crop_x_end,
                diff_threshold=diff_threshold,
                compare_window=compare_window,
                start_sec=start,
                end_sec=end,
                save_cleaned=False,
                band_half_width=band_half_width,
                min_band_pixels=min_band_pixels,
                target_tolerance=target_tolerance,
            )
            if stats.captures_kept == 0:
                return jsonify({"captures": []})

            times = {}
            times_path = tmp_crops / "times.json"
            if times_path.exists():
                try:
                    with times_path.open("r", encoding="utf-8") as fh:
                        times = json.load(fh)
                except (OSError, ValueError):
                    times = {}

            new_captures = []
            for p in sorted(tmp_crops.glob("*.png")):
                t = float(times.get(p.name, 0.0))
                out_name = f"ins_{uuid.uuid4().hex[:10]}_{p.name}"
                try:
                    with Image.open(p) as img:
                        w, h = img.size
                except Exception:
                    continue
                (crops_dir / out_name).write_bytes(p.read_bytes())
                new_captures.append(
                    {
                        "file": out_name,
                        "url": f"/api/captures/{job_id}/{out_name}",
                        "t": t,
                        "w": w,
                        "h": h,
                    }
                )

        insert_index = int(parse_float(payload.get("index"), "index", len(job_captures)))
        insert_index = max(0, min(insert_index, len(job_captures)))
        job_captures[insert_index:insert_index] = new_captures
        update_job(
            job_id,
            captures=job_captures,
            updated_at=time.time(),
        )

        return jsonify({"captures": new_captures})
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/split_image")
def split_image():
    ensure_cache_dirs()
    payload = request.get_json(force=True, silent=True) or {}
    try:
        job_id = payload.get("job_id")
        with STORE_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            return json_error("未知的任务。", 404)
        crops_dir = job_crops_dir(job_id)
        src = crops_dir / payload.get("file", "")
        if not src.exists():
            return json_error("未知的截图。", 404)
        img = Image.open(src).convert("RGB")
        w, h = img.size
        if h < MIN_SPLIT_PX * 2:
            return json_error("图片高度不足，无法继续分割。", 400)
        y = parse_float(payload.get("y"), "y", 0.5)
        cut = int(round(h * y))
        cut = max(MIN_SPLIT_PX, min(h - MIN_SPLIT_PX, cut))
        top = img.crop((0, 0, w, cut))
        bottom = img.crop((0, cut, w, h))
        stem = Path(payload.get("file", "x")).stem
        out_top = f"sp_{stem}_top_{uuid.uuid4().hex[:6]}.png"
        out_bottom = f"sp_{stem}_bot_{uuid.uuid4().hex[:6]}.png"
        top.save(crops_dir / out_top)
        bottom.save(crops_dir / out_bottom)
        return jsonify({
            "parts": [
                {"file": out_top, "url": f"/api/captures/{job_id}/{out_top}", "w": top.width, "h": top.height},
                {"file": out_bottom, "url": f"/api/captures/{job_id}/{out_bottom}", "w": bottom.width, "h": bottom.height},
            ]
        })
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/merge_image")
def merge_image():
    ensure_cache_dirs()
    payload = request.get_json(force=True, silent=True) or {}
    try:
        job_id = payload.get("job_id")
        with STORE_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            return json_error("未知的任务。", 404)
        crops_dir = job_crops_dir(job_id)
        top_path = crops_dir / payload.get("top", "")
        bottom_path = crops_dir / payload.get("bottom", "")
        if not top_path.exists() or not bottom_path.exists():
            return json_error("未知的截图。", 404)
        top_img = Image.open(top_path).convert("RGB")
        bottom_img = Image.open(bottom_path).convert("RGB")
        tw, th = top_img.size
        bw, bh = bottom_img.size
        w = max(tw, bw)
        h = th + bh
        merged = Image.new("RGB", (w, h), (255, 255, 255))
        merged.paste(top_img, (0, 0))
        merged.paste(bottom_img, (0, th))
        stem = Path(payload.get("top", "x")).stem
        out_name = f"mg_{stem}_{uuid.uuid4().hex[:6]}.png"
        merged.save(crops_dir / out_name)
        return jsonify({
            "file": out_name,
            "url": f"/api/captures/{job_id}/{out_name}",
            "w": w,
            "h": h,
        })
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


@app.get("/api/source_image/<source_id>")
def source_image(source_id: str):
    with STORE_LOCK:
        source = SOURCES.get(source_id)
    if source is None or source.get("type") not in IMAGE_LIKE_TYPES:
        return json_error("未知的图片源。", 404)
    if source.get("type") == "pdf":
        return json_error("PDF 源请使用 /api/source_page 预览。", 400)
    return send_file(source["path"])


@app.get("/api/source_info/<source_id>")
def source_info(source_id: str):
    """源的补充信息：PDF 的页数 / 当前 DPI（前端翻页与 DPI 输入框用）。"""
    with STORE_LOCK:
        source = SOURCES.get(source_id)
    if source is None:
        return json_error("未知的源。", 404)
    info = {"type": source.get("type")}
    if source.get("type") == "pdf":
        info["dpi"] = read_capture_dpi(source.get("pdf_dpi"))
        try:
            info["page_count"] = pdf_render.pdf_page_count(Path(source["path"]))
        except PdfRenderError as exc:
            return json_error(str(exc))
        source["page_count"] = info["page_count"]
    return jsonify(info)


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    with STORE_LOCK:
        job = JOBS.get(job_id)
        if job is not None:
            job = dict(job)
            job["logs"] = list(job.get("logs", []))
    if job is None:
        return json_error("未知的任务。", 404)
    return jsonify(job)


@app.get("/api/jobs/<job_id>/pdf")
def job_pdf(job_id: str):
    with STORE_LOCK:
        job = JOBS.get(job_id)
    if job is None or job.get("status") != "done":
        return json_error("PDF 尚未生成。", 404)
    return send_from_directory(RUNS_DIR / job_id, job["pdf_name"], as_attachment=False)


@app.get("/api/jobs/<job_id>/long_image")
def job_long_image(job_id: str):
    with STORE_LOCK:
        job = JOBS.get(job_id)
    if job is None or job.get("status") != "done":
        return json_error("长图尚未生成。", 404)
    # 优先用生成时记录的长图文件名；旧会话无 long_name 时回退到固定名推断。
    long_name = job.get("long_name")
    path = RUNS_DIR / job_id / long_name if long_name else None
    if not path or not path.exists():
        fallback = RUNS_DIR / job_id / "tablatura.png"
        if not fallback.exists():
            # 兼容：尝试所有由 pdf_name 派生的 .png。
            base = job.get("pdf_name") or "tablatura.pdf"
            fallback = RUNS_DIR / job_id / (base[:-4] + ".png" if base.lower().endswith(".pdf") else base + ".png")
        if not fallback.exists():
            return json_error("长图文件不存在。", 404)
        path = fallback
    return send_from_directory(RUNS_DIR / job_id, path.name, as_attachment=False)


def _ver_key(v):
    import re as _re
    m = _re.findall(r"\d+", str(v or ""))
    return [int(x) for x in m][:4]


@app.get("/api/latest_version")
def api_latest_version():
    """服务端获取最新 release 版本(首选 Gitee，拉不到再试 GitHub)，避免浏览器403/CORS。"""
    import urllib.request as _ul, re as _re

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"

    def _pull(url, kind):
        req = _ul.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        out = []
        with _ul.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        if not isinstance(data, list):
            return None
        for item in data:
            if not isinstance(item, dict):
                continue
            tag = item.get("tag_name") or item.get("name") or ""
            if not tag:
                continue
            if kind == "github":
                msg = item.get("body") or ""
            else:
                msg = (item.get("message") or "") if (item.get("message") not in (None, "")) \
                    else (item.get("tag_name") or "")
            out.append((_ver_key(tag), tag, msg or ""))
        return out or None

    def _answer(kind, hits):
        uniq = {}
        for _k, tag, msg in hits:
            if tag not in uniq or msg:
                uniq[tag] = msg
        releases = sorted(
            [{"name": tag, "message": msg} for tag, msg in uniq.items()],
            key=lambda r: _ver_key(r["name"]),
            reverse=True,
        )
        top = max(hits, key=lambda h: h[0])
        return jsonify({"version": top[1], "source": kind if top[1] else None, "releases": releases})

    # 1) Gitee tags API
    try:
        api = _pull("https://gitee.com/api/v5/repos/m1ku666/bili-tab-capture/tags?", "gitee")
        if api:
            return _answer("gitee", api)
    except Exception:
        api = None
    # 2) GitHub releases 兜底
    try:
        gh = _pull("https://api.github.com/repos/m1ku666/bili-tab-capture/releases?per_page=30", "github")
        if gh:
            return _answer("github", gh)
    except Exception:
        pass
    return jsonify({"version": None, "source": None, "releases": []})


@app.get("/api/previews/<path:filename>")
def preview_file(filename: str):
    return send_from_directory(PREVIEWS_DIR, filename, as_attachment=False)


if __name__ == "__main__":
    ensure_cache_dirs()
    # 删除“孤儿”中间产物：某 job/source 生命周期已结束即不再需要(bv/local/img 持久缓存不受影响)
    try:
        n = cleanup_orphan_transient()
        if n:
            print(f"已清理 {n} 个已结束 job/source 的中间产物目录。")
    except Exception:
        pass

    def _port_free(p: int) -> bool:
        import socket as _socket

        with contextlib.closing(_socket.socket()) as s:
            s.settimeout(0.5)
            try:
                s.bind(("127.0.0.1", p))
                return True
            except OSError:
                return False

    # 默认 5000 常被 macOS AirPlay 接收器占用；若被占用则自动改用下一个空闲端口，
    # 避免一启动就报 “Address already in use” 直接退出（表现为“打不开/运行不了”）。
    requested = int(os.environ.get("PORT", "5000"))
    port = requested
    if not _port_free(port):
        for candidate in range(requested + 1, requested + 30):
            if _port_free(candidate):
                port = candidate
                break
        else:
            pass  # 都不空闲则交给 Flask 报错
    if port != requested:
        print(f"端口 {requested} 被占用，已自动改用端口 {port}。")

    url = f"http://127.0.0.1:{port}"
    if not os.environ.get("BTAB_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"服务器已启动：{url}")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
