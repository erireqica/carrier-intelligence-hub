import pymupdf

from app.integrations.pdf import extract_pdf
from app.models.enums import AttachmentStatus


def pdf_bytes(*pages: str) -> bytes:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def test_extracts_text_pdf_with_page_boundaries_and_order() -> None:
    result = extract_pdf(
        pdf_bytes("First page policy TEST-100", "Second page signed authorization"),
        mime_type="application/pdf",
        max_bytes=1_000_000,
        max_pages=10,
    )

    assert result.status is AttachmentStatus.EXTRACTED
    assert result.page_count == 2
    assert result.text is not None
    assert result.text.index("First page") < result.text.index("Second page")
    assert "--- Page 1 ---" in result.text
    assert "--- Page 2 ---" in result.text


def test_image_only_pdf_requires_ocr_without_calling_ocr() -> None:
    result = extract_pdf(
        pdf_bytes(""),
        mime_type="application/pdf",
        max_bytes=1_000_000,
        max_pages=10,
    )

    assert result.status is AttachmentStatus.NEEDS_OCR
    assert result.error_code == "PDF_NEEDS_OCR"
    assert result.text is None


def test_malformed_oversized_page_limited_and_non_pdf_states() -> None:
    malformed = extract_pdf(
        b"not a pdf",
        mime_type="application/pdf",
        max_bytes=1_000_000,
        max_pages=10,
    )
    oversized = extract_pdf(
        b"x" * 11,
        mime_type="application/pdf",
        max_bytes=10,
        max_pages=10,
    )
    too_many_pages = extract_pdf(
        pdf_bytes("page one text content", "page two text content"),
        mime_type="application/pdf",
        max_bytes=1_000_000,
        max_pages=1,
    )
    unsupported = extract_pdf(
        b"image bytes",
        mime_type="image/png",
        max_bytes=1_000_000,
        max_pages=10,
    )

    assert (malformed.status, malformed.error_code) == (
        AttachmentStatus.FAILED,
        "PDF_MALFORMED",
    )
    assert (oversized.status, oversized.error_code) == (
        AttachmentStatus.FAILED,
        "PDF_TOO_LARGE",
    )
    assert (too_many_pages.status, too_many_pages.error_code) == (
        AttachmentStatus.FAILED,
        "PDF_TOO_MANY_PAGES",
    )
    assert unsupported.status is AttachmentStatus.UNSUPPORTED
