from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.evaluation import EVALUATION_SAMPLES, EvaluationSample, evaluate_result
from app.integrations.ai.analyzer import OpenAIAnalyzer
from app.integrations.ai.errors import AnalysisProviderError
from app.integrations.ai.prompt import ANALYSIS_INSTRUCTIONS
from app.integrations.ai.schemas import (
    ActionItem,
    AnalysisResult,
    Deadline,
    Evidence,
    InterpretationAmbiguity,
    InterpretationCandidate,
    SourceFact,
)
from app.models.enums import MessageClassification, PolicyStatus, Priority
from app.processing.ambiguities import verify_interpretation_ambiguities
from app.processing.conflicts import detect_source_conflicts
from app.processing.source import SourceBundle, SourceDocument
from app.processing.validation import validate_analysis


def strong_result(**updates) -> AnalysisResult:
    values = {
        "classification": MessageClassification.PENDING_REQUIREMENTS,
        "summary": "Americo needs an authorization for Test Client.",
        "priority": Priority.HIGH,
        "client_name": "Test Client",
        "policy_number": "test-10001",
        "policy_status": PolicyStatus.PENDING,
        "premium_amount": None,
        "currency": None,
        "effective_date": None,
        "deadline": Deadline(
            raw_text="within 2 business days",
            explicit_date=None,
            relative_count=2,
            relative_unit="BUSINESS_DAYS",
        ),
        "requirements": ["signed authorization"],
        "action_items": [
            ActionItem(
                title="Obtain signed authorization",
                description="Collect the requested authorization.",
                priority=Priority.HIGH,
                explicit_due_date=None,
                due_text="within 2 business days",
            )
        ],
        "evidence": [
            Evidence(field_name="client_name", source_id="email", excerpt="Client: Test Client"),
            Evidence(field_name="policy_number", source_id="email", excerpt="Policy: TEST-10001"),
            Evidence(field_name="policy_status", source_id="email", excerpt="Status: PENDING"),
            Evidence(field_name="deadline", source_id="email", excerpt="within 2 business days"),
            Evidence(
                field_name="action_item:0",
                source_id="email",
                excerpt="signed authorization within 2 business days",
            ),
        ],
        "overall_confidence": 0.95,
        "uncertainties": [],
    }
    values.update(updates)
    return AnalysisResult(**values)


def source_bundle() -> SourceBundle:
    content = (
        "Client: Test Client\nPolicy: TEST-10001\nStatus: PENDING\n"
        "Please return the signed authorization within 2 business days."
    )
    return SourceBundle(
        carrier_name="Americo",
        subject="Pending requirements",
        received_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        documents=(SourceDocument("email", "EMAIL", content),),
        rendered=content,
        truncated=False,
    )


def test_validation_normalizes_identity_and_resolves_business_deadline() -> None:
    validated = validate_analysis(
        strong_result(),
        source_bundle(),
        agency_timezone="America/Chicago",
        confidence_threshold=0.8,
    )

    assert validated.flags == ()
    assert validated.result.policy_number == "TEST-10001"
    assert validated.deadline_at == datetime(2026, 8, 24, 22, tzinfo=UTC)
    assert len(validated.verified_evidence) == 5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$412.50 USD", "412.50"),
        ("USD 1,250.00", "1250.00"),
        ("1,250.00", "1250.00"),
    ],
)
def test_validation_normalizes_common_human_money_formats(raw: str, expected: str) -> None:
    validated = validate_analysis(
        strong_result(premium_amount=raw, currency=None),
        source_bundle(),
        agency_timezone="UTC",
        confidence_threshold=0.8,
        require_evidence=False,
    )

    assert "INVALID_PREMIUM" not in validated.flags
    assert validated.result.premium_amount == expected
    expected_currency = "USD" if "USD" in raw or "$" in raw else None
    assert validated.result.currency == expected_currency


def test_validation_routes_inline_and_structured_currency_conflict() -> None:
    validated = validate_analysis(
        strong_result(premium_amount="$412.50 USD", currency="EUR"),
        source_bundle(),
        agency_timezone="UTC",
        confidence_threshold=0.8,
        require_evidence=False,
    )

    assert "CURRENCY_CONFLICT" in validated.flags


