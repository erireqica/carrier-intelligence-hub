import logging

from app.core.logging import GMAIL_OAUTH_CALLBACK_PATH, OAuthCallbackAccessLogFilter


def access_record(request_target: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("local-test", "GET", request_target, "1.1", 302),
        None,
    )


def test_oauth_callback_query_is_removed_from_access_log() -> None:
    record = access_record(f"{GMAIL_OAUTH_CALLBACK_PATH}?redacted")

    assert OAuthCallbackAccessLogFilter().filter(record) is True

    assert record.args[2] == GMAIL_OAUTH_CALLBACK_PATH
    assert "?" not in record.getMessage()


def test_other_access_log_targets_are_unchanged() -> None:
    request_target = "/api/v1/health?ready=yes"
    record = access_record(request_target)

    assert OAuthCallbackAccessLogFilter().filter(record) is True

    assert record.args[2] == request_target
