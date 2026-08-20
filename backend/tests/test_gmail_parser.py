import base64

import pytest

from app.integrations.gmail.parser import normalized_sender, parse_message


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def message(payload: dict, *, internal_date: str = "1787184000000") -> dict:
    return {
        "id": "gmail-message-1",
        "threadId": "gmail-thread-1",
        "internalDate": internal_date,
        "payload": {
            "headers": [
                {"name": "From", "value": '"Carrier Notices" <Notices@Example.COM>'},
                {"name": "Subject", "value": "Synthetic carrier notice"},
            ],
            **payload,
        },
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"mimeType": "text/plain", "body": {"data": encoded("Plain body")}}, "Plain body"),
        (
            {"mimeType": "text/html", "body": {"data": encoded("<p>Hello <b>team</b></p>")}},
            "Hello team",
        ),
        (
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": encoded("Preferred plain")}},
                    {"mimeType": "text/html", "body": {"data": encoded("<p>HTML copy</p>")}},
                ],
            },
            "Preferred plain",
        ),
        (
            {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {"mimeType": "text/html", "body": {"data": encoded("<p>Nested</p>")}}
                        ],
                    }
                ],
            },
            "Nested",
        ),
    ],
)
def test_parse_common_gmail_mime_layouts(payload: dict, expected: str) -> None:
    parsed = parse_message(message(payload))
    assert parsed.sender == "notices@example.com"
    assert parsed.subject == "Synthetic carrier notice"
    assert parsed.cleaned_content == expected


def test_attachment_and_attachment_only_message_are_safe() -> None:
    parsed = parse_message(
        message(
            {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "partId": "1",
                        "mimeType": "application/pdf",
                        "filename": "requirements.pdf",
                        "body": {"attachmentId": "gmail-attachment-1", "size": 3210},
                    }
                ],
            }
        )
    )
    assert parsed.raw_content == parsed.cleaned_content == ""
    assert parsed.attachments[0].external_id == "gmail-attachment-1"
    assert parsed.attachments[0].filename == "requirements.pdf"
    assert parsed.attachments[0].size_bytes == 3210


def test_missing_subject_and_display_name_from_header() -> None:
    fixture = message({"mimeType": "text/plain", "body": {"data": encoded("Body")}})
    fixture["payload"]["headers"] = [
        {"name": "From", "value": "Carrier Team <Alerts@Mail.Example.com>"}
    ]
    assert normalized_sender(fixture) == "alerts@mail.example.com"
    assert parse_message(fixture).subject == "(No subject)"


def test_invalid_base64url_body_does_not_crash() -> None:
    parsed = parse_message(
        message({"mimeType": "text/plain", "body": {"data": "%%%not-base64%%%"}})
    )
    assert parsed.cleaned_content == ""


def test_unnamed_attachment_and_malformed_optional_values_are_safe() -> None:
    fixture = message(
        {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "application/octet-stream",
                    "body": {"attachmentId": "unnamed-1", "size": "not-a-number"},
                }
            ],
        }
    )
    fixture["payload"]["headers"].append("malformed-header")
    parsed = parse_message(fixture)
    assert parsed.attachments[0].external_id == "unnamed-1"
    assert parsed.attachments[0].filename == "(Unnamed attachment)"
    assert parsed.attachments[0].size_bytes == 0
