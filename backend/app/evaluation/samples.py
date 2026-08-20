from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.integrations.ai.schemas import AnalysisResult
from app.models.enums import MessageClassification, PolicyStatus, Priority
from app.processing.source import SourceBundle, SourceDocument


@dataclass(frozen=True)
class EvaluationSample:
    name: str
    bundle: SourceBundle
    classification: MessageClassification
    client_name: str
    policy_number: str
    policy_status: PolicyStatus
    premium_amount: Decimal | None = None
    currency: str | None = None
    effective_date: str | None = None
    deadline_date: str | None = None
    deadline_relative_count: int | None = None
    deadline_relative_unit: Literal["BUSINESS_DAYS", "CALENDAR_DAYS"] | None = None
    minimum_actions: int = 1
    allowed_priorities: tuple[Priority, ...] = tuple(Priority)


def _bundle(carrier: str, subject: str, body: str) -> SourceBundle:
    document = SourceDocument(source_id="email", source_type="EMAIL", content=body)
    rendered = (
        f"AUTHORITATIVE CARRIER: {carrier}\nSUBJECT: {subject}\nSOURCE email (EMAIL):\n{body}"
    )
    return SourceBundle(
        carrier_name=carrier,
        subject=subject,
        received_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        documents=(document,),
        rendered=rendered,
        truncated=False,
    )


EVALUATION_SAMPLES = (
    EvaluationSample(
        name="Americo",
        bundle=_bundle(
            "Americo",
            "ACTION REQUIRED: Pending Application for John Doe",
            """Client John Doe
Policy # AMR-98765432
Status: PENDING
Please obtain the HIPAA authorization and clarify why a prescription was filled
04/12/2026. Obtain the signed addendum. Return all requirements within 10 business days.""",
        ),
        classification=MessageClassification.PENDING_REQUIREMENTS,
        client_name="John Doe",
        policy_number="AMR-98765432",
        policy_status=PolicyStatus.PENDING,
        deadline_relative_count=10,
        deadline_relative_unit="BUSINESS_DAYS",
        minimum_actions=2,
    ),
    EvaluationSample(
        name="Aetna",
        bundle=_bundle(
            "Aetna",
            "Policy Issued: Medicare Supplement - Smith, Mary",
            """Mary Smith has been APPROVED and ISSUED.
Policy Number: ATN-554433221
Effective Date: 09/01/2026
Monthly Premium: $145.00
The policy packet has been mailed. Notify the client and verify the first premium
draft around the effective date.""",
        ),
        classification=MessageClassification.POLICY_ISSUED,
        client_name="Mary Smith",
        policy_number="ATN-554433221",
        policy_status=PolicyStatus.ISSUED,
        premium_amount=Decimal("145.00"),
        currency="USD",
        effective_date="2026-09-01",
        minimum_actions=1,
    ),
    EvaluationSample(
        name="AMAM",
        bundle=_bundle(
            "American Amicable / AMAM",
            "URGENT: Grace Period Notice - Policy # AA-1122334",
            """Robert Johnson
Policy # AA-1122334
The payment was returned NSF. Past-due amount: $89.50.
The policy is in a 31-day grace period and will lapse if unpaid by September 15, 2026.
Contact the client, update banking information, and ensure payment before the deadline.""",
        ),
        classification=MessageClassification.LAPSE_NOTICE,
        client_name="Robert Johnson",
        policy_number="AA-1122334",
        policy_status=PolicyStatus.GRACE_PERIOD,
        premium_amount=Decimal("89.50"),
        currency="USD",
        deadline_date="2026-09-15",
        minimum_actions=2,
        allowed_priorities=(Priority.HIGH, Priority.URGENT),
    ),
)


def evaluate_result(sample: EvaluationSample, result: AnalysisResult) -> list[str]:
    failures: list[str] = []
    checks = {
        "classification": result.classification == sample.classification,
        "client_name": (result.client_name or "").casefold() == sample.client_name.casefold(),
        "policy_number": (result.policy_number or "").upper() == sample.policy_number,
        "policy_status": result.policy_status == sample.policy_status,
        "priority": result.priority in sample.allowed_priorities,
        "action_items": len(result.action_items) >= sample.minimum_actions,
    }
    if sample.currency is not None:
        checks["currency"] = result.currency == sample.currency
    if sample.effective_date is not None:
        checks["effective_date"] = result.effective_date == sample.effective_date
    if sample.deadline_date is not None:
        checks["deadline"] = (
            result.deadline.explicit_date == sample.deadline_date
            and result.deadline.relative_count is None
            and result.deadline.relative_unit is None
        )
    if sample.deadline_relative_count is not None:
        checks["deadline"] = (
            result.deadline.explicit_date is None
            and result.deadline.relative_count == sample.deadline_relative_count
            and result.deadline.relative_unit == sample.deadline_relative_unit
        )
    if sample.premium_amount is not None:
        try:
            checks["premium_amount"] = Decimal(result.premium_amount or "") == sample.premium_amount
        except InvalidOperation:
            checks["premium_amount"] = False
    failures.extend(name for name, passed in checks.items() if not passed)
    return failures
