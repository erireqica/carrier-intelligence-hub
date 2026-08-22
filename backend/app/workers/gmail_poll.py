import argparse
import logging
import signal
import time
from collections.abc import Callable
from types import FrameType

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.integrations.gmail import (
    GmailReauthorizationRequired,
    GmailTransientError,
    SyncResult,
    sync_connection,
)
from app.models.enums import GmailConnectionStatus
from app.models.organization import GmailConnection, User

logger = logging.getLogger("carrier_hub.gmail_poll")
SyncFunction = Callable[[Session, int], SyncResult]
SessionFactory = Callable[[], Session]


def _raise_keyboard_interrupt(_signum: int, _frame: FrameType | None) -> None:
    """Route Windows Ctrl+Break through the normal graceful shutdown path."""
    raise KeyboardInterrupt


def _configure_shutdown_signals() -> None:
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, _raise_keyboard_interrupt)


def poll_once(
    *,
    connection_id: int | None = None,
    sync_function: SyncFunction = sync_connection,
    session_factory: SessionFactory = SessionLocal,
) -> list[SyncResult]:
    with session_factory() as db:
        query = (
            select(GmailConnection.id)
            .join(User, User.id == GmailConnection.user_id)
            .where(
                GmailConnection.status.in_(
                    [GmailConnectionStatus.CONNECTED, GmailConnectionStatus.ERROR]
                ),
                User.is_active.is_(True),
                User.removed_at.is_(None),
            )
        )
        if connection_id is not None:
            query = query.where(GmailConnection.id == connection_id)
        connection_ids = list(db.scalars(query.order_by(GmailConnection.id)).all())

    results: list[SyncResult] = []
    for current_id in connection_ids:
        with session_factory() as db:
            try:
                result = sync_function(db, current_id)
                results.append(result)
                logger.info(
                    "Gmail sync completed connection_id=%s seen=%s ingested=%s skipped=%s",
                    current_id,
                    result.messages_seen,
                    result.ingested,
                    result.skipped_unapproved,
                )
            except GmailReauthorizationRequired:
                logger.warning(
                    "Gmail connection requires reauthorization connection_id=%s", current_id
                )
            except GmailTransientError:
                logger.error("Gmail synchronization failed connection_id=%s", current_id)
            except Exception:
                logger.error(
                    "Unexpected Gmail synchronization failure connection_id=%s", current_id
                )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll connected Gmail inboxes safely.")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit.")
    parser.add_argument("--connection-id", type=int, help="Limit polling to one connection ID.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    if not settings.gmail_oauth_configured:
        raise SystemExit("Gmail integration is not configured.")

    _configure_shutdown_signals()
    try:
        while True:
            poll_once(connection_id=args.connection_id)
            if args.once:
                return
            time.sleep(settings.gmail_poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Gmail poller stopped")


if __name__ == "__main__":
    main()