def test_source_conflicts_ignore_formatting_but_detect_material_differences() -> None:
    email = "Client: SOPHIE BENNETT\nPolicy: abc-123\nPremium: $412.50 USD\nStatus: ACTIVE"
    matching_pdf = (
        "Client Name: Sophie Bennett\nPolicy Number: ABC-123\n"
        "Premium Amount: USD 412.50\nPolicy Status: ACTIVE"
    )
    conflicting_pdf = matching_pdf.replace("ABC-123", "ABC-128").replace("USD 412.50", "EUR 475.00")
    base = dict(
        carrier_name="Americo",
        subject="Policy update",
        received_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        rendered="",
        truncated=False,
    )

    matching = detect_source_conflicts(
        SourceBundle(
            **base,
            documents=(
                SourceDocument("email", "EMAIL", email),
                SourceDocument("attachment:1", "PDF", matching_pdf, 1),
            ),
        )
    )
    conflicting = detect_source_conflicts(
        SourceBundle(
            **base,
            documents=(
                SourceDocument("email", "EMAIL", email),
                SourceDocument("attachment:1", "PDF", conflicting_pdf, 1),
            ),
        )
    )

    assert matching == ()
    assert {item.code for item in conflicting} == {
        "CURRENCY_CONFLICT",
        "POLICY_NUMBER_CONFLICT",
        "PREMIUM_CONFLICT",
    }


def test_source_classification_status_contradiction_is_a_real_conflict() -> None:
    content = "Notice Type: POLICY ISSUED\nPolicy Status: PENDING"
    bundle = SourceBundle(
        carrier_name="Americo",
        subject="Contradictory notice",
        received_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        documents=(SourceDocument("email", "EMAIL", content),),
        rendered=content,
        truncated=False,
    )

    conflicts = detect_source_conflicts(bundle)

    assert [item.code for item in conflicts] == ["POLICY_STATUS_CONFLICT"]


def natural_bundle(email: str, pdf: str | None = None) -> SourceBundle:
    documents = [SourceDocument("email", "EMAIL", email)]
    if pdf is not None:
        documents.append(SourceDocument("attachment:7", "PDF", pdf, 7))
    return SourceBundle(
        carrier_name="Americo",
        subject="Natural policy communication",
        received_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        documents=tuple(documents),
        rendered="",
        truncated=False,
    )


@pytest.mark.parametrize(
    ("field_name", "email", "email_value", "pdf", "pdf_value", "expected_code"),
    [
        (
            "premium_amount",
            "We have issued policy NAT-100 for John Smith. The annual premium will be $400.",
            "400.00",
            "Policy NAT-100 has an annual premium of $450.",
            "450.00",
            "PREMIUM_CONFLICT",
        ),
        (
            "policy_number",
            "We have issued policy ABC123 for John Smith.",
            "ABC123",
            "Coverage under policy ABC128 is now active.",
            "ABC128",
            "POLICY_NUMBER_CONFLICT",
        ),
        (
            "client_name",
            "We have issued the policy for Sophie Bennett.",
            "Sophie Bennett",
            "This policy is issued to Sophie Bennet.",
            "Sophie Bennet",
            "CLIENT_IDENTITY_CONFLICT",
        ),
    ],
)
def test_verified_natural_source_facts_detect_material_conflicts(
    field_name: str,
    email: str,
    email_value: str,
    pdf: str,
    pdf_value: str,
    expected_code: str,
) -> None:
    facts = [
        SourceFact(
            field_name=field_name,
            value=email_value,
            source_id="email",
            excerpt=email,
        ),
        SourceFact(
            field_name=field_name,
            value=pdf_value,
            source_id="attachment:7",
            excerpt=pdf,
        ),
    ]

    conflicts = detect_source_conflicts(natural_bundle(email, pdf), facts)

    conflict = next(item for item in conflicts if item.code == expected_code)
    assert {item.source_id for item in conflict.values} == {"email", "attachment:7"}
    assert {item.excerpt for item in conflict.values} == {email, pdf}


