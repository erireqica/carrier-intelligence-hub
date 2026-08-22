from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import MessageClassification, PolicyStatus, Priority

ANALYSIS_SCHEMA_VERSION = "3"

SOURCE_FACT_FIELDS = Literal[
    "client_name",
    "policy_number",
    "policy_status",
    "classification",
    "premium_amount",
    "currency",
    "effective_date",
]

INTERPRETATION_FIELDS = Literal[
    "client_name",
    "policy_number",
    "policy_status",
    "classification",
    "premium_amount",
    "currency",
    "effective_date",
    "deadline",
    "requirement_association",
    "case_association",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Deadline(StrictModel):
    raw_text: str | None
    explicit_date: str | None
    relative_count: int | None = Field(ge=1, le=365)
    relative_unit: Literal["BUSINESS_DAYS", "CALENDAR_DAYS"] | None

    @model_validator(mode="after")
    def validate_shape(self) -> Deadline:
        if (self.relative_count is None) != (self.relative_unit is None):
            raise ValueError("Relative deadline count and unit must be supplied together")
        return self


class ActionItem(StrictModel):
    title: str = Field(min_length=3, max_length=300)
    description: str | None = Field(max_length=2_000)
    priority: Priority
    explicit_due_date: str | None
    due_text: str | None = Field(max_length=500)

    @field_validator("title", "description", "due_text")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class Evidence(StrictModel):
    field_name: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=100)
    excerpt: str = Field(min_length=1, max_length=500)


class SourceFact(StrictModel):
    field_name: SOURCE_FACT_FIELDS
    value: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=100)
    excerpt: str = Field(min_length=1, max_length=500)

    @field_validator("value", "source_id", "excerpt")
    @classmethod
    def strip_fact_text(cls, value: str) -> str:
        return " ".join(value.split())


class InterpretationCandidate(StrictModel):
    interpretation: str = Field(min_length=1, max_length=300)
    source_id: str = Field(min_length=1, max_length=100)
    excerpt: str = Field(min_length=1, max_length=500)

    @field_validator("interpretation", "source_id", "excerpt")
    @classmethod
    def strip_candidate_text(cls, value: str) -> str:
        return " ".join(value.split())


class InterpretationAmbiguity(StrictModel):
    field_name: INTERPRETATION_FIELDS
    explanation: str = Field(min_length=1, max_length=500)
    candidates: list[InterpretationCandidate] = Field(min_length=2, max_length=4)

    @field_validator("explanation")
    @classmethod
    def strip_explanation(cls, value: str) -> str:
        return " ".join(value.split())


class AnalysisResult(StrictModel):
    classification: MessageClassification
    summary: str = Field(min_length=1, max_length=2_000)
    priority: Priority
    client_name: str | None = Field(max_length=200)
    policy_number: str | None = Field(max_length=100)
    policy_status: PolicyStatus
    premium_amount: str | None = Field(max_length=40)
    currency: str | None = Field(max_length=3)
    effective_date: str | None = Field(max_length=20)
    deadline: Deadline
    requirements: list[str] = Field(max_length=30)
    action_items: list[ActionItem] = Field(max_length=8)
    evidence: list[Evidence] = Field(max_length=40)
    source_facts: list[SourceFact] = Field(default_factory=list, max_length=24)
    interpretation_ambiguities: list[InterpretationAmbiguity] = Field(
        default_factory=list, max_length=5
    )
    overall_confidence: float = Field(ge=0, le=1)
    uncertainties: list[str] = Field(max_length=20)

    @field_validator("summary", "client_name", "policy_number", "currency")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @field_validator("requirements", "uncertainties")
    @classmethod
    def normalize_list(cls, values: list[str]) -> list[str]:
        return [normalized for value in values if (normalized := " ".join(value.split()))]


class HumanAnalysisInput(StrictModel):
    classification: MessageClassification
    summary: str = Field(min_length=1, max_length=2_000)
    priority: Priority
    client_name: str | None = Field(max_length=200)
    policy_number: str | None = Field(max_length=100)
    policy_status: PolicyStatus
    premium_amount: str | None = Field(max_length=40)
    currency: str | None = Field(max_length=3)
    effective_date: str | None = Field(max_length=20)
    deadline: Deadline
    requirements: list[str] = Field(default_factory=list, max_length=30)
    action_items: list[ActionItem] = Field(max_length=8)
