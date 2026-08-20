from dataclasses import dataclass

import pymupdf

from app.models.enums import AttachmentStatus


@dataclass(frozen=True)
class PdfExtraction:
    status: AttachmentStatus
    text: str | None = None
    page_count: int | None = None
    error_code: str | None = None


def extract_pdf(
    content: bytes,
    *,
    mime_type: str,
    max_bytes: int,
    max_pages: int,
) -> PdfExtraction:
    if mime_type.lower() != "application/pdf":
        return PdfExtraction(AttachmentStatus.UNSUPPORTED, error_code="ATTACHMENT_UNSUPPORTED")
    if len(content) > max_bytes:
        return PdfExtraction(AttachmentStatus.FAILED, error_code="PDF_TOO_LARGE")
    try:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            page_count = document.page_count
            if document.needs_pass:
                return PdfExtraction(
                    AttachmentStatus.FAILED,
                    page_count=page_count,
                    error_code="PDF_ENCRYPTED",
                )
            if page_count > max_pages:
                return PdfExtraction(
                    AttachmentStatus.FAILED,
                    page_count=page_count,
                    error_code="PDF_TOO_MANY_PAGES",
                )
            pages = [
                f"--- Page {index + 1} ---\n{page.get_text('text', sort=True).strip()}"
                for index, page in enumerate(document)
            ]
    except Exception:
        return PdfExtraction(AttachmentStatus.FAILED, error_code="PDF_MALFORMED")

    text = "\n\n".join(pages).strip()
    meaningful = sum(character.isalnum() for character in text)
    if meaningful < 20:
        return PdfExtraction(
            AttachmentStatus.NEEDS_OCR,
            page_count=page_count,
            error_code="PDF_NEEDS_OCR",
        )
    return PdfExtraction(AttachmentStatus.EXTRACTED, text=text, page_count=page_count)
