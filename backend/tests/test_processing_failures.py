from datetime import timedelta

from app.core.time import utc_now
from app.services.processing_failures import (
    processing_retry_state,
    safe_processing_failure_reason,
)


def test_processing_failure_reason_and_retry_state_are_safe_and_explicit() -> None:
    assert safe_processing_failure_reason("MATERIALIZATION_FAILED") == (
        "Analysis completed, but the case or tasks could not be saved safely."
    )
    assert processing_retry_state("AI_TIMEOUT", utc_now() + timedelta(minutes=1)) == (
        "AUTOMATIC_RETRY_SCHEDULED"
    )
    assert processing_retry_state("AI_TIMEOUT", None) == "AUTOMATIC_RETRIES_EXHAUSTED"
    assert processing_retry_state("MATERIALIZATION_FAILED", None) == ("MANUAL_RECOVERY_REQUIRED")
    assert processing_retry_state("GMAIL_REAUTH_REQUIRED", None) == ("REAUTHORIZATION_REQUIRED")
    assert safe_processing_failure_reason("UNALLOWLISTED_INTERNAL_DETAIL") == (
        "Processing stopped because of an internal error."
    )
