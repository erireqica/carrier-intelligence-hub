import re
from dataclasses import dataclass
from datetime import date, datetime

from app.models.enums import MessageClassification, PolicyStatus
from app.processing.source import SourceBundle, SourceDocument
from app.processing.validation import parse_premium


@dataclass(frozen=True)
class ConflictValue:
    source_id: str
    source_type: str
    source_label: str
    value: str


@dataclass(frozen=True)
class SourceConflict:
    code: str
    field_name: str
    title: str
    message: str
    values: tuple[ConflictValue, ...]


_FIELD_PATTERNS = {
    "policy_number": re.compile(
        r"(?im)^\s*Policy(?:\s+(?:Number|No\.?))?\s*[:#]\s*([^\r\n]+?)\s*$"
    ),
    "client_name": re.compile(r"(?im)^\s*Client(?:\s+Name)?\s*:\s*([^\r\n]+?)\s*$"),
    "premium_amount": re.compile(r"(?im)^\s*(?:Premium|Premium\s+Amount)\s*:\s*([^\r\n]+?)\s*$"),
    "policy_status": re.compile(r"(?im)^\s*(?:Policy\s+Status|Status)\s*:\s*([^\r\n]+?)\s*$"),
    "classification": re.compile(r"(?im)^\s*Notice\s+Type\s*:\s*([^\r\n]+?)\s*$"),
    "effective_date": re.compile(r"(?im)^\s*Effective(?:\s+Date)?\s*:\s*([^\r\n]+?)\s*$"),
}

_CONFLICT_DETAILS = {
    "policy_number": (
        "POLICY_NUMBER_CONFLICT",
        "Policy number conflict",
        "The carrier sources contain different policy numbers.",
    ),
    "client_name": (
        "CLIENT_IDENTITY_CONFLICT",
        "Client identity conflict",
        "The carrier sources identify different clients.",
    ),
    "premium_amount": (
        "PREMIUM_CONFLICT",
        "Premium conflict",
        "The carrier sources contain different premium amounts.",
    ),
    "currency": (
        "CURRENCY_CONFLICT",
        "Premium currency conflict",
        "The carrier sources contain different currencies.",
    ),
    "policy_status": (
        "POLICY_STATUS_CONFLICT",
        "Policy status conflict",
        "The carrier sources contain incompatible policy statuses.",
    ),
    "classification": (
        "POLICY_STATUS_CONFLICT",
        "Policy status conflict",
        "The carrier sources describe incompatible policy events and statuses.",
    ),
    "effective_date": (
        "EFFECTIVE_DATE_CONFLICT",
        "Effective date conflict",
        "The carrier sources contain different effective dates.",
    ),
}


def _source_label(document: SourceDocument) -> str:
    if document.source_type == "EMAIL":
        return "Email body"
    return (
        f"PDF attachment {document.attachment_id}" if document.attachment_id else "PDF attachment"
    )


def _canonical_status(value: str) -> str | None:
    normalized = re.sub(r"[_\s/-]+", " ", value).strip().upper()
    aliases = {
        "POLICY ISSUED": PolicyStatus.ISSUED.value,
        "ISSUED": PolicyStatus.ISSUED.value,
        "ACTIVE": PolicyStatus.ACTIVE.value,
        "PENDING": PolicyStatus.PENDING.value,
        "PENDING REQUIREMENTS": PolicyStatus.PENDING.value,
        "LAPSED": PolicyStatus.LAPSED.value,
        "LAPSE NOTICE": PolicyStatus.LAPSED.value,
        "GRACE PERIOD": PolicyStatus.GRACE_PERIOD.value,
        "RISK OF LAPSE": PolicyStatus.GRACE_PERIOD.value,
        "DECLINED": PolicyStatus.DECLINED.value,
    }
    return aliases.get(normalized)


def _canonical_classification(value: str) -> str | None:
    normalized = re.sub(r"[_\s/-]+", " ", value).strip().upper()
    aliases = {
        "POLICY ISSUED": MessageClassification.POLICY_ISSUED.value,
        "PENDING REQUIREMENTS": MessageClassification.PENDING_REQUIREMENTS.value,
        "LAPSE NOTICE": MessageClassification.LAPSE_NOTICE.value,
        "COMMISSION UPDATE": MessageClassification.COMMISSION_UPDATE.value,
        "OTHER": MessageClassification.OTHER.value,
    }
    return aliases.get(normalized)


