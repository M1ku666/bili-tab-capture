import contextlib
import io
import json
import re
import subprocess
import tempfile
import threading
import time
import uuid
import os
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime_paths import data_dir
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image, ImageColor, ImageOps

from tab_extractor import (
    BILIX_EXE,
    ExtractionOptions,
    ExtractionStats,
    RESAMPLE,
    VideoMetadata,
    binarize_luminance,
    build_pdf_from_images,
    build_video_metadata,
    decode_bytes,
    download_bilibili_video,
    download_video,
    extract_unique_crops,
    find_video_file,
    get_video_duration,
    hex_to_rgb,
    normalize_bilibili_url,
    probe_bilibili_metadata,
    probe_youtube_metadata,
    save_video_frame,
    validate_crop_ratios,
    validate_crop_x_ratios,
)


ROOT_DIR = data_dir()
CACHE_DIR = ROOT_DIR / "app_cache"
UPLOADS_DIR = CACHE_DIR / "uploads"
PREVIEWS_DIR = CACHE_DIR / "previews"
RUNS_DIR = CACHE_DIR / "runs"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
YOUTUBE_PREVIEW_MAX_HEIGHT = 480

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

SOURCES: Dict[str, Dict[str, Any]] = {}
JOBS: Dict[str, Dict[str, Any]] = {}
STORE_LOCK = threading.Lock()

BILIBILI_LOGIN_LOCK = threading.Lock()
BILIBILI_LOGIN: Dict[str, Any] = {"status": "idle", "qr": None, "message": None}
BILIBILI_LOGIN_TOKEN: Optional[str] = None
BILIBILI_LOGIN_PROCESS: Optional[subprocess.Popen] = None


def bilibili_cookie_path() -> Path:
    return Path(BILIX_EXE.parent) / "cookie.txt"


