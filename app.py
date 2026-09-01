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

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
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
    """图片源不走视频提取，直接按裁剪参数切一张截图、立即产出任务。"""
    crop_y_start = parse_float(payload.get("crop_y_start"), "crop_y_start", 0.0)
    crop_y_end = parse_float(payload.get("crop_y_end"), "crop_y_end", 1)
    crop_x_start = parse_float(payload.get("crop_x_start"), "crop_x_start", 0.0)
    crop_x_end = parse_float(payload.get("crop_x_end"), "crop_x_end", 1.0)
    validate_crop_ratios(crop_y_start, crop_y_end)
    validate_crop_x_ratios(crop_x_start, crop_x_end)

    job_id = uuid.uuid4().hex
    run_dir = RUNS_DIR / job_id
    crops_dir = run_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    metadata = metadata_from_dict(source.get("metadata", {}))
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
    nw, nh = image.size
    capture = {
        "file": out_name,
        "url": f"/api/captures/{job_id}/{out_name}",
        "t": 0.0,
        "w": nw,
        "h": nh,
    }
    stats = ExtractionStats(captures_kept=1).to_dict()
    with STORE_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "source_id": source["id"],
            "status": "done",
            "phase": "done",
            "logs": ["已导入图片。"],
            "stats": stats,
            "captures": [capture],
            "metadata": metadata_to_dict(metadata),
            "error": None,
            "pdf_url": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
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
        # 统一重命名为 BVxxxx.mp4，避免直接用视频标题（可能含中文/特殊字符）作文件名。
        target = cache_dir / f"{bvid}.mp4"
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
            if state is not None and state.get("captures"):
                job_id = make_cached_job(source_id, cache_dir, state)
                source["restore"] = {"job_id": job_id, "images": restore_images(state), "layout": state.get("layout"), "maxStage": state.get("maxStage")}
                source["download"]["status"] = "done"
                if cached_video is not None:
                    source["video_path"] = str(cached_video)
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
            original_name = secure_filename(upload.filename)
            suffix = Path(original_name).suffix.lower()
            source_id = uuid.uuid4().hex
            upload_dir = UPLOADS_DIR / source_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            saved_path = upload_dir / original_name
            upload.save(saved_path)
            if suffix in ALLOWED_IMAGE_EXTENSIONS:
                metadata = build_video_metadata(raw_title=Path(original_name).stem)
                source = {
                    "id": source_id,
                    "type": "image",
                    "path": str(saved_path),
                    "metadata": metadata_to_dict(metadata),
                    "duration": None,
                }
            elif suffix in ALLOWED_VIDEO_EXTENSIONS:
                duration = get_video_duration(saved_path)
                metadata = build_video_metadata(raw_title=Path(original_name).stem)
                file_hash = hash_file(saved_path)
                cache_dir = local_cache_dir(file_hash)
                cache_dir.mkdir(parents=True, exist_ok=True)
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
                if state is not None and state.get("captures"):
                    job_id = make_cached_job(source_id, cache_dir, state)
                    source["restore"] = {"job_id": job_id, "images": restore_images(state), "layout": state.get("layout"), "maxStage": state.get("maxStage")}
            else:
                return json_error("不支持的文件格式，请使用视频（mp4/mov/mkv/webm）或图片（png/jpg/webp/bmp/gif）。")
        else:
            return json_error("请填写 BV 号，或选择本地视频。")

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

        preview_name = f"{source['id']}_{int(time_sec * 1000)}_{uuid.uuid4().hex[:8]}.jpg"
        preview_path = PREVIEWS_DIR / preview_name

        if source["type"] == "bilibili":
            cached = Path(source.get("video_path") or "")
            if cached.exists():
                video_path = cached
            else:
                video_path = cached_remote_preview_video(source)
            save_video_frame(video_path, preview_path, time_sec=time_sec)
        else:
            save_video_frame(Path(source["path"]), preview_path, time_sec=time_sec)

        return jsonify(
            {
                "preview_url": f"/api/previews/{preview_name}",
                "duration": source.get("duration"),
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
        if source["type"] == "image":
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
    tolerance = parse_float(request.args.get("tolerance"), "tolerance", 60.0)
    softness = parse_float(request.args.get("softness"), "softness", 20.0)

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
    tolerance = parse_float(payload.get("tolerance"), "tolerance", 60.0)
    softness = parse_float(payload.get("softness"), "softness", 20.0)
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
        tolerance = parse_float(payload.get("tolerance"), "tolerance", 60.0)
        softness = parse_float(payload.get("softness"), "softness", 20.0)
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
        tolerance = parse_float(payload.get("tolerance"), "tolerance", 60.0)
        softness = parse_float(payload.get("softness"), "softness", 20.0)
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
    if source is None or source.get("type") != "image":
        return json_error("未知的图片源。", 404)
    return send_file(source["path"])


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


@app.get("/api/previews/<path:filename>")
def preview_file(filename: str):
    return send_from_directory(PREVIEWS_DIR, filename, as_attachment=False)


if __name__ == "__main__":
    ensure_cache_dirs()
    port = int(os.environ.get("PORT", "5000"))
    url = f"http://127.0.0.1:{port}"
    if not os.environ.get("BILIX_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"服务器已启动：{url}")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