def test_verified_natural_premium_facts_detect_currency_conflict() -> None:
    email = "The annual premium will be $400."
    pdf = "The annual premium under the contract is EUR 400."
    facts = [
        SourceFact(
            field_name="premium_amount",
            value="400.00",
            source_id="email",
            excerpt=email,
        ),
        SourceFact(
            field_name="premium_amount",
            value="400",
            source_id="attachment:7",
            excerpt=pdf,
        ),
    ]

    conflicts = detect_source_conflicts(natural_bundle(email, pdf), facts)

    assert {item.code for item in conflicts} == {"CURRENCY_CONFLICT"}


def test_equivalent_natural_money_facts_are_canonicalized_before_comparison() -> None:
    email = "The annual premium is $1,250."
    pdf = "Premium payable is USD 1250.00."
    facts = [
        SourceFact(
            field_name="premium_amount",
            value="1250",
            source_id="email",
            excerpt=email,
        ),
        SourceFact(
            field_name="premium_amount",
            value="USD 1250.00",
            source_id="attachment:7",
            excerpt=pdf,
        ),
    ]

    assert detect_source_conflicts(natural_bundle(email, pdf), facts) == ()


def test_historical_people_and_unsupported_source_facts_do_not_create_conflicts() -> None:
    content = (
        "The policy was previously pending but has now been issued. "
        "Agent Jane Miller confirms that client John Smith's policy has been issued. "
        "The annual premium is $400."
    )
    facts = [
        SourceFact(
            field_name="policy_status",
            value="ISSUED",
            source_id="email",
            excerpt="The policy was previously pending but has now been issued.",
        ),
        SourceFact(
            field_name="client_name",
            value="John Smith",
            source_id="email",
            excerpt="Agent Jane Miller confirms that client John Smith's policy has been issued.",
        ),
        SourceFact(
            field_name="premium_amount",
            value="999",
            source_id="email",
            excerpt="The annual premium is $400.",
        ),
        SourceFact(
            field_name="premium_amount",
            value="450",
            source_id="attachment:missing",
            excerpt="The annual premium is $450.",
        ),
    ]

    assert detect_source_conflicts(natural_bundle(content), facts) == ()


def test_old_analysis_json_without_source_facts_remains_loadable() -> None:
    old_json = strong_result().model_dump(
        mode="json", exclude={"source_facts", "interpretation_ambiguities"}
    )

    restored = AnalysisResult.model_validate(old_json)
    version_two_json = strong_result().model_dump(
        mode="json", exclude={"interpretation_ambiguities"}
    )
    restored_v2 = AnalysisResult.model_validate(version_two_json)

    assert restored.source_facts == []
    assert restored.interpretation_ambiguities == []
    assert restored_v2.interpretation_ambiguities == []


def test_interpretation_ambiguity_requires_two_distinct_grounded_candidates() -> None:
    content = (
        "Policy ABC and policy XYZ are both discussed. "
        "This requirement must be completed before approval."
    )
    bundle = natural_bundle(content)
    ambiguity = InterpretationAmbiguity(
        field_name="requirement_association",
        explanation="The pronoun may refer to either policy.",
        candidates=[
            InterpretationCandidate(
                interpretation="The requirement applies to policy ABC.",
                source_id="email",
                excerpt="This requirement must be completed before approval.",
            ),
            InterpretationCandidate(
                interpretation="The requirement applies to policy XYZ.",
                source_id="email",
                excerpt="This requirement must be completed before approval.",
            ),
        ],
    )
    hallucinated = ambiguity.model_copy(
        update={
            "candidates": [
                ambiguity.candidates[0],
                ambiguity.candidates[1].model_copy(
                    update={"excerpt": "This passage does not exist."}
                ),
            ]
        }
    )

    verified = verify_interpretation_ambiguities(bundle, [ambiguity])

    assert len(verified) == 1
    assert len(verified[0].candidates) == 2
    assert verify_interpretation_ambiguities(bundle, [hallucinated]) == ()


