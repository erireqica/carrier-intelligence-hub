from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings
from app.integrations.gmail.errors import (
    GmailIntegrationNotConfigured,
    GmailReauthorizationRequired,
)


class TokenCipher:
    """Authenticated encryption for OAuth token material stored in PostgreSQL."""

    def __init__(self, key: str):
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (TypeError, ValueError) as error:
            raise GmailIntegrationNotConfigured(
                "Google token encryption is not configured correctly."
            ) from error

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TokenCipher:
        active_settings = settings or get_settings()
        if active_settings.google_token_encryption_key is None:
            raise GmailIntegrationNotConfigured("Google token encryption is not configured.")
        return cls(active_settings.google_token_encryption_key.get_secret_value())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as error:
            raise GmailReauthorizationRequired(
                "Stored Google authorization could not be decrypted."
            ) from error
