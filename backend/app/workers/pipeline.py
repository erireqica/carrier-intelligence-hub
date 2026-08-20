import argparse
import logging
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import FrameType

from app.core.config import get_settings
from app.integrations.gmail.sync import SyncResult
from app.services.gmail_labels import LabelResult
from app.services.message_processing import ProcessingResult
from app.workers.gmail_labels import reconcile_once
from app.workers.gmail_poll import poll_once
from app.workers.message_process import process_once

logger = logging.getLogger("carrier_hub.pipeline")


@dataclass(frozen=True)
class PipelineSummary:
    gmail_connections: int
    messages_ingested: int
    messages_processed: int
    reviews_created: int
    label_syncs_applied: int
    failures: int


def _raise_keyboard_interrupt(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def _configure_shutdown_signals() -> None:
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, _raise_keyboard_interrupt)


def pipeline_once(
    *,
    poll_function: Callable[..., list[SyncResult]] = poll_once,
    process_function: Callable[..., list[ProcessingResult]] = process_once,
    label_function: Callable[..., list[LabelResult]] = reconcile_once,
) -> PipelineSummary:
    sync_results = poll_function()
    processing_results = process_function()
    label_results = label_function()
    summary = PipelineSummary(
        gmail_connections=len(sync_results),
        messages_ingested=sum(result.ingested for result in sync_results),
        messages_processed=sum(
            result.processing_status.value == "PROCESSED" for result in processing_results
        ),
        reviews_created=sum(result.review_id is not None for result in processing_results),
        label_syncs_applied=sum(result.status.value == "APPLIED" for result in label_results),
        failures=sum(result.processing_status.value == "FAILED" for result in processing_results)
        + sum(result.status.value == "FAILED" for result in label_results),
    )
    logger.info(
        "Pipeline cycle completed gmail_connections=%s messages_ingested=%s "
        "messages_processed=%s reviews_created=%s label_syncs_applied=%s failures=%s",
        summary.gmail_connections,
        summary.messages_ingested,
        summary.messages_processed,
        summary.reviews_created,
        summary.label_syncs_applied,
        summary.failures,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Carrier Hub processing pipeline.")
    parser.add_argument("--once", action="store_true", help="Run one complete pipeline pass.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    if not settings.gmail_oauth_configured:
        raise SystemExit("Gmail integration is not configured.")
    if not settings.openai_configured:
        raise SystemExit("AI analysis is not configured.")
    _configure_shutdown_signals()
    if args.once:
        pipeline_once()
        return

    now = time.monotonic()
    next_gmail = now
    next_processing = now
    next_labels = now
    try:
        while True:
            now = time.monotonic()
            if now >= next_gmail:
                poll_once()
                next_gmail = now + settings.gmail_poll_interval_seconds
            if now >= next_processing:
                process_once()
                next_processing = now + settings.message_process_poll_interval_seconds
            if now >= next_labels:
                reconcile_once()
                next_labels = now + settings.gmail_label_poll_interval_seconds
            sleep_for = max(0.1, min(next_gmail, next_processing, next_labels) - time.monotonic())
            time.sleep(min(sleep_for, 1.0))
    except KeyboardInterrupt:
        logger.info("Carrier Hub pipeline stopped")


if __name__ == "__main__":
    main()