def test_validation_routes_low_confidence_contradiction_and_hallucinated_evidence() -> None:
    evidence = strong_result().evidence
    evidence[0] = Evidence(
        field_name="client_name", source_id="email", excerpt="Client: Hallucinated Person"
    )
    validated = validate_analysis(
        strong_result(
            classification=MessageClassification.LAPSE_NOTICE,
            policy_status=PolicyStatus.ISSUED,
            overall_confidence=0.5,
            evidence=evidence,
        ),
        source_bundle(),
        agency_timezone="UTC",
        confidence_threshold=0.8,
    )

    assert {"LOW_CONFIDENCE", "CLASSIFICATION_STATUS_MISMATCH", "EVIDENCE_MISMATCH"} <= set(
        validated.flags
    )
    assert all(
        item.proposal.excerpt != "Client: Hallucinated Person"
        for item in validated.verified_evidence
    )


def test_validation_routes_invalid_action_due_date_to_review() -> None:
    action = strong_result().action_items[0].model_copy(update={"explicit_due_date": "2026-02-30"})
    validated = validate_analysis(
        strong_result(action_items=[action]),
        source_bundle(),
        agency_timezone="UTC",
        confidence_threshold=0.8,
    )

    assert "INVALID_DATE" in validated.flags


def test_validation_routes_competing_deadline_forms_to_review() -> None:
    deadline = Deadline(
        raw_text="within 2 days by 2026-08-24",
        explicit_date="2026-08-24",
        relative_count=2,
        relative_unit="BUSINESS_DAYS",
    )
    validated = validate_analysis(
        strong_result(deadline=deadline),
        source_bundle(),
        agency_timezone="UTC",
        confidence_threshold=0.8,
    )

    assert "INVALID_DEADLINE" in validated.flags


def test_policy_evidence_must_support_the_proposed_policy_value() -> None:
    evidence = strong_result().evidence
    evidence[1] = evidence[1].model_copy(update={"excerpt": "Policy: TEST-10001"})
    validated = validate_analysis(
        strong_result(policy_number="TEST-99999", evidence=evidence),
        source_bundle(),
        agency_timezone="UTC",
        confidence_threshold=0.8,
    )

    assert "EVIDENCE_MISMATCH" in validated.flags
    assert all(item.proposal.field_name != "policy_number" for item in validated.verified_evidence)


def test_client_evidence_supports_comma_order_but_rejects_another_name() -> None:
    content = (
        source_bundle().documents[0].content.replace("Client: Test Client", "Client: Smith, Mary")
    )
    bundle = SourceBundle(
        carrier_name="Americo",
        subject="Pending requirements",
        received_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        documents=(SourceDocument("email", "EMAIL", content),),
        rendered=content,
        truncated=False,
    )
    evidence = strong_result().evidence
    evidence[0] = evidence[0].model_copy(update={"excerpt": "Client: Smith, Mary"})
    correct = validate_analysis(
        strong_result(client_name="Mary Smith", evidence=evidence),
        bundle,
        agency_timezone="UTC",
        confidence_threshold=0.8,
        require_evidence=False,
    )
    wrong = validate_analysis(
        strong_result(client_name="Robert Johnson", evidence=evidence),
        bundle,
        agency_timezone="UTC",
        confidence_threshold=0.8,
        require_evidence=False,
    )

    assert "EVIDENCE_MISMATCH" not in correct.flags
    assert "EVIDENCE_MISMATCH" in wrong.flags


def test_validation_normalizes_structured_action_evidence_index_alias() -> None:
    evidence = strong_result().evidence
    evidence[-1] = evidence[-1].model_copy(update={"field_name": "action_items[0]"})
    validated = validate_analysis(
        strong_result(evidence=evidence),
        source_bundle(),
        agency_timezone="UTC",
        confidence_threshold=0.8,
    )

    assert validated.flags == ()
    assert validated.verified_evidence[-1].proposal.field_name == "action_item:0"


def test_validation_routes_missing_identity_and_invalid_money_to_review() -> None:
    validated = validate_analysis(
        strong_result(
            policy_number=None,
            premium_amount="not-money",
            currency="US",
            effective_date="09/01/2026",
        ),
        source_bundle(),
        agency_timezone="UTC",
        confidence_threshold=0.8,
    )

    assert {"MISSING_POLICY_NUMBER", "INVALID_PREMIUM", "INVALID_DATE"} <= set(validated.flags)


