from dataclasses import dataclass
from datetime import datetime

from app.models.enums import AttachmentStatus
from app.models.operations import CarrierMessage


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    source_type: str
    content: str
    attachment_id: int | None = None


@dataclass(frozen=True)
class SourceBundle:
    carrier_name: str
    subject: str
    received_at: datetime
    documents: tuple[SourceDocument, ...]
    rendered: str
    truncated: bool

    @property
    def source_map(self) -> dict[str, SourceDocument]:
        return {document.source_id: document for document in self.documents}


def build_source_bundle(message: CarrierMessage, *, max_chars: int) -> SourceBundle:
    documents = [
        SourceDocument(
            source_id="email",
            source_type="EMAIL",
            content=message.cleaned_content.strip(),
        )
    ]
    for attachment in sorted(message.attachments, key=lambda item: item.id):
        if attachment.processing_status is AttachmentStatus.EXTRACTED and attachment.extracted_text:
            documents.append(
                SourceDocument(
                    source_id=f"attachment:{attachment.id}",
                    source_type="PDF",
                    content=attachment.extracted_text.strip(),
                    attachment_id=attachment.id,
                )
            )

    header = (
        "AUTHORITATIVE CARRIER:\n"
        f"{message.carrier.name}\n\n"
        f"MESSAGE RECEIVED AT:\n{message.received_at.isoformat()}\n\n"
    )
    sections: list[str] = []
    truncated = False
    remaining = max_chars - len(header)
    for document in documents:
        filename = ""
        if document.attachment_id is not None:
            attachment = next(
                item for item in message.attachments if item.id == document.attachment_id
            )
            filename = f"\nFILENAME: {attachment.filename}"
        section = (
            f"SOURCE ID: {document.source_id}\n"
            f"TYPE: {document.source_type}{filename}\n"
            f"SUBJECT: {message.subject if document.source_id == 'email' else ''}\n\n"
            f"{document.content}\n"
        )
        if len(section) > remaining:
            sections.append(section[: max(0, remaining)])
            truncated = True
            break
        sections.append(section)
        remaining -= len(section)

    return SourceBundle(
        carrier_name=message.carrier.name,
        subject=message.subject,
        received_at=message.received_at,
        documents=tuple(documents),
        rendered=header + "\n".join(sections),
        truncated=truncated,
    )