def _canonical_date(value: str) -> str | None:
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def _canonical(field_name: str, value: str) -> tuple[str, str | None] | None:
    if field_name == "client_name":
        display = re.sub(r"\s+", " ", value).strip()
        return display.casefold(), None
    if field_name == "policy_number":
        display = re.sub(r"\s+", " ", value).strip().upper()
        return display.casefold(), None
    if field_name == "policy_status":
        status = _canonical_status(value)
        return (status, None) if status else None
    if field_name == "classification":
        classification = _canonical_classification(value)
        return (classification, None) if classification else None
    if field_name == "effective_date":
        parsed = _canonical_date(value)
        return (parsed, None) if parsed else None
    if field_name == "premium_amount":
        amount, currency, error = parse_premium(value)
        if error or amount is None:
            return None
        return f"{amount:.2f}", currency
    return None


def detect_source_conflicts(bundle: SourceBundle) -> tuple[SourceConflict, ...]:
    found: dict[str, dict[str, list[ConflictValue]]] = {}
    currencies: dict[str, list[ConflictValue]] = {}
    for document in bundle.documents:
        for field_name, pattern in _FIELD_PATTERNS.items():
            for match in pattern.finditer(document.content):
                raw = match.group(1).strip()
                canonical = _canonical(field_name, raw)
                if canonical is None:
                    continue
                value, currency = canonical
                item = ConflictValue(
                    source_id=document.source_id,
                    source_type=document.source_type,
                    source_label=_source_label(document),
                    value=raw,
                )
                found.setdefault(field_name, {}).setdefault(value, []).append(item)
                if field_name == "premium_amount" and currency:
                    currencies.setdefault(currency, []).append(item)

    conflicts: list[SourceConflict] = []
    for field_name, groups in found.items():
        if len(groups) <= 1:
            continue
        code, title, message = _CONFLICT_DETAILS[field_name]
        conflicts.append(
            SourceConflict(
                code=code,
                field_name=field_name,
                title=title,
                message=message,
                values=tuple(item for group in groups.values() for item in group),
            )
        )
    classifications = found.get("classification", {})
    statuses = found.get("policy_status", {})
    if len(classifications) == 1 and len(statuses) == 1:
        classification = next(iter(classifications))
        policy_status = next(iter(statuses))
        compatible = {
            MessageClassification.POLICY_ISSUED.value: {
                PolicyStatus.ISSUED.value,
                PolicyStatus.ACTIVE.value,
            },
            MessageClassification.PENDING_REQUIREMENTS.value: {PolicyStatus.PENDING.value},
            MessageClassification.LAPSE_NOTICE.value: {
                PolicyStatus.GRACE_PERIOD.value,
                PolicyStatus.LAPSED.value,
            },
        }.get(classification)
        if compatible is not None and policy_status not in compatible:
            code, title, message = _CONFLICT_DETAILS["policy_status"]
            conflicts.append(
                SourceConflict(
                    code=code,
                    field_name="policy_status",
                    title=title,
                    message=message,
                    values=tuple(
                        item
                        for groups in (classifications.values(), statuses.values())
                        for group in groups
                        for item in group
                    ),
                )
            )
    if len(currencies) > 1:
        code, title, message = _CONFLICT_DETAILS["currency"]
        conflicts.append(
            SourceConflict(
                code=code,
                field_name="currency",
                title=title,
                message=message,
                values=tuple(item for group in currencies.values() for item in group),
            )
        )
    return tuple(sorted(conflicts, key=lambda item: item.code))


def unique_source_values(bundle: SourceBundle) -> dict[str, str]:
    """Return only explicit critical values that agree across every source."""
    found: dict[str, dict[str, str]] = {}
    currencies: dict[str, str] = {}
    for document in bundle.documents:
        for field_name, pattern in _FIELD_PATTERNS.items():
            for match in pattern.finditer(document.content):
                raw = match.group(1).strip()
                canonical = _canonical(field_name, raw)
                if canonical is None:
                    continue
                value, currency = canonical
                display = (
                    value
                    if field_name
                    in {
                        "classification",
                        "policy_status",
                        "effective_date",
                        "premium_amount",
                    }
                    else re.sub(r"\s+", " ", raw).strip()
                )
                found.setdefault(field_name, {})[value] = display
                if field_name == "premium_amount" and currency:
                    currencies[currency] = currency
    result = {
        field_name: next(iter(values.values()))
        for field_name, values in found.items()
        if len(values) == 1
    }
    if len(currencies) == 1:
        result["currency"] = next(iter(currencies))
    return result