def test_openai_analyzer_uses_responses_structured_output_without_storage_or_tools() -> None:
    result = strong_result()
    calls: list[dict] = []

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_parsed=result, output=[])

    client = SimpleNamespace(responses=FakeResponses())
    settings = Settings(openai_api_key=SecretStr("synthetic-test-key"), openai_model="gpt-5.6")
    analyzer = OpenAIAnalyzer(settings, client=client)

    assert analyzer.analyze("synthetic source") == result
    assert calls[0]["store"] is False
    assert calls[0]["tools"] == []
    assert calls[0]["text_format"] is AnalysisResult
    assert calls[0]["instructions"] == ANALYSIS_INSTRUCTIONS
    assert "untrusted data" in ANALYSIS_INSTRUCTIONS
    assert "deadline in exactly one form" in ANALYSIS_INSTRUCTIONS
    assert "use USD" in ANALYSIS_INSTRUCTIONS
    assert "YYYY-MM-DD" in ANALYSIS_INSTRUCTIONS
    assert "action_item:N" in ANALYSIS_INSTRUCTIONS
    assert "source_facts" in ANALYSIS_INSTRUCTIONS
    assert "competing current facts" in " ".join(ANALYSIS_INSTRUCTIONS.split()).lower()
    assert "interpretation_ambiguity" in ANALYSIS_INSTRUCTIONS
    assert "clarification is required" in " ".join(ANALYSIS_INSTRUCTIONS.split()).lower()
    assert "operational next step" in ANALYSIS_INSTRUCTIONS
    assert "do not collapse" in ANALYSIS_INSTRUCTIONS
    assert "PENDING_REQUIREMENTS" in ANALYSIS_INSTRUCTIONS
    assert "POLICY_ISSUED" in ANALYSIS_INSTRUCTIONS
    assert "LAPSE_NOTICE" in ANALYSIS_INSTRUCTIONS
    assert "explicit_due_date to exactly the normalized effective_date" in ANALYSIS_INSTRUCTIONS
    assert "John Doe" not in ANALYSIS_INSTRUCTIONS
    assert "Mary Smith" not in ANALYSIS_INSTRUCTIONS
    assert "Robert Johnson" not in ANALYSIS_INSTRUCTIONS


def test_openai_analyzer_routes_refusal_and_invalid_response_without_raw_detail() -> None:
    settings = Settings(openai_api_key=SecretStr("synthetic-test-key"))
    refusal = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **kwargs: SimpleNamespace(output_parsed=None, output=[])
        )
    )
    with pytest.raises(AnalysisProviderError) as refused:
        OpenAIAnalyzer(settings, client=refusal).analyze("synthetic source")
    assert refused.value.code == "AI_REFUSAL"
    assert refused.value.reviewable is True

    def invalid(**kwargs):
        raise ValueError("synthetic raw content that must not escape")

    broken = SimpleNamespace(responses=SimpleNamespace(parse=invalid))
    with pytest.raises(AnalysisProviderError) as malformed:
        OpenAIAnalyzer(settings, client=broken).analyze("synthetic source")
    assert malformed.value.code == "AI_INVALID_RESPONSE"
    assert "synthetic raw" not in str(malformed.value)


def _evaluation_result(sample: EvaluationSample, actions: list[ActionItem]) -> AnalysisResult:
    deadline = Deadline(
        raw_text=(
            "within 10 business days"
            if sample.deadline_relative_count is not None
            else "September 15, 2026"
            if sample.deadline_date is not None
            else None
        ),
        explicit_date=sample.deadline_date,
        relative_count=sample.deadline_relative_count,
        relative_unit=sample.deadline_relative_unit,
    )
    return AnalysisResult(
        classification=sample.classification,
        summary="Grounded carrier communication requiring operational follow-up.",
        priority=sample.allowed_priorities[0],
        client_name=sample.client_name,
        policy_number=sample.policy_number,
        policy_status=sample.policy_status,
        premium_amount=(str(sample.premium_amount) if sample.premium_amount is not None else None),
        currency=sample.currency,
        effective_date=sample.effective_date,
        deadline=deadline,
        requirements=[],
        action_items=actions,
        evidence=[],
        overall_confidence=0.95,
        uncertainties=[],
    )


