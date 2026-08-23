import re
from dataclasses import dataclass
from datetime import date, datetime

from app.integrations.ai.schemas import SourceFact
from app.models.enums import MessageClassification, PolicyStatus
from app.processing.source import SourceBundle, SourceDocument
from app.processing.validation import normalize_excerpt, parse_premium


@dataclass(frozen=True)
class ConflictValue:
    source_id: str
    source_type: str
    source_label: str
    value: str
    excerpt: str | None = None


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
    if field_name == "currency":
        currency = value.strip().upper()
        return (currency, None) if re.fullmatch(r"[A-Z]{3}", currency) else None
    return None


_MONEY_IN_TEXT = re.compile(
    r"(?i)(?:(?P<prefix>[A-Z]{3})\s+)?(?P<symbol>\$)?\s*"
    r"(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)"
    r"(?:\s+(?P<suffix>[A-Z]{3}))?"
)
_DATE_IN_TEXT = re.compile(
    r"(?i)\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2},\s+\d{4})\b"
)


def _money_values(value: str) -> list[tuple[str, str | None]]:
    candidates: list[tuple[str, str | None]] = []
    for match in _MONEY_IN_TEXT.finditer(value):
        pieces = [
            match.group("prefix") or "",
            match.group("symbol") or "",
            match.group("amount"),
            match.group("suffix") or "",
        ]
        amount, currency, error = parse_premium(" ".join(item for item in pieces if item))
        if error is None and amount is not None:
            candidates.append((f"{amount:.2f}", currency))
    return candidates


def _fact_supported(fact: SourceFact, document: SourceDocument, canonical: str) -> bool:
    if normalize_excerpt(fact.excerpt) not in normalize_excerpt(document.content):
        return False
    excerpt = fact.excerpt
    if fact.field_name == "policy_number":
        return re.sub(r"\s+", "", canonical).casefold() in re.sub(r"\s+", "", excerpt).casefold()
    if fact.field_name == "client_name":
        tokens = set(re.findall(r"\w+", canonical.casefold()))
        return bool(tokens) and tokens.issubset(set(re.findall(r"\w+", excerpt.casefold())))
    if fact.field_name == "premium_amount":
        return any(amount == canonical for amount, _currency in _money_values(excerpt))
    if fact.field_name == "currency":
        explicit = {item.upper() for item in re.findall(r"\b[A-Za-z]{3}\b", excerpt)}
        return canonical in explicit or (canonical == "USD" and "$" in excerpt)
    if fact.field_name == "effective_date":
        return any(
            _canonical_date(item.group(0)) == canonical for item in _DATE_IN_TEXT.finditer(excerpt)
        )
    normalized = normalize_excerpt(excerpt)
    if fact.field_name == "policy_status":
        support = {
            PolicyStatus.ISSUED.value: ("issued",),
            PolicyStatus.ACTIVE.value: ("active", "in force"),
            PolicyStatus.PENDING.value: ("pending",),
            PolicyStatus.LAPSED.value: ("lapsed", "has lapsed"),
            PolicyStatus.GRACE_PERIOD.value: ("grace period", "risk of lapse"),
            PolicyStatus.DECLINED.value: ("declined",),
        }
        return any(term in normalized for term in support.get(canonical, ()))
    if fact.field_name == "classification":
        support = {
            MessageClassification.POLICY_ISSUED.value: (
                "policy issued",
                "issued policy",
                "policy has been issued",
                "policy is issued",
            ),
            MessageClassification.PENDING_REQUIREMENTS.value: (
                "pending requirements",
                "requirements remain outstanding",
            ),
            MessageClassification.LAPSE_NOTICE.value: ("lapse notice", "has lapsed"),
            MessageClassification.COMMISSION_UPDATE.value: ("commission",),
            MessageClassification.OTHER.value: (),
        }
        return any(term in normalized for term in support.get(canonical, ()))
    return False


CandidateGroups = dict[str, dict[str, dict[str, ConflictValue]]]


def _add_candidate(
    groups: CandidateGroups,
    *,
    field_name: str,
    canonical: str,
    value: ConflictValue,
) -> None:
    groups.setdefault(field_name, {}).setdefault(canonical, {}).setdefault(value.source_id, value)


def _candidate_groups(
    bundle: SourceBundle, source_facts: tuple[SourceFact, ...] | list[SourceFact] = ()
) -> CandidateGroups:
    found: CandidateGroups = {}
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
                    excerpt=match.group(0).strip(),
                )
                _add_candidate(found, field_name=field_name, canonical=value, value=item)
                if field_name == "premium_amount" and currency:
                    _add_candidate(found, field_name="currency", canonical=currency, value=item)

    source_map = bundle.source_map
    for fact in source_facts:
        document = source_map.get(fact.source_id)
        if document is None:
            continue
        canonical = _canonical(fact.field_name, fact.value)
        if canonical is None:
            continue
        value, inline_currency = canonical
        if not _fact_supported(fact, document, value):
            continue
        item = ConflictValue(
            source_id=document.source_id,
            source_type=document.source_type,
            source_label=_source_label(document),
            value=fact.value,
            excerpt=fact.excerpt,
        )
        _add_candidate(found, field_name=fact.field_name, canonical=value, value=item)
        if fact.field_name == "premium_amount":
            supported_currencies = {
                currency
                for amount, currency in _money_values(fact.excerpt)
                if amount == value and currency
            }
            if inline_currency:
                supported_currencies.add(inline_currency)
            for currency in supported_currencies:
                _add_candidate(found, field_name="currency", canonical=currency, value=item)
    return found


def detect_source_conflicts(
    bundle: SourceBundle, source_facts: tuple[SourceFact, ...] | list[SourceFact] = ()
) -> tuple[SourceConflict, ...]:
    found = _candidate_groups(bundle, source_facts)

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
                values=tuple(item for group in groups.values() for item in group.values()),
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
                        for item in group.values()
                    ),
                )
            )
    return tuple(sorted(conflicts, key=lambda item: item.code))


def is_human_resolvable_source_conflict(conflict: SourceConflict) -> bool:
    """Return whether grounded, independent sources present competing values."""
    source_ids = {value.source_id for value in conflict.values}
    candidate_values = {value.value.strip().casefold() for value in conflict.values}
    return (
        len(source_ids) > 1
        and len(candidate_values) > 1
        and all(value.excerpt and value.excerpt.strip() for value in conflict.values)
    )


def unique_source_values(
    bundle: SourceBundle, source_facts: tuple[SourceFact, ...] | list[SourceFact] = ()
) -> dict[str, str]:
    """Return only explicit critical values that agree across every source."""
    found = _candidate_groups(bundle, source_facts)
    result: dict[str, str] = {}
    for field_name, values in found.items():
        if len(values) != 1:
            continue
        canonical, candidates = next(iter(values.items()))
        if field_name in {
            "classification",
            "policy_status",
            "effective_date",
            "premium_amount",
            "currency",
        }:
            result[field_name] = canonical
        else:
            result[field_name] = next(iter(candidates.values())).value
    return result
