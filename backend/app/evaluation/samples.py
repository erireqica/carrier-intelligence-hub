import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.integrations.ai.schemas import ActionItem, AnalysisResult
from app.models.enums import MessageClassification, PolicyStatus, Priority
from app.processing.source import SourceBundle, SourceDocument


@dataclass(frozen=True)
class ExpectedAction:
    """A wording-tolerant, deterministic operational-intent expectation."""

    name: str
    concept_groups: tuple[tuple[str, ...], ...]
    explicit_due_date: str | None = None
    due_text_groups: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class EvaluationSample:
    name: str
    bundle: SourceBundle
    classification: MessageClassification
    client_name: str
    policy_number: str
    policy_status: PolicyStatus
    expected_actions: tuple[ExpectedAction, ...]
    premium_amount: Decimal | None = None
    currency: str | None = None
    effective_date: str | None = None
    deadline_date: str | None = None
    deadline_relative_count: int | None = None
    deadline_relative_unit: Literal["BUSINESS_DAYS", "CALENDAR_DAYS"] | None = None
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
            """Dear Agent,
We are currently reviewing the Final Expense application for your client, John Doe.
Policy # AMR-98765432 is currently in PENDING status.
To proceed with underwriting, we require a completed HIPAA authorization form
and a clarification on the medical history questionnaire regarding a prescription
filled on 04/12/2026. Please have the client sign the attached addendum and return
it within 10 business days to avoid application closure.
Thank you,
Americo Underwriting Team""",
        ),
        classification=MessageClassification.PENDING_REQUIREMENTS,
        client_name="John Doe",
        policy_number="AMR-98765432",
        policy_status=PolicyStatus.PENDING,
        expected_actions=(
            ExpectedAction(
                "hipaa_authorization",
                (("hipaa",), ("authorization", "consent")),
            ),
            ExpectedAction(
                "prescription_clarification",
                (
                    ("clarif", "explain", "medical history", "questionnaire"),
                    ("prescription", "medication"),
                    ("04/12/2026", "2026-04-12"),
                ),
            ),
            ExpectedAction(
                "submit_requirements",
                (
                    ("submit", "return", "send", "provide"),
                    ("document", "requirement", "form", "addendum"),
                ),
                due_text_groups=(("10 business day",),),
            ),
        ),
        deadline_relative_count=10,
        deadline_relative_unit="BUSINESS_DAYS",
    ),
    EvaluationSample(
        name="Aetna",
        bundle=_bundle(
            "Aetna",
            "Policy Issued: Medicare Supplement - Smith, Mary",
            """Good morning,
This email is to confirm that the Medicare Supplement policy for Mary Smith has
been APPROVED and ISSUED.
Policy Number: ATN-554433221
Effective Date: 09/01/2026
Monthly Premium: $145.00
The physical policy packet has been mailed directly to the client's address on file.
Your commission will be reflected on your next weekly statement.
Regards,
Aetna Senior Supplemental Insurance""",
        ),
        classification=MessageClassification.POLICY_ISSUED,
        client_name="Mary Smith",
        policy_number="ATN-554433221",
        policy_status=PolicyStatus.ISSUED,
        expected_actions=(
            ExpectedAction(
                "notify_client",
                (
                    ("notify", "inform", "advise", "contact"),
                    ("$client", "client", "insured"),
                    ("approved", "issued"),
                    ("mail", "deliver", "packet"),
                ),
            ),
            ExpectedAction(
                "verify_first_premium",
                (
                    ("verify", "confirm", "check"),
                    ("first premium", "premium draft", "initial premium", "first payment"),
                ),
                explicit_due_date="2026-09-01",
            ),
        ),
        premium_amount=Decimal("145.00"),
        currency="USD",
        effective_date="2026-09-01",
    ),
    EvaluationSample(
        name="AMAM",
        bundle=_bundle(
            "American Amicable / AMAM",
            "URGENT: Grace Period Notice - Policy # AA-1122334",
            """Agent Notification:
Please be advised that the premium payment for Policy # AA-1122334 (Insured:
Robert Johnson) was returned due to insufficient funds (NSF).
The policy is currently in its 31-day grace period. If the past-due amount of $89.50
is not received by September 15, 2026, the policy will lapse. We have sent a
notification letter to the insured. Please reach out to your client to update their
banking information on the agent portal.
American Amicable Life Insurance Company of Texas""",
        ),
        classification=MessageClassification.LAPSE_NOTICE,
        client_name="Robert Johnson",
        policy_number="AA-1122334",
        policy_status=PolicyStatus.GRACE_PERIOD,
        expected_actions=(
            ExpectedAction(
                "contact_client_about_nsf",
                (
                    ("call", "contact", "reach out"),
                    ("$client", "client", "insured"),
                    ("nsf", "insufficient funds", "returned"),
                    ("89.50",),
                ),
            ),
            ExpectedAction(
                "update_banking",
                (
                    ("update", "correct"),
                    ("bank", "payment information", "payment method"),
                    ("portal",),
                    ("lapse",),
                ),
                explicit_due_date="2026-09-15",
            ),
        ),
        premium_amount=Decimal("89.50"),
        currency="USD",
        deadline_date="2026-09-15",
        allowed_priorities=(Priority.HIGH, Priority.URGENT),
    ),
)


def _normalized_action_text(action: ActionItem) -> str:
    value = " ".join((action.title, action.description or "", action.due_text or ""))
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _matches_term(term: str, text: str, client_name: str) -> bool:
    expected = client_name.casefold() if term == "$client" else term.casefold()
    return expected in text


def _matches_action(expectation: ExpectedAction, action: ActionItem, client_name: str) -> bool:
    text = _normalized_action_text(action)
    if not all(
        any(_matches_term(term, text, client_name) for term in group)
        for group in expectation.concept_groups
    ):
        return False
    if expectation.explicit_due_date != action.explicit_due_date:
        return False
    due_text = (action.due_text or "").casefold()
    return all(
        any(term.casefold() in due_text for term in group) for group in expectation.due_text_groups
    )


def _match_expected_actions(
    expectations: tuple[ExpectedAction, ...], actions: list[ActionItem], client_name: str
) -> set[str]:
    """Return unmatched intent names using one distinct action per expected responsibility."""

    best: frozenset[int] = frozenset()

    def assign(index: int, used: frozenset[int], matched: frozenset[int]) -> None:
        nonlocal best
        if index == len(expectations):
            if len(matched) > len(best):
                best = matched
            return
        assign(index + 1, used, matched)
        for action_index, action in enumerate(actions):
            if action_index not in used and _matches_action(
                expectations[index], action, client_name
            ):
                assign(index + 1, used | {action_index}, matched | {index})

    assign(0, frozenset(), frozenset())
    return {expectation.name for index, expectation in enumerate(expectations) if index not in best}


def evaluate_result(sample: EvaluationSample, result: AnalysisResult) -> list[str]:
    failures: list[str] = []
    checks = {
        "classification": result.classification == sample.classification,
        "client_name": (result.client_name or "").casefold() == sample.client_name.casefold(),
        "policy_number": (result.policy_number or "").upper() == sample.policy_number,
        "policy_status": result.policy_status == sample.policy_status,
        "priority": result.priority in sample.allowed_priorities,
        "action_items.count": len(result.action_items) == len(sample.expected_actions),
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
    failures.extend(
        f"action_items.{name}"
        for name in sorted(
            _match_expected_actions(
                sample.expected_actions, result.action_items, sample.client_name
            )
        )
    )
    return failures
