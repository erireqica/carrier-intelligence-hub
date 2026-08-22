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
from app.core.security import PUBLIC_EMAIL_PROVIDER_DOMAINS, normalize_domain, normalize_email
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
    avatar_url: str | None


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
    dismissed_at: datetime | None
    can_manage_lifecycle: bool


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
    created_at: datetime
    completed_at: datetime | None
    assigned_agent: AgentBrief
    is_manual: bool
    created_by: AgentBrief | None
    completed_by: AgentBrief | None


class TaskListResponse(BaseModel):
    items: list[TaskItem]
    page: PageInfo


class TaskUpdate(BaseModel):
    status: TaskStatus

    model_config = ConfigDict(extra="forbid")


class ManualTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5_000)
    priority: Priority = Priority.NORMAL
    due_date: date | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Task title is required")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class CaseAssignmentInput(BaseModel):
    assigned_agent_id: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


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
    attachment_filename: str | None = None
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
    issue_title: str
    issue_summary: str


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


class ReviewIssueValue(BaseModel):
    source_id: str
    source_label: str
    value: str
    excerpt: str | None = None


class ReviewIssue(BaseModel):
    code: str
    category: str
    title: str
    message: str
    field_name: str | None = None
    human_resolvable: bool
    values: list[ReviewIssueValue] = Field(default_factory=list)


class ReviewDetailResponse(ReviewItemResponse):
    analysis: MessageAnalysisResponse
    issues: list[ReviewIssue] = Field(default_factory=list)


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
    page: PageInfo


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
    case_assigned_agent: AgentBrief | None
    can_open_case: bool
    review_id: int | None
    can_open_review: bool
    last_processing_error_code: str | None
    processing_failure_reason: str | None
    processing_retry_state: str | None
    processing_attempt_count: int
    processing_next_retry_at: datetime | None
    label_sync_status: GmailLabelSyncStatus | None


class GmailMessageListResponse(BaseModel):
    items: list[GmailMessageListItem]
    page: PageInfo


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
    in_progress_tasks: int
    due_soon_tasks: int
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
    avatar_url: str | None


class AgentListResponse(BaseModel):
    items: list[AgentListItem]
    page: PageInfo


class AgentCreateInput(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: InternalEmail = Field(max_length=320)
    initial_password: str = Field(min_length=12, max_length=256)
    confirm_initial_password: str = Field(min_length=12, max_length=256)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Full name must contain at least two characters")
        return normalized

    @model_validator(mode="after")
    def passwords_match(self) -> AgentCreateInput:
        if self.initial_password != self.confirm_initial_password:
            raise ValueError("Initial password and confirmation do not match.")
        return self


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
        if normalized in PUBLIC_EMAIL_PROVIDER_DOMAINS:
            raise ValueError(
                "Public email-provider domains cannot be approved for an entire carrier; "
                "add the specific sender address instead"
            )
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


class AnalyticsBreakdownItem(BaseModel):
    label: str
    count: int
    percentage: float


class AnalyticsTrendItem(BaseModel):
    label: str
    count: int


class CarrierAnalyticsItem(BaseModel):
    carrier_id: int
    carrier_name: str
    messages: int
    automation_rate: float | None
    review_rate: float | None
    failure_rate: float | None


class AttachmentAnalytics(BaseModel):
    pdfs_processed: int
    extracted_successfully: int
    needs_ocr: int
    failed_or_unsupported: int


class AnalyticsResponse(BaseModel):
    range: Literal["7d", "30d", "90d", "all"]
    start_date: date | None
    end_date: date
    carrier_messages: int
    automation_rate: float | None
    review_rate: float | None
    failure_rate: float | None
    average_processing_seconds: float | None
    pdf_extraction_success_rate: float | None
    outcomes: list[AnalyticsBreakdownItem]
    volume_trend: list[AnalyticsTrendItem]
    classifications: list[AnalyticsBreakdownItem]
    carrier_performance: list[CarrierAnalyticsItem]
    attachments: AttachmentAnalytics


class AuditLogItem(BaseModel):
    id: int
    event_type: str
    event_label: str
    category: str
    severity: AuditSeverity
    actor_name: str | None
    actor_user_id: int | None
    description: str
    case_id: int | None
    case_label: str | None = None
    task_id: int | None
    task_title: str | None = None
    review_id: int | None = None
    review_label: str | None = None
    metadata: dict[str, object]
    created_at: datetime


class AuditLogResponse(BaseModel):
    items: list[AuditLogItem]
    page: PageInfo


class ErrorResponse(BaseModel):
    detail: str

    model_config = ConfigDict(extra="forbid")
