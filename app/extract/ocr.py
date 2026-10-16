"""Rasterize a PDF page and run OCR over it, entirely in memory. LLD §3.1.

Isolated from parse.py for the same reason app/llm/ is isolated from the rest of the
codebase: this is the one place that talks to an external binary (tesseract) and the one
place that would change if OCR ever moved to a hosted API instead of a local engine.
Nothing here touches disk — CLAUDE.md §2.3 (no document bytes persisted, not even
transiently) — PyMuPDF rasterizes a page straight into an in-memory pixmap and pytesseract
reads a PIL Image, so a scanned page never becomes a temp file.
"""

import io

import pymupdf as fitz
import pytesseract
from PIL import Image


class OCRError(Exception):
    pass


def rasterize_pdf_page(data: bytes, page_index: int, *, dpi: int) -> Image.Image:
    """Render one page of an in-memory PDF to a PIL Image. `page_index` is 0-based."""
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            page = doc[page_index]
            pixmap = page.get_pixmap(dpi=dpi)
            return Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    except Exception as exc:  # pragma: no cover - fitz raises its own exception types
        raise OCRError(f"could not rasterize page {page_index}: {exc}") from exc


def ocr_image(image: Image.Image, *, lang: str) -> str:
    try:
        result: str = pytesseract.image_to_string(image, lang=lang)
        return result
    except pytesseract.TesseractError as exc:
        raise OCRError(f"OCR engine failed: {exc}") from exc
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRError(
            "tesseract binary not found — install tesseract-ocr in this environment"
        ) from exc


def ocr_pdf_page(data: bytes, page_index: int, *, dpi: int, lang: str) -> str:
    image = rasterize_pdf_page(data, page_index, dpi=dpi)
    return ocr_image(image, lang=lang)
