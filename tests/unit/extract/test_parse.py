import io

import pytest
from docx import Document as DocxDocument
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


def test_blank_pdf_triggers_ocr_fallback_and_raises():
    pdf_bytes = _make_blank_pdf()
    with pytest.raises(ParseError, match="OCR"):
        parse_document(
            filename="scan.pdf", data=pdf_bytes, settings=_settings(ocr_char_per_page_threshold=120)
        )


def test_docx_parsed():
    docx_bytes = _make_docx("Sanctioned amount is five lakh rupees.")
    result = parse_document(filename="agreement.docx", data=docx_bytes, settings=_settings())
    assert "five lakh" in result.text


def test_unsupported_extension_raises():
    with pytest.raises(ParseError, match="unsupported"):
        parse_document(filename="x.xyz", data=b"abc", settings=_settings())


def test_no_bytes_written_to_disk(tmp_path, monkeypatch):
    """No branch writes bytes to disk or returns a file path (CLAUDE.md §2.3)."""
    monkeypatch.chdir(tmp_path)
    parse_document(filename="x.txt", text="some text", settings=_settings())
    written_files = list(tmp_path.rglob("*"))
    assert written_files == []
