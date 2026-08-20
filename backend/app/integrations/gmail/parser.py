import base64
import re
from dataclasses import dataclass
from email.utils import parseaddr
from html.parser import HTMLParser
from typing import Any

from app.core.security import normalize_email


@dataclass(frozen=True)
class ParsedAttachment:
    external_id: str
    filename: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class ParsedMessage:
    sender: str
    subject: str
    raw_content: str
    cleaned_content: str
    attachments: list[ParsedAttachment]


class _ReadableHTMLParser(HTMLParser):
    _BREAK_TAGS = {"br", "div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        elif tag in self._BREAK_TAGS:
            self._text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in self._BREAK_TAGS:
            self._text.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._text.append(data)

    def text(self) -> str:
        return "".join(self._text)


def _decode_body(data: str | None) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")
    except ValueError, TypeError:
        return ""


def _clean_text(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.replace("\r", "").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _html_to_text(value: str) -> str:
    parser = _ReadableHTMLParser()
    parser.feed(value)
    parser.close()
    return _clean_text(parser.text())


def message_headers(message: dict[str, Any]) -> dict[str, str]:
    payload = message.get("payload")
    headers = payload.get("headers", []) if isinstance(payload, dict) else []
    return {
        str(item.get("name", "")).casefold(): str(item.get("value", ""))
        for item in headers
        if isinstance(item, dict) and item.get("name")
    }


def normalized_sender(message: dict[str, Any]) -> str:
    _, address = parseaddr(message_headers(message).get("from", ""))
    return normalize_email(address)


def parse_message(message: dict[str, Any]) -> ParsedMessage:
    headers = message_headers(message)
    _, address = parseaddr(headers.get("from", ""))
    sender = normalize_email(address)
    subject = headers.get("subject", "").strip() or "(No subject)"
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[ParsedAttachment] = []

    def walk(part: dict[str, Any], path: tuple[int, ...]) -> None:
        if not isinstance(part, dict):
            return
        mime_type = str(part.get("mimeType") or "application/octet-stream")
        filename = str(part.get("filename") or "").strip()
        body_value = part.get("body")
        body = body_value if isinstance(body_value, dict) else {}
        attachment_id = str(body.get("attachmentId") or "").strip()
        if filename or attachment_id:
            external_id = str(
                attachment_id
                or part.get("partId")
                or "part-" + ("-".join(map(str, path)) or "root")
            )
            try:
                size_bytes = max(0, int(body.get("size") or 0))
            except TypeError, ValueError:
                size_bytes = 0
            attachments.append(
                ParsedAttachment(
                    external_id=external_id,
                    filename=filename or "(Unnamed attachment)",
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                )
            )
        elif mime_type == "text/plain":
            text = _decode_body(body.get("data"))
            if text:
                plain_parts.append(text)
        elif mime_type == "text/html":
            html = _decode_body(body.get("data"))
            if html:
                html_parts.append(html)
        children = part.get("parts")
        for index, child in enumerate(children if isinstance(children, list) else []):
            walk(child, (*path, index))

    payload = message.get("payload")
    walk(payload if isinstance(payload, dict) else {}, ())
    raw_content = "\n\n".join(plain_parts or html_parts).strip()
    cleaned_content = (
        _clean_text("\n\n".join(plain_parts))
        if plain_parts
        else _html_to_text("\n\n".join(html_parts))
    )
    return ParsedMessage(
        sender=sender,
        subject=subject,
        raw_content=raw_content,
        cleaned_content=cleaned_content,
        attachments=attachments,
    )
