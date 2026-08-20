import argparse
import logging
import signal
import time
from collections.abc import Callable
from types import FrameType

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.gmail_labels import (
    LabelResult,
    claim_label_sync,
    process_claimed_label_sync,
    recover_stale_label_syncs,
)

logger = logging.getLogger("carrier_hub.gmail_labels")
SessionFactory = Callable[[], Session]


def _raise_keyboard_interrupt(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def _configure_shutdown_signals() -> None:
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, _raise_keyboard_interrupt)


def reconcile_once(
    *,
    sync_id: int | None = None,
    connection_id: int | None = None,
    session_factory: sessionmaker[Session] | SessionFactory = SessionLocal,
) -> list[LabelResult]:
    with session_factory() as db:
        recover_stale_label_syncs(db)
    results: list[LabelResult] = []
    while True:
        with session_factory() as db:
            claim = claim_label_sync(db, sync_id=sync_id, connection_id=connection_id)
        if claim is None:
            break
        with session_factory() as db:
            try:
                result = process_claimed_label_sync(db, claim)
            except Exception:
                logger.exception(
                    "Unexpected Gmail label reconciliation failure sync_id=%s",
                    claim.sync_id,
                )
                if sync_id is not None:
                    break
                continue
            results.append(result)
            logger.info(
                "Gmail label reconciliation completed sync_id=%s status=%s generation=%s",
                result.sync_id,
                result.status,
                result.generation,
            )
        if sync_id is not None:
            break
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile Carrier Hub Gmail labels safely.")
    parser.add_argument("--once", action="store_true", help="Run one due-work pass and exit.")
    parser.add_argument("--sync-id", type=int, help="Limit reconciliation to one sync row.")
    parser.add_argument("--connection-id", type=int, help="Limit reconciliation to one inbox.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    if not settings.gmail_oauth_configured:
        raise SystemExit("Gmail integration is not configured.")

    _configure_shutdown_signals()
    try:
        while True:
            reconcile_once(sync_id=args.sync_id, connection_id=args.connection_id)
            if args.once or args.sync_id is not None:
                return
            time.sleep(settings.gmail_label_poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Gmail label worker stopped")


if __name__ == "__main__":
    main()
