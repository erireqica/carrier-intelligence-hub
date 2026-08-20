class GmailIntegrationNotConfigured(RuntimeError):
    """Raised when required local Google configuration is absent or invalid."""


class GmailReauthorizationRequired(RuntimeError):
    """Raised when stored Google authorization can no longer refresh or access Gmail."""


class GmailTransientError(RuntimeError):
    """Raised for a safe-to-retry Gmail API or network failure."""


class GmailTokenExchangeError(GmailTransientError):
    """Raised when Google rejects or cannot complete the authorization-code exchange."""

    def __init__(self, reason: str):
        super().__init__("Google authorization could not be completed.")
        self.reason = reason


class GmailProfileError(GmailTransientError):
    """Raised when the authorized Gmail identity cannot be loaded."""


class GmailProfileRequestError(GmailProfileError):
    """Raised when constructing or executing the Gmail profile request fails."""

    def __init__(self, *, status_code: int | None, reason: str, during_execute: bool):
        super().__init__("Google did not return the authorized Gmail identity.")
        self.status_code = status_code
        self.reason = reason
        self.during_execute = during_execute


class GmailProfileValidationError(GmailProfileError):
    """Raised when Gmail returns a profile that cannot identify an account safely."""

    def __init__(
        self,
        *,
        response_is_mapping: bool,
        email_present: bool,
        email_is_nonempty_string: bool,
        normalized_email_valid: bool,
    ):
        super().__init__("Google did not return the authorized Gmail identity.")
        self.response_is_mapping = response_is_mapping
        self.email_present = email_present
        self.email_is_nonempty_string = email_is_nonempty_string
        self.normalized_email_valid = normalized_email_valid
