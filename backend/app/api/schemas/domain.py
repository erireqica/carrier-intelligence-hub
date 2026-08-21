from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.api.schemas.common import InternalEmail
from app.core.security import normalize_domain, normalize_email
from app.integrations.ai.schemas import AnalysisResult
from app.models.enums import (
    AttachmentStatus,
    AuditSeverity,
    GmailConnectionStatus,
    GmailHealth,
    GmailLabelSyncStatus,
    MessageClassification,
    PolicyStatus,
    Priority,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
    UserRole,
)


class PageInfo(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class CarrierBrief(BaseModel):
    id: int
    name: str
    code: str | None


class AgentBrief(BaseModel):
    id: int
    full_name: str
    email: InternalEmail


class CaseListItem(BaseModel):
    id: int
    client_name: str
    policy_number: str | None
    policy_status: PolicyStatus
    priority: Priority
    summary: str
    deadline: date | None
    updated_at: datetime
    carrier: CarrierBrief
    assigned_agent: AgentBrief | None
    needs_review: bool


class CaseListResponse(BaseModel):
    items: list[CaseListItem]
    page: PageInfo


class TaskItem(BaseModel):
    id: int
    case_id: int
    client_name: str
    policy_number: str | None
    title: str
    description: str | None
    priority: Priority
    due_at: date | None
    status: TaskStatus
    completed_at: datetime | None
    assigned_agent: AgentBrief


class TaskListResponse(BaseModel):
    items: list[TaskItem]
    page: PageInfo


class TaskUpdate(BaseModel):
    status: TaskStatus | None = None
    assigned_agent_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_supported_change(self) -> TaskUpdate:
        if self.status is None and self.assigned_agent_id is None:
            raise ValueError("Provide status or assigned_agent_id")
        return self


class CaseCorrectionInput(BaseModel):
    client_name: str = Field(min_length=1, max_length=200)
    policy_number: str | None = Field(default=None, max_length=100)
    policy_status: PolicyStatus
    priority: Priority
    summary: str = Field(min_length=1, max_length=5_000)
    premium_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    effective_date: date | None = None
    deadline: date | None = None
    reason: str = Field(min_length=3, max_length=1_000)

    @field_validator("client_name", "summary", "reason")
    @classmethod
    def strip_required_text(cls, value: str, info) -> str:
        normalized = value.strip()
        minimum = 3 if info.field_name == "reason" else 1
        if len(normalized) < minimum:
            raise ValueError(f"{info.field_name.replace('_', ' ').title()} is too short")
        return normalized

    @field_validator("policy_number")
    @classmethod
    def normalize_policy_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class MessageItem(BaseModel):
    id: int
    sender: str
    subject: str
    received_at: datetime
    classification: MessageClassification | None
    summary: str | None
    priority: Priority | None
    processing_status: ProcessingStatus
    cleaned_content: str
    original_deadline_text: str | None
    analysis_confidence: float | None
    validation_flags: list[str]
    review_id: int | None


class AttachmentItem(BaseModel):
    id: int
    filename: str
    mime_type: str
    size_bytes: int
    processing_status: AttachmentStatus
    page_count: int | None
    extraction_error_code: str | None
    extracted_text_preview: str | None


class EvidenceItem(BaseModel):
    id: int
    field_name: str
    source_type: str
    excerpt: str


class ActivityItem(BaseModel):
    id: int
    event_type: str
    severity: AuditSeverity
    description: str
    created_at: datetime


class CaseDetail(CaseListItem):
    premium_amount: Decimal | None
    currency: str | None
    effective_date: date | None
    messages: list[MessageItem]
    attachments: list[AttachmentItem]
    tasks: list[TaskItem]
    evidence: list[EvidenceItem]
    activity: list[ActivityItem]


class ReviewItemResponse(BaseModel):
    id: int
    message_id: int
    case_id: int | None
    client_name: str | None
    policy_number: str | None
    carrier_name: str
    message_subject: str
    reason_code: str
    reason: str
    status: ReviewStatus
    resolution_notes: str | None
    assigned_reviewer: AgentBrief | None
    created_at: datetime
    resolved_at: datetime | None
    analysis_confidence: float | None


class MessageAnalysisResponse(BaseModel):
    message_id: int
    carrier_name: str
    processing_status: ProcessingStatus
    case_id: int | None
    review_id: int | None
    model_name: str | None
    schema_version: str | None
    prompt_version: str | None
    overall_confidence: float | None
    validation_flags: list[str]
    proposed_result: AnalysisResult | None
    final_result: AnalysisResult | None
    source_content: str
    attachments: list[AttachmentItem]


class ReviewDetailResponse(ReviewItemResponse):
    analysis: MessageAnalysisResponse


class ReviewListResponse(BaseModel):
    items: list[ReviewItemResponse]
    page: PageInfo


class ReviewUpdate(BaseModel):
    status: Literal[ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]
    resolution_notes: str | None = Field(default=None, max_length=2000)


class GmailConnectionItem(BaseModel):
    id: int
    gmail_address: EmailStr
    owner: AgentBrief
    status: GmailConnectionStatus
    connected_at: datetime | None
    last_successful_sync_at: datetime | None
    last_attempted_sync_at: datetime | None
    last_error_summary: str | None
    is_owner: bool
    can_apply_workflow_labels: bool
    pending_label_sync_count: int = 0
    failed_label_sync_count: int = 0


class GmailConnectionsResponse(BaseModel):
    configured: bool
    connections: list[GmailConnectionItem]


class GmailOAuthStartRequest(BaseModel):
    reconnect_connection_id: int | None = Field(default=None, gt=0)


class GmailOAuthStartResponse(BaseModel):
    authorization_url: AnyHttpUrl


class GmailSyncResult(BaseModel):
    connection_id: int
    messages_seen: int
    already_ingested: int
    approved: int
    ingested: int
    skipped_unapproved: int
    attachments_discovered: int


class GmailMessageListItem(BaseModel):
    id: int
    carrier: CarrierBrief
    sender: str
    subject: str
    received_at: datetime
    processing_status: ProcessingStatus
    attachment_count: int
    case_id: int | None
    review_id: int | None
    last_processing_error_code: str | None
    processing_attempt_count: int
    processing_next_retry_at: datetime | None
    label_sync_status: GmailLabelSyncStatus | None


class MessageProcessingResult(BaseModel):
    message_id: int
    processing_status: ProcessingStatus
    case_id: int | None
    review_id: int | None
    tasks_created: int
    attachments_extracted: int
    analysis_confidence: float | None
    validation_flags: list[str]


class ReviewDismissRequest(BaseModel):
    resolution_notes: str | None = Field(default=None, max_length=2_000)


class DashboardMetrics(BaseModel):
    urgent_cases: int
    open_tasks: int
    overdue_tasks: int
    review_items: int
    processing_failures: int
    processed_messages: int
    gmail_connections_needing_attention: int
    received_backlog: int
    processing_messages: int
    retry_scheduled: int
    failed_requiring_attention: int
    gmail_labels_pending: int
    gmail_labels_requiring_attention: int
    oldest_unprocessed_age_seconds: int | None


class WorkloadItem(BaseModel):
    agent: AgentBrief
    open_tasks: int


class DashboardResponse(BaseModel):
    metrics: DashboardMetrics
    recent_cases: list[CaseListItem]
    recent_activity: list[ActivityItem]
    workload: list[WorkloadItem]
    gmail_connected: bool
    gmail_health: GmailHealth


class AgentListItem(BaseModel):
    id: int
    full_name: str
    email: InternalEmail
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    open_tasks: int
    urgent_cases: int
    gmail_connections: int


class CarrierDomainItem(BaseModel):
    id: int
    domain: str
    is_enabled: bool


class CarrierSenderItem(BaseModel):
    id: int
    email: EmailStr
    is_enabled: bool


class CarrierItem(BaseModel):
    id: int
    name: str
    code: str | None
    notes: str | None
    is_enabled: bool
    domains: list[CarrierDomainItem]
    senders: list[CarrierSenderItem]


class CarrierWrite(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    code: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    is_enabled: bool = True


class DomainWrite(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    is_enabled: bool = True

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        normalized = normalize_domain(value)
        labels = normalized.split(".")
        if len(labels) < 2 or any(
            not label or not label.replace("-", "").isalnum() for label in labels
        ):
            raise ValueError("Enter a valid domain")
        return normalized


class SenderWrite(BaseModel):
    email: EmailStr
    is_enabled: bool = True

    @field_validator("email")
    @classmethod
    def normalize_sender(cls, value: EmailStr) -> str:
        return normalize_email(str(value))


class EnabledUpdate(BaseModel):
    is_enabled: bool


class AnalyticsResponse(BaseModel):
    cases_by_status: dict[str, int]
    cases_by_carrier: dict[str, int]
    workload_by_agent: list[WorkloadItem]
    urgent_high_cases: int
    open_tasks: int
    overdue_tasks: int
    open_reviews: int
    processed_messages: int
    failed_messages: int


class AuditLogItem(BaseModel):
    id: int
    event_type: str
    severity: AuditSeverity
    actor_name: str | None
    actor_user_id: int | None
    description: str
    case_id: int | None
    case_label: str | None = None
    task_id: int | None
    task_title: str | None = None
    metadata: dict[str, object]
    created_at: datetime


class AuditLogResponse(BaseModel):
    items: list[AuditLogItem]
    page: PageInfo


class ErrorResponse(BaseModel):
    detail: str

    model_config = ConfigDict(extra="forbid")