def run_bilibili_login_worker(token: str) -> None:
    global BILIBILI_LOGIN_PROCESS

    cwd = str(BILIX_EXE.parent)
    cookie_path = bilibili_cookie_path()
    cookie_before = cookie_path.stat().st_mtime if cookie_path.exists() else None

    try:
        proc = subprocess.Popen(
            [str(BILIX_EXE), "--login"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        with BILIBILI_LOGIN_LOCK:
            if BILIBILI_LOGIN_TOKEN == token:
                BILIBILI_LOGIN.update(
                    status="error", qr=None, message=f"无法启动 bilix：{exc}"
                )
        return

    BILIBILI_LOGIN_PROCESS = proc
    qr_re = re.compile(r"data:image/[A-Za-z]+;base64,[A-Za-z0-9+/=]+")

    for raw_line in proc.stdout:
        line = decode_bytes(raw_line)
        with BILIBILI_LOGIN_LOCK:
            if BILIBILI_LOGIN["qr"] is None:
                match = qr_re.search(line)
                if match:
                    BILIBILI_LOGIN["qr"] = match.group(0)
                    BILIBILI_LOGIN["message"] = "请用哔哩哔哩扫描二维码登录"

    proc.wait()
    BILIBILI_LOGIN_PROCESS = None

    cookie_after = cookie_path.stat().st_mtime if cookie_path.exists() else None
    success = cookie_after is not None and cookie_after != cookie_before

    with BILIBILI_LOGIN_LOCK:
        if BILIBILI_LOGIN_TOKEN == token:
            if success:
                BILIBILI_LOGIN.update(
                    status="success", qr=None, message="登录成功。"
                )
            else:
                BILIBILI_LOGIN.update(
                    status="error", qr=None, message="登录失败或超时。"
                )


def ensure_cache_dirs() -> None:
    for directory in (UPLOADS_DIR, PREVIEWS_DIR, RUNS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def is_youtube_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


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


def safe_pdf_name(value: str) -> str:
    # 保留中文等 Unicode，只替换 Windows 文件名不允许的字符。
    filename = _INVALID_FILENAME_CHARS.sub("_", (value or "tablatura.pdf").strip()).strip(" .")
    if not filename:
        filename = "tablatura.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    return filename


def cached_remote_preview_video(source: Dict[str, Any]) -> Path:
    preview_dir = PREVIEWS_DIR / source["id"] / "video"
    preview_dir.mkdir(parents=True, exist_ok=True)

    existing = find_video_file(preview_dir)
    if existing is not None:
        return existing

    if source["type"] == "bilibili":
        return download_bilibili_video(source["url"], preview_dir, quality=16)

    video_path, _metadata, _downloaded_start = download_video(
        source["url"],
        preview_dir,
        max_height=YOUTUBE_PREVIEW_MAX_HEIGHT,
    )
    return video_path


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
            download_dir = run_dir / "download"
            crops_dir = run_dir / "crops"
            comparison_dir = run_dir / "comparison" if options.debug_diffs else None
            run_dir.mkdir(parents=True, exist_ok=True)

            update_job(job_id, status="running", phase="downloading", updated_at=time.time())

            source_metadata = metadata_from_dict(source["metadata"])
            if source["type"] == "youtube":
                print("正在下载 YouTube 视频...")
                video_path, downloaded_metadata, downloaded_start_sec = download_video(
                    source["url"],
                    download_dir,
                    start_sec=start_sec,
                    end_sec=end_sec,
                )
                metadata = build_video_metadata(
                    raw_title=downloaded_metadata.raw_title,
                    channel=downloaded_metadata.channel,
                    source_url=downloaded_metadata.source_url,
                    title_override=payload.get("title"),
                    channel_override=payload.get("channel"),
                )
            elif source["type"] == "bilibili":
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


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/import")
def import_source():
    ensure_cache_dirs()
    youtube_url = (request.form.get("youtube_url") or "").strip()
    bvid = (request.form.get("bvid") or "").strip()
    upload = request.files.get("file")

    try:
        if bvid:
            full_url = normalize_bilibili_url(bvid)
            metadata, duration = probe_bilibili_metadata(full_url)
            source_id = uuid.uuid4().hex
            source = {
                "id": source_id,
                "type": "bilibili",
                "url": full_url,
                "metadata": metadata_to_dict(metadata),
                "duration": duration,
            }
        elif youtube_url:
            if not is_youtube_url(youtube_url):
                return json_error("请输入有效的 YouTube 链接。")
            metadata, duration = probe_youtube_metadata(youtube_url)
            source_id = uuid.uuid4().hex
            source = {
                "id": source_id,
                "type": "youtube",
                "url": youtube_url,
                "metadata": metadata_to_dict(metadata),
                "duration": duration,
            }
        elif upload and upload.filename:
            original_name = secure_filename(upload.filename)
            suffix = Path(original_name).suffix.lower()
            if suffix not in ALLOWED_VIDEO_EXTENSIONS:
                return json_error("不支持的视频格式，请使用 mp4、mov、mkv 或 webm。")
            source_id = uuid.uuid4().hex
            upload_dir = UPLOADS_DIR / source_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            video_path = upload_dir / original_name
            upload.save(video_path)
            duration = get_video_duration(video_path)
            metadata = build_video_metadata(raw_title=Path(original_name).stem)
            source = {
                "id": source_id,
                "type": "local",
                "path": str(video_path),
                "metadata": metadata_to_dict(metadata),
                "duration": duration,
            }
        else:
            return json_error("请填写 YouTube 链接或 Bilibili BV 号，或选择本地视频。")

        with STORE_LOCK:
            SOURCES[source_id] = source

        return jsonify(source)
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/api/bilibili/login")
def bilibili_login_start():
    global BILIBILI_LOGIN_TOKEN

    with BILIBILI_LOGIN_LOCK:
        if BILIBILI_LOGIN["status"] == "running":
            return jsonify(dict(BILIBILI_LOGIN))

    if BILIBILI_LOGIN_PROCESS is not None:
        BILIBILI_LOGIN_PROCESS.terminate()

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

    proc = BILIBILI_LOGIN_PROCESS
    if proc is not None:
        proc.terminate()

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

        if source["type"] in ("youtube", "bilibili"):
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
        source_or_error(payload.get("source_id"))
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
    return send_from_directory(RUNS_DIR / job_id / "crops", filename, as_attachment=False)


@app.get("/api/capture_preview/<job_id>/<path:filename>")
def capture_preview(job_id: str, filename: str):
    """按当前二值化/反色/配色设置实时返回处理后的单张截图。

    变换顺序与 /api/pdf 完全一致（先反色，再二值化），保证预览所见即所得。
    """
    crops_dir = RUNS_DIR / job_id / "crops"
    src = crops_dir / filename
    if not src.exists():
        return json_error("未知的截图。", 404)

    invert = parse_bool(request.args.get("invert"))
    binarize = parse_bool(request.args.get("binarize"))
    note_dark = parse_bool(request.args.get("note_dark", "true"))

    threshold_raw = request.args.get("threshold")
    threshold = None
    if threshold_raw not in (None, ""):
        try:
            threshold = int(float(threshold_raw))
        except (TypeError, ValueError):
            threshold = None

    text_color = parse_hex_color(request.args.get("text_color"), "#181818")
    bg_color = (request.args.get("bg_color") or "white").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}|[a-zA-Z]+", bg_color):
        bg_color = "white"

    try:
        img = Image.open(src).convert("RGB")
        if invert:
            img = ImageOps.invert(img)
        if binarize:
            thr = threshold
            if not note_dark and thr is not None:
                thr = 255 - thr
            img = binarize_luminance(
                img,
                threshold=thr,
                dark_note=note_dark,
                foreground_rgb=hex_to_rgb(text_color),
                background_rgb=ImageColor.getrgb(bg_color),
            )
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    except Exception as exc:
        return json_error(str(exc), 500)


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

        crops_dir = RUNS_DIR / job_id / "crops"
        final_dir = RUNS_DIR / job_id / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        for old in final_dir.glob("*.png"):
            old.unlink()

        margin = int(parse_float(payload.get("margin"), "margin", 40))
        spacing = int(parse_float(payload.get("spacing"), "spacing", 25))
        bg_color = (payload.get("bg_color") or "white").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}|[a-zA-Z]+", bg_color):
            bg_color = "white"

        text_color = parse_hex_color(payload.get("text_color"), "#181818")
        note_dark = parse_bool(payload.get("note_dark", True))
        binarize = parse_bool(payload.get("binarize"))
        invert = parse_bool(payload.get("invert"))
        binarize_threshold = parse_optional_float(payload.get("binarize_threshold"), "binarize_threshold")
        binarize_threshold = int(binarize_threshold) if binarize_threshold is not None else None
        if not note_dark and binarize_threshold is not None:
            binarize_threshold = 255 - binarize_threshold

        orientation = payload.get("orientation") or "portrait"
        if orientation not in ("portrait", "landscape"):
            orientation = "portrait"
        align = payload.get("align") or "left"
        if align not in ("left", "center"):
            align = "left"

        # 与 build_pdf_from_images 一致：横向纸张交换宽高，据此算内容区宽度。
        pdf_w, pdf_h = 1654, 2339
        if orientation == "landscape":
            pdf_w, pdf_h = pdf_h, pdf_w
        content_w = pdf_w - 2 * margin

        index = 0
        for item in payload.get("images") or []:
            src_path = crops_dir / item.get("file", "")
            if not src_path.exists():
                continue
            img = Image.open(src_path).convert("RGB")
            crop = item.get("crop") or {}
            c_l = max(0.0, min(1.0, float(crop.get("l", 0.0))))
            c_t = max(0.0, min(1.0, float(crop.get("t", 0.0))))
            c_r = max(c_l, min(1.0, float(crop.get("r", 1.0))))
            c_b = max(c_t, min(1.0, float(crop.get("b", 1.0))))
            iw, ih = img.size
            # 先按原图缩放到内容区宽度（基准缩放），再裁切，保证裁切后缩放不变化。
            scaled_h = int(round(ih * (content_w / iw)))
            img = img.resize((content_w, scaled_h), RESAMPLE)
            img = img.crop((
                int(round(content_w * c_l)),
                int(round(scaled_h * c_t)),
                int(round(content_w * c_r)),
                int(round(scaled_h * c_b)),
            ))
            if invert:
                img = ImageOps.invert(img)
            if binarize:
                img = binarize_luminance(
                    img,
                    threshold=binarize_threshold,
                    dark_note=note_dark,
                    foreground_rgb=hex_to_rgb(text_color),
                    background_rgb=ImageColor.getrgb(bg_color),
                )
            img.save(final_dir / f"final_{index:04d}.png")
            index += 1

        if index == 0:
            return json_error("没有可导出的截图。")

        metadata = build_video_metadata(
            raw_title=source_metadata.raw_title,
            channel=source_metadata.channel,
            source_url=source_metadata.source_url,
            title_override=payload.get("title"),
            channel_override=payload.get("channel"),
        )
        output_pdf = RUNS_DIR / job_id / safe_pdf_name(payload.get("output") or "tablatura.pdf")
        page_count = build_pdf_from_images(
            final_dir,
            output_pdf,
            metadata=metadata,
            margin=margin,
            spacing=spacing,
            bg_color=bg_color,
            text_color=text_color,
            orientation=orientation,
            align=align,
            fit_width=False,
        )

        update_job(job_id, pdf_name=output_pdf.name, pdf_url=f"/api/jobs/{job_id}/pdf")
        return jsonify({
            "pdf_url": f"/api/jobs/{job_id}/pdf",
            "pdf_name": output_pdf.name,
            "page_count": page_count,
        })
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

        crops_dir = RUNS_DIR / job_id / "crops"
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
