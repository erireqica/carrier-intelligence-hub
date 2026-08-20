import logging

GMAIL_OAUTH_CALLBACK_PATH = "/api/v1/gmail/oauth/callback"


class OAuthCallbackAccessLogFilter(logging.Filter):
    """Remove sensitive OAuth callback query strings from Uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or not isinstance(record.args, tuple):
            return True
        if len(record.args) < 3:
            return True

        request_target = record.args[2]
        if not isinstance(request_target, str):
            return True
        if not request_target.startswith(f"{GMAIL_OAUTH_CALLBACK_PATH}?"):
            return True

        arguments = list(record.args)
        arguments[2] = GMAIL_OAUTH_CALLBACK_PATH
        record.args = tuple(arguments)
        return True


def configure_sensitive_log_redaction() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, OAuthCallbackAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(OAuthCallbackAccessLogFilter())
