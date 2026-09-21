"""PDF 渲染：把 PDF 的每一页渲染成位图，供导入/裁剪/排版复用图片那一套流程。

依赖 PyMuPDF(pymupdf)：纯 wheel、无外部可执行文件依赖，跨平台一致。
本模块**延迟导入** fitz，这样在缺少该依赖时，只有真正导入 PDF 才会报错，
其余功能（视频/图片）不受影响。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# PDF 渲染 DPI 的可调范围与默认值（与前端第 2 步输入框保持一致）
PDF_DPI_DEFAULT = 200
PDF_DPI_MIN = 50
PDF_DPI_MAX = 600

# 单页渲染的像素上限（约 40MP）：极端页面尺寸下防止内存爆掉。
MAX_RENDER_PIXELS = 40_000_000


class PdfRenderError(RuntimeError):
    """PDF 无法解析或渲染时抛出（消息直接给用户看）。"""


def _import_fitz():
    try:
        import pymupdf  # noqa: F401  (PyMuPDF >= 1.24 的新模块名)
        return pymupdf
    except Exception:
        pass
    try:
        import fitz  # PyMuPDF 旧模块名
        return fitz
    except Exception as exc:  # pragma: no cover - 依赖缺失时的提示
        raise PdfRenderError(
            "缺少 PDF 支持库 PyMuPDF，请先执行：pip install pymupdf"
        ) from exc


def clamp_dpi(value: Any, default: int = PDF_DPI_DEFAULT) -> int:
    """把外部传入的 DPI 收敛到合法区间。"""
    try:
        dpi = int(round(float(value)))
    except (TypeError, ValueError):
        dpi = int(default)
    return max(PDF_DPI_MIN, min(PDF_DPI_MAX, dpi))


def open_pdf(path: Path):
    """打开 PDF 文档。调用方负责 close()。"""
    pymupdf = _import_fitz()
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise PdfRenderError(f"无法打开 PDF：{exc}") from exc
    if doc.needs_pass:
        doc.close()
        raise PdfRenderError("该 PDF 已加密，暂不支持导入带密码的 PDF。")
    if doc.page_count <= 0:
        doc.close()
        raise PdfRenderError("该 PDF 没有任何页面。")
    return doc


def pdf_page_count(path: Path) -> int:
    """PDF 页数（用于导入时快速探页）。"""
    doc = open_pdf(path)
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def _render_doc_page(doc, index: int, dpi: int):
    """渲染第 index 页为 PIL RGB 图像。"""
    from PIL import Image  # 局部导入，避免模块级循环依赖

    page = doc.load_page(index)
    zoom = dpi / 72.0
    try:
        rect = page.rect
        # 极端大页面：按面积上限下调缩放，避免内存爆炸。
        est = (rect.width * zoom) * (rect.height * zoom)
        if est > MAX_RENDER_PIXELS and est > 0:
            zoom *= (MAX_RENDER_PIXELS / est) ** 0.5
        matrix = _import_fitz().Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
    except Exception as exc:
        raise PdfRenderError(f"第 {index + 1} 页渲染失败：{exc}") from exc

    mode = "RGB" if pix.n >= 3 else "L"
    image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    return image.convert("RGB")


def render_pdf_page(path: Path, index: int, dpi: int = PDF_DPI_DEFAULT):
    """渲染 PDF 的单页（0 基）为 PIL RGB 图像。"""
    dpi = clamp_dpi(dpi)
    doc = open_pdf(path)
    try:
        if index < 0 or index >= doc.page_count:
            raise PdfRenderError("页码超出范围。")
        return _render_doc_page(doc, index, dpi)
    finally:
        doc.close()


def render_pdf_pages(
    path: Path,
    out_dir: Path,
    dpi: int = PDF_DPI_DEFAULT,
    prefix: str = "page",
    start_index: int = 0,
    max_pages: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """把 PDF 每页渲染为 out_dir/<prefix>_0001.png，返回页信息列表。

    每项：{"file": 文件名, "index": 0 基页序, "w": 宽, "h": 高}。
    """
    dpi = clamp_dpi(dpi)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = open_pdf(path)
    pages: List[Dict[str, Any]] = []
    try:
        total = doc.page_count
        end = total if max_pages is None else min(total, start_index + max(0, max_pages))
        for i in range(max(0, start_index), end):
            image = _render_doc_page(doc, i, dpi)
            name = f"{prefix}_{i + 1:04d}.png"
            image.save(out_dir / name, optimize=False)
            pages.append({"file": name, "index": i, "w": image.width, "h": image.height})
            image.close()
    finally:
        doc.close()
    return pages


def pdf_page_sizes(path: Path) -> List[Tuple[float, float]]:
    """各页尺寸（PDF 点，1/72 英寸），用于按比例映射裁剪框。"""
    doc = open_pdf(path)
    try:
        sizes: List[Tuple[float, float]] = []
        for i in range(doc.page_count):
            rect = doc.load_page(i).rect
            sizes.append((float(rect.width), float(rect.height)))
        return sizes
    finally:
        doc.close()
