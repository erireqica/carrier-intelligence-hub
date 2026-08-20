import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.integrations.ai.schemas import AnalysisResult, Evidence
from app.models.enums import MessageClassification, PolicyStatus, Priority
from app.processing.source import SourceBundle

POLICY_CLASSIFICATIONS = {
    MessageClassification.POLICY_ISSUED,
    MessageClassification.PENDING_REQUIREMENTS,
    MessageClassification.LAPSE_NOTICE,
}
STATUS_COMPATIBILITY = {
    MessageClassification.POLICY_ISSUED: {PolicyStatus.ISSUED, PolicyStatus.ACTIVE},
    MessageClassification.PENDING_REQUIREMENTS: {PolicyStatus.PENDING},
    MessageClassification.LAPSE_NOTICE: {PolicyStatus.GRACE_PERIOD, PolicyStatus.LAPSED},
}
CRITICAL_EVIDENCE_FIELDS = {
    "client_name",
    "policy_number",
    "policy_status",
    "premium_amount",
    "effective_date",
    "deadline",
}


@dataclass(frozen=True)
class VerifiedEvidence:
    proposal: Evidence
    source_type: str
    attachment_id: int | None


@dataclass(frozen=True)
class ValidatedAnalysis:
    result: AnalysisResult
    flags: tuple[str, ...]
    verified_evidence: tuple[VerifiedEvidence, ...]
    premium_amount: Decimal | None
    effective_date: date | None
    deadline_at: datetime | None

    @property
    def safe_to_apply(self) -> bool:
        return not self.flags


