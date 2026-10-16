"""bytes/text -> ParsedDocument (pdf, docx, txt, images; per-page OCR fallback). LLD §3.1
(module map) / HLD §3.1.

No branch writes bytes to disk or returns a file path — CLAUDE.md §2.3: no document bytes
persisted, not on disk, not anywhere. Every format is parsed straight from the in-memory
`bytes` the caller hands in; PDF pages needing OCR are rasterized into an in-memory PIL
Image (app/extract/ocr.py) and never touch a temp file.

OCR is applied per page, not per document: a 40-page loan agreement with two scanned
exhibit pages should not lose those two pages' content just because the other 38 have a
clean text layer, and it should not fall back to OCR-ing the whole document either — that
would throw away the real text layer's superior accuracy on the 38 pages that have one.
"""

import io

from docx import Document as DocxDocument
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import Settings
from app.domain.documents import ParsedDocument
from app.extract.ocr import OCRError, ocr_image, ocr_pdf_page
from app.obs.logging import get_logger

logger = get_logger()

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp")


class ParseError(Exception):
    pass


def _try_decrypt(reader: PdfReader) -> None:
    """Some scanners emit PDFs "encrypted" with an empty owner password — these aren't
    actually access-protected, just technically encrypted. Anything requiring a real
    password is rejected with a clear message rather than guessed at."""
    if not reader.is_encrypted:
        return
    try:
        result = reader.decrypt("")
    except Exception as exc:
        raise ParseError(f"PDF is password-protected and could not be opened: {exc}") from exc
    if result == 0:
        raise ParseError("PDF is password-protected — re-submit a decrypted copy")


def _parse_pdf(data: bytes, *, settings: Settings) -> tuple[str, int, bool]:
    try:
        reader = PdfReader(io.BytesIO(data))
    except (PdfReadError, ValueError) as exc:
        raise ParseError(f"could not read PDF: {exc}") from exc

    _try_decrypt(reader)

    page_count = len(reader.pages)
    if page_count == 0:
        raise ParseError("PDF has no pages")

    try:
        page_texts = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise ParseError(f"could not read PDF text layer: {exc}") from exc

    ocr_page_indices = [
        i for i, text in enumerate(page_texts) if len(text) < settings.ocr_char_per_page_threshold
    ]

    if not ocr_page_indices:
        return "\n".join(page_texts), page_count, False

    if page_count > settings.ocr_max_pages:
        raise ParseError(
            f"document has {page_count} pages and needs OCR on {len(ocr_page_indices)} of "
            f"them — exceeds the {settings.ocr_max_pages}-page OCR limit for this build"
        )

    for i in ocr_page_indices:
        try:
            page_texts[i] = ocr_pdf_page(data, i, dpi=settings.ocr_dpi, lang=settings.ocr_lang)
        except OCRError as exc:
            raise ParseError(f"OCR failed on page {i + 1} of {page_count}: {exc}") from exc

    logger.info(
        "document.ocr_applied",
        page_count=page_count,
        ocr_page_count=len(ocr_page_indices),
    )
    return "\n".join(page_texts), page_count, True


def _parse_docx(data: bytes) -> str:
    try:
        doc = DocxDocument(io.BytesIO(data))
    except Exception as exc:
        raise ParseError(f"could not read DOCX: {exc}") from exc
    return "\n".join(p.text for p in doc.paragraphs)


def _parse_image(data: bytes, *, settings: Settings) -> str:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except UnidentifiedImageError as exc:
        raise ParseError(f"could not read image: {exc}") from exc
    try:
        text = ocr_image(image.convert("RGB"), lang=settings.ocr_lang)
    except OCRError as exc:
        raise ParseError(f"OCR failed on image: {exc}") from exc
    logger.info("document.ocr_applied", page_count=1, ocr_page_count=1)
    return text


def parse_document(
    *, filename: str, data: bytes | None = None, text: str | None = None, settings: Settings
) -> ParsedDocument:
    """Exactly one of `data` (raw file bytes) or `text` (already-extracted plain text, the
    common API path per LLD §15.1 where the submission carries `text` directly) must be
    given."""
    if text is not None:
        return ParsedDocument(text=text, char_count=len(text), page_count=None, ocr_used=False)

    if data is None:
        raise ParseError("either data or text must be supplied")
    if not data:
        raise ParseError("file is empty")

    lower = filename.lower()

    if lower.endswith(".pdf"):
        extracted, page_count, ocr_used = _parse_pdf(data, settings=settings)
        return ParsedDocument(
            text=extracted, char_count=len(extracted), page_count=page_count, ocr_used=ocr_used
        )

    if lower.endswith(".docx"):
        extracted = _parse_docx(data)
        return ParsedDocument(
            text=extracted, char_count=len(extracted), page_count=None, ocr_used=False
        )

    if lower.endswith(".doc"):
        raise ParseError(
            "legacy .doc (pre-2007 binary Word format) is not supported — "
            "re-save as .docx or .pdf and re-submit"
        )

    if lower.endswith(".txt"):
        extracted = data.decode("utf-8", errors="replace")
        return ParsedDocument(
            text=extracted, char_count=len(extracted), page_count=None, ocr_used=False
        )

    if lower.endswith(IMAGE_EXTENSIONS):
        extracted = _parse_image(data, settings=settings)
        return ParsedDocument(
            text=extracted, char_count=len(extracted), page_count=1, ocr_used=True
        )

    raise ParseError(f"unsupported file type: {filename}")
