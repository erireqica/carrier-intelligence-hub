"""Focused Google OAuth and Gmail API integration boundary."""

from app.integrations.gmail.errors import GmailReauthorizationRequired, GmailTransientError
from app.integrations.gmail.sync import SyncResult, sync_connection

__all__ = [
    "GmailReauthorizationRequired",
    "GmailTransientError",
    "SyncResult",
    "sync_connection",
]