def normalize_excerpt(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def add_business_days(start: date, count: int) -> date:
    result = start
    remaining = count
    while remaining:
        result += timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def resolve_deadline(
    result: AnalysisResult, received_at: datetime, agency_timezone: str
) -> tuple[datetime | None, str | None]:
    deadline = result.deadline
    if not any(
        [deadline.raw_text, deadline.explicit_date, deadline.relative_count, deadline.relative_unit]
    ):
        return None, None
    try:
        timezone = ZoneInfo(agency_timezone)
    except ZoneInfoNotFoundError:
        timezone = UTC
    try:
        if deadline.explicit_date and deadline.relative_count is not None:
            return None, "INVALID_DEADLINE"
        if deadline.explicit_date:
            due_date = date.fromisoformat(deadline.explicit_date)
        elif deadline.relative_count and deadline.relative_unit:
            local_received = received_at.astimezone(timezone).date()
            if deadline.relative_unit == "BUSINESS_DAYS":
                due_date = add_business_days(local_received, deadline.relative_count)
            else:
                due_date = local_received + timedelta(days=deadline.relative_count)
        else:
            return None, "INVALID_DEADLINE"
    except ValueError:
        return None, "INVALID_DEADLINE"
    local_due = datetime.combine(due_date, time(17, 0), timezone)
    return local_due.astimezone(UTC), None


def _parse_premium(value: str | None) -> tuple[Decimal | None, str | None]:
    if value is None:
        return None, None
    try:
        parsed = Decimal(value).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None, "INVALID_PREMIUM"
    if parsed < 0 or parsed > Decimal("9999999999.99"):
        return None, "INVALID_PREMIUM"
    return parsed, None


def _parse_date(value: str | None) -> tuple[date | None, str | None]:
    if value is None:
        return None, None
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, "INVALID_DATE"


def _normalize_result(result: AnalysisResult) -> AnalysisResult:
    client_name = " ".join(result.client_name.split()) if result.client_name else None
    policy_number = " ".join(result.policy_number.split()).upper() if result.policy_number else None
    currency = result.currency.upper() if result.currency else None
    priority = result.priority
    evidence = []
    for item in result.evidence:
        action_alias = re.fullmatch(r"action_items\[(\d+)\]", item.field_name)
        evidence.append(
            item.model_copy(update={"field_name": f"action_item:{action_alias.group(1)}"})
            if action_alias
            else item
        )
    if result.classification is MessageClassification.LAPSE_NOTICE and priority in {
        Priority.LOW,
        Priority.NORMAL,
    }:
        priority = Priority.HIGH
    return result.model_copy(
        update={
            "client_name": client_name,
            "policy_number": policy_number,
            "currency": currency,
            "priority": priority,
            "evidence": evidence,
        }
    )


def validate_analysis(
    result: AnalysisResult,
    bundle: SourceBundle,
    *,
    agency_timezone: str,
    confidence_threshold: float,
    source_flags: set[str] | None = None,
    require_evidence: bool = True,
) -> ValidatedAnalysis:
    normalized = _normalize_result(result)
    flags = set(source_flags or set())
    if normalized.overall_confidence < confidence_threshold:
        flags.add("LOW_CONFIDENCE")
    if normalized.uncertainties:
        flags.add("MODEL_UNCERTAINTY")
    if normalized.classification in POLICY_CLASSIFICATIONS:
        if not normalized.policy_number:
            flags.add("MISSING_POLICY_NUMBER")
        if not normalized.client_name:
            flags.add("MISSING_CLIENT_NAME")
        if normalized.policy_status is PolicyStatus.UNKNOWN:
            flags.add("UNKNOWN_POLICY_STATUS")
    expected = STATUS_COMPATIBILITY.get(normalized.classification)
    if expected is not None and normalized.policy_status not in expected:
        flags.add("CLASSIFICATION_STATUS_MISMATCH")

    premium, premium_error = _parse_premium(normalized.premium_amount)
    effective_date, date_error = _parse_date(normalized.effective_date)
    deadline_at, deadline_error = resolve_deadline(normalized, bundle.received_at, agency_timezone)
    flags.update(item for item in (premium_error, date_error, deadline_error) if item)
    if any(
        action.explicit_due_date is not None
        and _parse_date(action.explicit_due_date)[1] is not None
        for action in normalized.action_items
    ):
        flags.add("INVALID_DATE")
    if normalized.currency and not re.fullmatch(r"[A-Z]{3}", normalized.currency):
        flags.add("INVALID_PREMIUM")

    verified: list[VerifiedEvidence] = []
    invalid_evidence = False
    source_map = bundle.source_map
    for proposal in normalized.evidence:
        source = source_map.get(proposal.source_id)
        if source is None or len(proposal.excerpt) > 500:
            invalid_evidence = True
            continue
        if normalize_excerpt(proposal.excerpt) not in normalize_excerpt(source.content):
            invalid_evidence = True
            continue
        verified.append(
            VerifiedEvidence(
                proposal=proposal,
                source_type=source.source_type,
                attachment_id=source.attachment_id,
            )
        )
    if invalid_evidence:
        flags.add("EVIDENCE_MISMATCH")

    if require_evidence:
        evidenced_fields = {item.proposal.field_name for item in verified}
        required = set()
        for field in CRITICAL_EVIDENCE_FIELDS:
            value = {
                "client_name": normalized.client_name,
                "policy_number": normalized.policy_number,
                "policy_status": (
                    normalized.policy_status
                    if normalized.policy_status is not PolicyStatus.UNKNOWN
                    else None
                ),
                "premium_amount": normalized.premium_amount,
                "effective_date": normalized.effective_date,
                "deadline": normalized.deadline.raw_text,
            }[field]
            if value is not None:
                required.add(field)
        required.update(f"action_item:{index}" for index in range(len(normalized.action_items)))
        if not required.issubset(evidenced_fields):
            flags.add("EVIDENCE_MISMATCH")

    return ValidatedAnalysis(
        result=normalized,
        flags=tuple(sorted(flags)),
        verified_evidence=tuple(verified),
        premium_amount=premium,
        effective_date=effective_date,
        deadline_at=deadline_at,
    )