ASSIGNMENT_ACTIONS = (
    [
        ActionItem(
            title="Obtain signed HIPAA authorization form",
            description=None,
            priority=Priority.HIGH,
            explicit_due_date=None,
            due_text=None,
        ),
        ActionItem(
            title="Clarify medical history for 04/12/2026 prescription",
            description=None,
            priority=Priority.HIGH,
            explicit_due_date=None,
            due_text=None,
        ),
        ActionItem(
            title="Submit completed requirement documents",
            description=None,
            priority=Priority.HIGH,
            explicit_due_date=None,
            due_text="within 10 business days",
        ),
    ],
    [
        ActionItem(
            title="Notify client that the issued policy packet was mailed",
            description=None,
            priority=Priority.NORMAL,
            explicit_due_date=None,
            due_text=None,
        ),
        ActionItem(
            title="Verify first premium draft",
            description=None,
            priority=Priority.NORMAL,
            explicit_due_date="2026-09-01",
            due_text="on the effective date",
        ),
    ],
    [
        ActionItem(
            title="Call client about returned NSF payment of $89.50",
            description=None,
            priority=Priority.URGENT,
            explicit_due_date=None,
            due_text="ASAP",
        ),
        ActionItem(
            title="Update banking information in portal to prevent lapse",
            description=None,
            priority=Priority.URGENT,
            explicit_due_date="2026-09-15",
            due_text="before the lapse deadline",
        ),
    ],
)


def test_assignment_evaluation_inputs_are_verbatim_and_do_not_supply_aetna_actions() -> None:
    assert (
        EVALUATION_SAMPLES[0].bundle.documents[0].content
        == """Dear Agent,
We are currently reviewing the Final Expense application for your client, John Doe.
Policy # AMR-98765432 is currently in PENDING status.
To proceed with underwriting, we require a completed HIPAA authorization form
and a clarification on the medical history questionnaire regarding a prescription
filled on 04/12/2026. Please have the client sign the attached addendum and return
it within 10 business days to avoid application closure.
Thank you,
Americo Underwriting Team"""
    )
    aetna_body = EVALUATION_SAMPLES[1].bundle.documents[0].content
    assert (
        aetna_body
        == """Good morning,
This email is to confirm that the Medicare Supplement policy for Mary Smith has
been APPROVED and ISSUED.
Policy Number: ATN-554433221
Effective Date: 09/01/2026
Monthly Premium: $145.00
The physical policy packet has been mailed directly to the client's address on file.
Your commission will be reflected on your next weekly statement.
Regards,
Aetna Senior Supplemental Insurance"""
    )
    assert "Notify the client" not in aetna_body
    assert "verify the first premium" not in aetna_body
    assert (
        EVALUATION_SAMPLES[2].bundle.documents[0].content
        == """Agent Notification:
Please be advised that the premium payment for Policy # AA-1122334 (Insured:
Robert Johnson) was returned due to insufficient funds (NSF).
The policy is currently in its 31-day grace period. If the past-due amount of $89.50
is not received by September 15, 2026, the policy will lapse. We have sent a
notification letter to the insured. Please reach out to your client to update their
banking information on the agent portal.
American Amicable Life Insurance Company of Texas"""
    )


@pytest.mark.parametrize(
    ("sample", "actions"), tuple(zip(EVALUATION_SAMPLES, ASSIGNMENT_ACTIONS, strict=True))
)
def test_assignment_evaluation_requires_exact_distinct_action_semantics_and_dates(
    sample: EvaluationSample, actions: list[ActionItem]
) -> None:
    assert evaluate_result(sample, _evaluation_result(sample, actions)) == []


