from __future__ import annotations

from datetime import datetime

RETRYABLE_PROCESSING_CODES = frozenset(
    {
        "AI_RATE_LIMITED",
        "AI_TIMEOUT",
        "AI_TRANSIENT_FAILURE",
        "AI_SERVICE_UNAVAILABLE",
        "ATTACHMENT_DOWNLOAD_FAILED",
        "STALE_PROCESSING_RECOVERED",
    }
)

SAFE_PROCESSING_FAILURE_REASONS = {
    "AI_NOT_CONFIGURED": "AI analysis is not configured for this environment.",
    "AI_AUTH_FAILED": "The AI provider rejected the configured credentials.",
    "AI_RATE_LIMITED": "The AI service is temporarily rate limited.",
    "AI_TIMEOUT": "The AI service did not respond in time.",
    "AI_TRANSIENT_FAILURE": "The AI service returned a temporary processing error.",
    "AI_SERVICE_UNAVAILABLE": "The AI service is temporarily unavailable.",
    "AI_UNKNOWN_PROVIDER_ERROR": "The AI provider could not complete the analysis.",
    "ATTACHMENT_DOWNLOAD_FAILED": "A Gmail attachment could not be downloaded.",
    "PDF_EXTRACTION_FAILED": "An attachment could not be prepared safely for analysis.",
    "MATERIALIZATION_FAILED": (
        "Analysis completed, but the case or tasks could not be saved safely."
    ),
    "GMAIL_REAUTH_REQUIRED": "Gmail authorization must be renewed before processing can resume.",
    "STALE_PROCESSING_RECOVERED": "An interrupted analysis attempt was recovered.",
    "UNEXPECTED_PROCESSING_FAILURE": "Processing stopped because of an internal error.",
}


def safe_processing_failure_reason(code: str | None) -> str | None:
    if code is None:
        return None
    return SAFE_PROCESSING_FAILURE_REASONS.get(
        code, "Processing stopped because of an internal error."
    )


def processing_retry_state(code: str | None, next_retry_at: datetime | None) -> str | None:
    if code is None:
        return None
    if next_retry_at is not None:
        return "AUTOMATIC_RETRY_SCHEDULED"
    if code == "GMAIL_REAUTH_REQUIRED":
        return "REAUTHORIZATION_REQUIRED"
    if code in RETRYABLE_PROCESSING_CODES:
        return "AUTOMATIC_RETRIES_EXHAUSTED"
    return "MANUAL_RECOVERY_REQUIRED"
