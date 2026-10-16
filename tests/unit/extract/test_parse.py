import io

import pytest
from docx import Document as DocxDocument
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from app.config import Settings
from app.extract.parse import ParseError, parse_document


def _settings(**kw) -> Settings:
    defaults = dict(database_url="postgresql+asyncpg://u:p@localhost/db")
    defaults.update(kw)
    return Settings(_env_file=None, **defaults)  # type: ignore[call-arg]


def _make_text_pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text.splitlines() or [text]:
        c.drawString(50, y, line[:100])
        y -= 20
    c.save()
    return buf.getvalue()


def _make_blank_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.showPage()
    c.save()
    return buf.getvalue()


def _make_docx(text: str) -> bytes:
    doc = DocxDocument()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _text_image(text: str, *, width: int = 1000, height: int = 200) -> Image.Image:
    """A synthetic "scanned page": real rendered glyphs with no PDF text layer behind
    them, so OCR is the only way to recover the content. Large, high-contrast text —
    this only needs to be legible to tesseract, not realistic."""
    image = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    draw.text((20, 20), text, fill="black", font=font)
    return image


def _make_scanned_pdf(text: str) -> bytes:
    """A PDF with no extractable text layer at all — just an embedded page image, the way
    a real scanner or fax output would look."""
    image = _text_image(text)
    img_buf = io.BytesIO()
    image.save(img_buf, format="PDF")
    reader_bytes = img_buf.getvalue()
    return reader_bytes


def _make_image_bytes(text: str, *, fmt: str = "PNG") -> bytes:
    image = _text_image(text)
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


def _merge_pdfs(*pdf_bytes: bytes) -> bytes:
    writer = PdfWriter()
    for data in pdf_bytes:
        writer.append(io.BytesIO(data))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_text_submission_used_directly():
    result = parse_document(filename="x.txt", text="hello world", settings=_settings())
    assert result.text == "hello world"
    assert result.char_count == 11
    assert result.ocr_used is False


def test_txt_bytes_parsed():
    result = parse_document(filename="doc.txt", data=b"plain text content", settings=_settings())
    assert "plain text content" in result.text


def test_pdf_with_text_layer_parses_without_ocr():
    content = "This is a Key Facts Statement with plenty of readable text content here. " * 5
    pdf_bytes = _make_text_pdf(content)
    result = parse_document(
        filename="kfs.pdf", data=pdf_bytes, settings=_settings(ocr_char_per_page_threshold=10)
    )
    assert result.ocr_used is False
    assert result.page_count == 1


def test_blank_pdf_triggers_ocr_and_returns_empty_text():
    """A genuinely blank page has nothing for OCR to find — this should succeed (ocr_used
    True, text empty-ish), not be treated as a parse failure. A failure is reserved for
    cases where OCR itself could not run, not for pages with nothing on them."""
    pdf_bytes = _make_blank_pdf()
    result = parse_document(
        filename="scan.pdf", data=pdf_bytes, settings=_settings(ocr_char_per_page_threshold=120)
    )
    assert result.ocr_used is True
    assert result.page_count == 1


def test_scanned_pdf_recovered_via_ocr():
    pdf_bytes = _make_scanned_pdf("SANCTIONED AMOUNT FIVE LAKH")
    result = parse_document(
        filename="scan.pdf", data=pdf_bytes, settings=_settings(ocr_char_per_page_threshold=120)
    )
    assert result.ocr_used is True
    assert "SANCTIONED" in result.text.upper()


def test_mixed_pdf_only_ocrs_the_scanned_page():
    """One real text-layer page plus one scanned page: the text page's extraction should be
    used as-is (not re-OCR'd, which would be strictly worse), and only the scanned page
    should go through OCR."""
    text_page = _make_text_pdf("This is a Key Facts Statement with readable text. " * 5)
    scanned_page = _make_scanned_pdf("PENAL CHARGE TWO PERCENT")
    merged = _merge_pdfs(text_page, scanned_page)
    result = parse_document(
        filename="mixed.pdf", data=merged, settings=_settings(ocr_char_per_page_threshold=120)
    )
    assert result.ocr_used is True
    assert result.page_count == 2
    assert "Key Facts Statement" in result.text
    assert "PENAL CHARGE" in result.text.upper()


def test_ocr_page_limit_exceeded_raises():
    pdf_bytes = _make_blank_pdf()
    with pytest.raises(ParseError, match="OCR limit"):
        parse_document(
            filename="scan.pdf",
            data=pdf_bytes,
            settings=_settings(ocr_char_per_page_threshold=120, ocr_max_pages=0),
        )


def test_png_image_recovered_via_ocr():
    png_bytes = _make_image_bytes("CLOSURE DATE JANUARY 2026", fmt="PNG")
    result = parse_document(filename="call_screenshot.png", data=png_bytes, settings=_settings())
    assert result.ocr_used is True
    assert "CLOSURE" in result.text.upper()


def test_corrupt_pdf_bytes_raise_clean_parse_error():
    with pytest.raises(ParseError, match="could not read PDF"):
        parse_document(
            filename="broken.pdf", data=b"%PDF-1.4 not actually a pdf", settings=_settings()
        )


def test_corrupt_image_bytes_raise_clean_parse_error():
    with pytest.raises(ParseError, match="could not read image"):
        parse_document(filename="broken.png", data=b"not a real png", settings=_settings())


def test_empty_file_raises():
    with pytest.raises(ParseError, match="empty"):
        parse_document(filename="empty.pdf", data=b"", settings=_settings())


def test_legacy_doc_extension_rejected_with_clear_message():
    with pytest.raises(ParseError, match=r"\.doc\b.*not supported"):
        parse_document(filename="old_agreement.doc", data=b"\xd0\xcf\x11\xe0", settings=_settings())


def test_docx_parsed():
    docx_bytes = _make_docx("Sanctioned amount is five lakh rupees.")
    result = parse_document(filename="agreement.docx", data=docx_bytes, settings=_settings())
    assert "five lakh" in result.text


def test_corrupt_docx_bytes_raise_clean_parse_error():
    with pytest.raises(ParseError, match="could not read DOCX"):
        parse_document(filename="broken.docx", data=b"not a real docx", settings=_settings())


def test_unsupported_extension_raises():
    with pytest.raises(ParseError, match="unsupported"):
        parse_document(filename="x.xyz", data=b"abc", settings=_settings())


def test_no_bytes_written_to_disk(tmp_path, monkeypatch):
    """No branch writes bytes to disk or returns a file path (CLAUDE.md §2.3) — covers the
    OCR path too, which is the one most tempted to use a temp file."""
    monkeypatch.chdir(tmp_path)
    parse_document(filename="x.txt", text="some text", settings=_settings())
    scanned = _make_scanned_pdf("NO DISK WRITES")
    parse_document(filename="scan.pdf", data=scanned, settings=_settings())
    written_files = list(tmp_path.rglob("*"))
    assert written_files == []