def test_assignment_evaluation_rejects_collapsed_missing_and_extra_actions() -> None:
    americo = EVALUATION_SAMPLES[0]
    collapsed = ActionItem(
        title=("Obtain HIPAA authorization, clarify 04/12/2026 prescription, and submit documents"),
        description=None,
        priority=Priority.HIGH,
        explicit_due_date=None,
        due_text="within 10 business days",
    )
    failures = evaluate_result(americo, _evaluation_result(americo, [collapsed]))
    assert "action_items.count" in failures
    assert len([failure for failure in failures if failure.startswith("action_items.")]) >= 3

    aetna = EVALUATION_SAMPLES[1]
    wrong_date = ASSIGNMENT_ACTIONS[1][1].model_copy(update={"explicit_due_date": "2026-09-02"})
    failures = evaluate_result(
        aetna,
        _evaluation_result(aetna, [ASSIGNMENT_ACTIONS[1][0], wrong_date]),
    )
    assert "action_items.verify_first_premium" in failures


@pytest.mark.parametrize(
    ("sample_index", "carrier", "identity", "policy", "body", "actions"),
    [
        (
            0,
            "Northstar Life",
            "Alex Rivera",
            "NEW-100",
            (
                "Alex Rivera's policy NEW-100 is pending. Obtain HIPAA consent and explain the "
                "questionnaire medication dated 04/12/2026. Return the requirement package "
                "within 10 business days."
            ),
            [
                ActionItem(
                    title="Collect HIPAA consent",
                    description=None,
                    priority=Priority.HIGH,
                    explicit_due_date=None,
                    due_text=None,
                ),
                ActionItem(
                    title="Explain questionnaire medication dated 04/12/2026",
                    description=None,
                    priority=Priority.HIGH,
                    explicit_due_date=None,
                    due_text=None,
                ),
                ActionItem(
                    title="Return requirement package",
                    description=None,
                    priority=Priority.HIGH,
                    explicit_due_date=None,
                    due_text="within 10 business days",
                ),
            ],
        ),
        (
            1,
            "Harbor Mutual",
            "Taylor Brooks",
            "NEW-200",
            (
                "Harbor Mutual approved and issued policy NEW-200 for Taylor Brooks. The packet "
                "was electronically delivered. The $145.00 first premium and effective date are "
                "09/01/2026."
            ),
            [
                ActionItem(
                    title="Inform insured the approved packet was delivered",
                    description=None,
                    priority=Priority.NORMAL,
                    explicit_due_date=None,
                    due_text=None,
                ),
                ActionItem(
                    title="Confirm initial premium payment",
                    description=None,
                    priority=Priority.NORMAL,
                    explicit_due_date="2026-09-01",
                    due_text=None,
                ),
            ],
        ),
        (
            2,
            "Summit Assurance",
            "Jordan Chen",
            "NEW-300",
            (
                "Policy NEW-300 for Jordan Chen is in its grace period after an $89.50 payment "
                "was returned for insufficient funds. Update bank details in the portal before "
                "09/15/2026 to avoid lapse."
            ),
            [
                ActionItem(
                    title="Reach out to insured about insufficient funds of $89.50",
                    description=None,
                    priority=Priority.HIGH,
                    explicit_due_date=None,
                    due_text=None,
                ),
                ActionItem(
                    title="Correct bank details in portal to avoid lapse",
                    description=None,
                    priority=Priority.HIGH,
                    explicit_due_date="2026-09-15",
                    due_text=None,
                ),
            ],
        ),
    ],
)
def test_action_semantics_generalize_to_new_identities_and_equivalent_wording(
    sample_index: int,
    carrier: str,
    identity: str,
    policy: str,
    body: str,
    actions: list[ActionItem],
) -> None:
    bundle = SourceBundle(
        carrier_name=carrier,
        subject="Synthetic operational communication",
        received_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        documents=(SourceDocument("email", "EMAIL", body),),
        rendered=body,
        truncated=False,
    )
    sample = replace(
        EVALUATION_SAMPLES[sample_index],
        name=f"Generalized {sample_index}",
        bundle=bundle,
        client_name=identity,
        policy_number=policy,
    )

    assert evaluate_result(sample, _evaluation_result(sample, actions)) == []
