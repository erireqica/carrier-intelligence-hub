import argparse
import logging
import signal
import time
from collections.abc import Callable
from types import FrameType

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.integrations.ai import AnalysisProviderError, Analyzer, OpenAIAnalyzer
from app.services.message_processing import (
    ProcessingResult,
    claim_message,
    mark_failed,
    process_claimed_message,
    recover_stale_processing,
)

logger = logging.getLogger("carrier_hub.message_process")
SessionFactory = Callable[[], Session]
AnalyzerFactory = Callable[[], Analyzer]


def _raise_keyboard_interrupt(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def _configure_shutdown_signals() -> None:
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, _raise_keyboard_interrupt)


def process_once(
    *,
    message_id: int | None = None,
    session_factory: sessionmaker[Session] | SessionFactory = SessionLocal,
    analyzer_factory: AnalyzerFactory = OpenAIAnalyzer,
) -> list[ProcessingResult]:
    with session_factory() as db:
        recover_stale_processing(db)
    analyzer = analyzer_factory()
    results: list[ProcessingResult] = []
    while True:
        with session_factory() as db:
            claimed = claim_message(
                db,
                message_id=message_id,
                allow_failed=message_id is not None,
            )
        if claimed is None:
            break
        with session_factory() as db:
            try:
                result = process_claimed_message(db, claimed, analyzer=analyzer)
            except Exception:
                result = mark_failed(db, claimed, "UNEXPECTED_PROCESSING_FAILURE")
            results.append(result)
            logger.info(
                "Message processing completed message_id=%s status=%s case_id=%s review_id=%s",
                result.message_id,
                result.processing_status,
                result.case_id,
                result.review_id,
            )
        if message_id is not None:
            break
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Process received carrier messages safely.")
    parser.add_argument("--once", action="store_true", help="Run one processing cycle and exit.")
    parser.add_argument("--message-id", type=int, help="Limit processing to one message ID.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    if not settings.openai_configured:
        raise SystemExit("AI analysis is not configured.")

    _configure_shutdown_signals()
    try:
        while True:
            try:
                process_once(message_id=args.message_id)
            except AnalysisProviderError:
                logger.error("Message processor could not initialize the AI provider safely")
                if args.once:
                    raise SystemExit(1) from None
            if args.once or args.message_id is not None:
                return
            time.sleep(settings.message_process_poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Message processor stopped")


if __name__ == "__main__":
    main()
