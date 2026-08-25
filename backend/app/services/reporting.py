from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.schemas.domain import (
    ActivityItem,
    AgentListItem,
    AgentListResponse,
    AnalyticsBreakdownItem,
    AnalyticsResponse,
    AnalyticsTrendItem,
    AttachmentAnalytics,
    AuditLogItem,
    AuditLogResponse,
    CarrierAnalyticsItem,
    DashboardMetrics,
    DashboardResponse,
    WorkloadItem,
)
from app.core.time import utc_now
from app.models.audit import AuditEvent
from app.models.enums import (
    AttachmentStatus,
    AuditSeverity,
    GmailConnectionStatus,
    GmailHealth,
    GmailLabelSyncStatus,
    MessageClassification,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
    UserRole,
)
from app.models.gmail_labels import GmailThreadLabelSync
from app.models.operations import Attachment, CarrierMessage, PolicyCase, ReviewItem, Task
from app.models.organization import GmailConnection, User
from app.services.auth import AuthContext
from app.services.operations import (
    agent_brief,
    case_item,
    page_info,
    scoped_cases_query,
    valid_page,
)

AUDIT_CATEGORY_LABELS = {
    "ACCESS": "Access",
    "TASKS": "Tasks",
    "REVIEWS": "Reviews",
    "CASES": "Cases",
    "GMAIL": "Gmail",
    "CARRIER_CONFIG": "Carrier config",
    "PROCESSING_SYSTEM": "Processing / System",
}


def audit_category(event_type: str) -> str:
    if event_type.startswith(("USER_", "PROFILE_", "PASSWORD_", "AGENT_")):
        return "ACCESS"
    if event_type.startswith("TASK_"):
        return "TASKS"
    if event_type.startswith("AI_REVIEW_") or event_type == "CASE_REVIEWED":
        return "REVIEWS"
    if event_type.startswith("CASE_"):
        return "CASES"
    if event_type.startswith("GMAIL_"):
        return "GMAIL"
    if event_type.startswith(("CARRIER_", "WHITELIST_")):
        return "CARRIER_CONFIG"
    return "PROCESSING_SYSTEM"


def audit_event_label(event_type: str) -> str:
    return event_type.replace("_", " ").title()


def _category_clause(category: str):
    access = or_(
        AuditEvent.event_type.like("USER\\_%", escape="\\"),
        AuditEvent.event_type.like("PROFILE\\_%", escape="\\"),
        AuditEvent.event_type.like("PASSWORD\\_%", escape="\\"),
        AuditEvent.event_type.like("AGENT\\_%", escape="\\"),
    )
    tasks = AuditEvent.event_type.like("TASK\\_%", escape="\\")
    reviews = or_(
        AuditEvent.event_type.like("AI\\_REVIEW\\_%", escape="\\"),
        AuditEvent.event_type == "CASE_REVIEWED",
    )
    cases = AuditEvent.event_type.like("CASE\\_%", escape="\\") & (
        AuditEvent.event_type != "CASE_REVIEWED"
    )
    gmail = AuditEvent.event_type.like("GMAIL\\_%", escape="\\")
    carrier = or_(
        AuditEvent.event_type.like("CARRIER\\_%", escape="\\"),
        AuditEvent.event_type.like("WHITELIST\\_%", escape="\\"),
    )
    clauses = {
        "ACCESS": access,
        "TASKS": tasks,
        "REVIEWS": reviews,
        "CASES": cases,
        "GMAIL": gmail,
        "CARRIER_CONFIG": carrier,
    }
    if category == "PROCESSING_SYSTEM":
        return ~(access | tasks | reviews | cases | gmail | carrier)
    return clauses.get(category)


def dashboard(db: Session, current: AuthContext) -> DashboardResponse:
    dashboard_now = utc_now()
    case_scope = scoped_cases_query(current).where(
        PolicyCase.dismissed_at.is_(None),
        PolicyCase.completed_at.is_(None),
    )
    task_filters = [Task.agency_id == current.user.agency_id]
    gmail_filters = [GmailConnection.agency_id == current.user.agency_id]
    if current.user.role is UserRole.AGENT:
        task_filters.append(Task.assigned_agent_id == current.user.id)
        gmail_filters.append(GmailConnection.user_id == current.user.id)

    urgent_cases = (
        db.scalar(
            select(func.count()).select_from(
                case_scope.where(PolicyCase.priority == "URGENT").subquery()
            )
        )
        or 0
    )
    open_tasks = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .join(PolicyCase, Task.case_id == PolicyCase.id)
            .where(
                *task_filters,
                PolicyCase.dismissed_at.is_(None),
                PolicyCase.completed_at.is_(None),
                Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
            )
        )
        or 0
    )
    in_progress_tasks = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .join(PolicyCase, Task.case_id == PolicyCase.id)
            .where(
                *task_filters,
                PolicyCase.dismissed_at.is_(None),
                PolicyCase.completed_at.is_(None),
                Task.status == TaskStatus.IN_PROGRESS,
            )
        )
        or 0
    )
    due_soon_tasks = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .join(PolicyCase, Task.case_id == PolicyCase.id)
            .where(
                *task_filters,
                PolicyCase.dismissed_at.is_(None),
                PolicyCase.completed_at.is_(None),
                Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
                Task.due_at >= dashboard_now,
                Task.due_at <= dashboard_now + timedelta(days=7),
            )
        )
        or 0
    )
    overdue_tasks = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .join(PolicyCase, Task.case_id == PolicyCase.id)
            .where(
                *task_filters,
                PolicyCase.dismissed_at.is_(None),
                PolicyCase.completed_at.is_(None),
                Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
                Task.due_at < dashboard_now,
            )
        )
        or 0
    )
    review_query = (
        select(func.count())
        .select_from(ReviewItem)
        .join(PolicyCase, ReviewItem.case_id == PolicyCase.id, isouter=True)
        .where(
            ReviewItem.agency_id == current.user.agency_id,
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
            or_(
                ReviewItem.case_id.is_(None),
                (PolicyCase.dismissed_at.is_(None) & PolicyCase.completed_at.is_(None)),
            ),
        )
    )
    if current.user.role is UserRole.AGENT:
        review_query = review_query.where(
            or_(
                ReviewItem.assigned_reviewer_id == current.user.id,
                PolicyCase.assigned_agent_id == current.user.id,
            )
        )
    review_items = db.scalar(review_query) or 0
    connection_scope = select(GmailConnection.id).where(*gmail_filters)
    message_filters = [CarrierMessage.agency_id == current.user.agency_id]
    if current.user.role is UserRole.AGENT:
        message_filters.append(
            or_(
                CarrierMessage.gmail_connection_id.in_(connection_scope),
                CarrierMessage.case_id.in_(case_scope.with_only_columns(PolicyCase.id)),
            )
        )
    failures = (
        db.scalar(
            select(func.count())
            .select_from(CarrierMessage)
            .where(*message_filters, CarrierMessage.processing_status == ProcessingStatus.FAILED)
        )
        or 0
    )
    processed = (
        db.scalar(
            select(func.count())
            .select_from(CarrierMessage)
            .where(*message_filters, CarrierMessage.processing_status == ProcessingStatus.PROCESSED)
        )
        or 0
    )
    received_backlog = (
        db.scalar(
            select(func.count())
            .select_from(CarrierMessage)
            .where(*message_filters, CarrierMessage.processing_status == ProcessingStatus.RECEIVED)
        )
        or 0
    )
    processing_messages = (
        db.scalar(
            select(func.count())
            .select_from(CarrierMessage)
            .where(
                *message_filters, CarrierMessage.processing_status == ProcessingStatus.PROCESSING
            )
        )
        or 0
    )
    retry_scheduled = (
        db.scalar(
            select(func.count())
            .select_from(CarrierMessage)
            .where(
                *message_filters,
                CarrierMessage.processing_status == ProcessingStatus.FAILED,
                CarrierMessage.processing_next_retry_at.is_not(None),
            )
        )
        or 0
    )
    failed_attention = (
        db.scalar(
            select(func.count())
            .select_from(CarrierMessage)
            .where(
                *message_filters,
                CarrierMessage.processing_status == ProcessingStatus.FAILED,
                CarrierMessage.processing_next_retry_at.is_(None),
            )
        )
        or 0
    )
    oldest_unprocessed = db.scalar(
        select(func.min(CarrierMessage.received_at)).where(
            *message_filters,
            CarrierMessage.processing_status.in_(
                [ProcessingStatus.RECEIVED, ProcessingStatus.PROCESSING, ProcessingStatus.FAILED]
            ),
        )
    )
    label_filters = [GmailThreadLabelSync.agency_id == current.user.agency_id]
    if current.user.role is UserRole.AGENT:
        label_filters.append(GmailThreadLabelSync.gmail_connection_id.in_(connection_scope))
    labels_pending = (
        db.scalar(
            select(func.count())
            .select_from(GmailThreadLabelSync)
            .where(
                *label_filters,
                GmailThreadLabelSync.status.in_(
                    [
                        GmailLabelSyncStatus.PENDING,
                        GmailLabelSyncStatus.PROCESSING,
                        GmailLabelSyncStatus.RETRY_WAIT,
                    ]
                ),
            )
        )
        or 0
    )
    labels_attention = (
        db.scalar(
            select(func.count())
            .select_from(GmailThreadLabelSync)
            .where(
                *label_filters,
                GmailThreadLabelSync.status.in_(
                    [GmailLabelSyncStatus.FAILED, GmailLabelSyncStatus.NEEDS_PERMISSION]
                ),
            )
        )
        or 0
    )
    connections_attention = (
        db.scalar(
            select(func.count())
            .select_from(GmailConnection)
            .where(
                *gmail_filters,
                GmailConnection.status.in_(
                    [GmailConnectionStatus.NEEDS_REAUTH, GmailConnectionStatus.ERROR]
                ),
            )
        )
        or 0
    )

    recent_cases = db.scalars(
        case_scope.options(
            joinedload(PolicyCase.carrier),
            joinedload(PolicyCase.assigned_agent),
            selectinload(PolicyCase.reviews),
        )
        .order_by(PolicyCase.updated_at.desc())
        .limit(5)
    ).all()
    activity_query = select(AuditEvent).where(AuditEvent.agency_id == current.user.agency_id)
    if current.user.role is UserRole.AGENT:
        activity_query = activity_query.where(
            or_(
                AuditEvent.actor_user_id == current.user.id,
                AuditEvent.case_id.in_(case_scope.with_only_columns(PolicyCase.id)),
            )
        )
    activities = db.scalars(activity_query.order_by(AuditEvent.created_at.desc()).limit(8)).all()
    workload: list[WorkloadItem] = []
    if current.user.role is UserRole.MANAGER:
        rows = db.execute(
            select(
                User,
                func.count(Task.id).filter(
                    PolicyCase.dismissed_at.is_(None),
                    PolicyCase.completed_at.is_(None),
                ),
            )
            .outerjoin(
                Task,
                (Task.assigned_agent_id == User.id)
                & Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
            )
            .outerjoin(PolicyCase, Task.case_id == PolicyCase.id)
            .where(
                User.agency_id == current.user.agency_id,
                User.role == UserRole.AGENT,
                User.is_active.is_(True),
            )
            .group_by(User.id)
            .order_by(User.full_name)
        ).all()
        workload = [WorkloadItem(agent=agent_brief(user), open_tasks=count) for user, count in rows]

    gmail_statuses = set(db.scalars(select(GmailConnection.status).where(*gmail_filters)).all())
    if GmailConnectionStatus.CONNECTED in gmail_statuses:
        gmail_health = GmailHealth.CONNECTED
    elif gmail_statuses & {
        GmailConnectionStatus.NEEDS_REAUTH,
        GmailConnectionStatus.ERROR,
    }:
        gmail_health = GmailHealth.NEEDS_ATTENTION
    else:
        gmail_health = GmailHealth.NOT_CONNECTED
    return DashboardResponse(
        metrics=DashboardMetrics(
            urgent_cases=urgent_cases,
            open_tasks=open_tasks,
            in_progress_tasks=in_progress_tasks,
            due_soon_tasks=due_soon_tasks,
            overdue_tasks=overdue_tasks,
            review_items=review_items,
            processing_failures=failures,
            processed_messages=processed,
            gmail_connections_needing_attention=connections_attention,
            received_backlog=received_backlog,
            processing_messages=processing_messages,
            retry_scheduled=retry_scheduled,
            failed_requiring_attention=failed_attention,
            gmail_labels_pending=labels_pending,
            gmail_labels_requiring_attention=labels_attention,
            oldest_unprocessed_age_seconds=(
                max(0, int((utc_now() - oldest_unprocessed).total_seconds()))
                if oldest_unprocessed is not None
                else None
            ),
        ),
        recent_cases=[case_item(item, current.agency.timezone, current) for item in recent_cases],
        recent_activity=[
            ActivityItem(
                id=event.id,
                event_type=event.event_type,
                severity=event.severity,
                description=event.description,
                created_at=event.created_at,
            )
            for event in activities
        ],
        workload=workload,
        gmail_connected=gmail_health == GmailHealth.CONNECTED,
        gmail_health=gmail_health,
    )


def list_agents(
    db: Session, current: AuthContext, *, page: int, page_size: int = 10
) -> AgentListResponse:
    query = select(User).where(
        User.agency_id == current.user.agency_id,
        User.role == UserRole.AGENT,
        User.removed_at.is_(None),
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    page = valid_page(page, page_size, total)
    users = db.scalars(
        query.order_by(
            case((User.role == UserRole.AGENT, 0), else_=1),
            User.is_active.desc(),
            User.full_name,
            User.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    output = [agent_list_item(db, user) for user in users]
    return AgentListResponse(items=output, page=page_info(page, page_size, total))


def agent_list_item(db: Session, user: User) -> AgentListItem:
    open_tasks = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.assigned_agent_id == user.id,
                Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
            )
        )
        or 0
    )
    urgent_cases = (
        db.scalar(
            select(func.count())
            .select_from(PolicyCase)
            .where(PolicyCase.assigned_agent_id == user.id, PolicyCase.priority == "URGENT")
        )
        or 0
    )
    gmail_count = (
        db.scalar(
            select(func.count())
            .select_from(GmailConnection)
            .where(
                GmailConnection.user_id == user.id,
                GmailConnection.status != GmailConnectionStatus.DISCONNECTED,
            )
        )
        or 0
    )
    return AgentListItem(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        open_tasks=open_tasks,
        urgent_cases=urgent_cases,
        gmail_connections=gmail_count,
        avatar_url=agent_brief(user).avatar_url,
    )


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 1) if denominator else None


def analytics(
    db: Session,
    current: AuthContext,
    *,
    time_range: str = "30d",
) -> AnalyticsResponse:
    timezone = ZoneInfo(current.agency.timezone)
    today = datetime.now(timezone).date()
    days = {"7d": 7, "30d": 30, "90d": 90}.get(time_range)
    start_date = today - timedelta(days=days - 1) if days else None
    start_at = (
        datetime.combine(start_date, datetime.min.time(), timezone).astimezone(UTC)
        if start_date
        else None
    )
    end_at = datetime.combine(today + timedelta(days=1), datetime.min.time(), timezone).astimezone(
        UTC
    )
    query = (
        select(CarrierMessage)
        .options(joinedload(CarrierMessage.carrier))
        .where(
            CarrierMessage.agency_id == current.user.agency_id,
            CarrierMessage.received_at < end_at,
        )
    )
    if start_at is not None:
        query = query.where(CarrierMessage.received_at >= start_at)
    messages = list(db.scalars(query.order_by(CarrierMessage.received_at)).unique().all())
    message_ids = [message.id for message in messages]
    reviewed_ids = (
        set(
            db.scalars(
                select(ReviewItem.carrier_message_id).where(
                    ReviewItem.agency_id == current.user.agency_id,
                    ReviewItem.carrier_message_id.in_(message_ids),
                )
            ).all()
        )
        if message_ids
        else set()
    )
    handled_statuses = {
        ProcessingStatus.PROCESSED,
        ProcessingStatus.NEEDS_REVIEW,
        ProcessingStatus.FAILED,
        ProcessingStatus.IGNORED,
    }
    handled = [message for message in messages if message.processing_status in handled_statuses]
    handled_ids = {message.id for message in handled}
    reviewed_handled_ids = reviewed_ids & handled_ids
    successful = [
        message for message in messages if message.processing_status is ProcessingStatus.PROCESSED
    ]
    automatic = [message for message in successful if message.id not in reviewed_ids]
    failures = [
        message for message in handled if message.processing_status is ProcessingStatus.FAILED
    ]
    durations = [
        (message.processed_at - message.processing_started_at).total_seconds()
        for message in messages
        if message.processing_status is ProcessingStatus.PROCESSED
        and message.processing_started_at is not None
        and message.processed_at is not None
        and message.processed_at >= message.processing_started_at
    ]

    outcomes = Counter()
    for message in messages:
        if message.processing_status is ProcessingStatus.FAILED:
            outcomes["Failed"] += 1
        elif message.id in reviewed_ids:
            outcomes["Human review"] += 1
        elif message.processing_status in {ProcessingStatus.PROCESSED, ProcessingStatus.IGNORED}:
            outcomes["Automatic"] += 1
        else:
            outcomes["Still processing"] += 1
    total = len(messages)
    outcome_items = [
        AnalyticsBreakdownItem(
            label=label, count=outcomes[label], percentage=_rate(outcomes[label], total) or 0
        )
        for label in ("Automatic", "Human review", "Failed", "Still processing")
    ]

    classification_labels = {
        MessageClassification.POLICY_ISSUED: "Policy Issued",
        MessageClassification.PENDING_REQUIREMENTS: "Pending Requirements",
        MessageClassification.LAPSE_NOTICE: "Lapse Notice",
        MessageClassification.COMMISSION_UPDATE: "Commission Update",
        MessageClassification.OTHER: "Other",
    }
    classifications = Counter(
        message.classification for message in messages if message.classification
    )
    classified_total = sum(classifications.values())
    classification_items = [
        AnalyticsBreakdownItem(
            label=classification_labels[classification],
            count=classifications[classification],
            percentage=_rate(classifications[classification], classified_total) or 0,
        )
        for classification in classification_labels
        if classifications[classification]
    ]

    carrier_groups: dict[int, list[CarrierMessage]] = {}
    for message in messages:
        carrier_groups.setdefault(message.carrier_id, []).append(message)
    carrier_items = []
    for carrier_id, group in carrier_groups.items():
        group_handled = [
            message for message in group if message.processing_status in handled_statuses
        ]
        group_handled_ids = {message.id for message in group_handled}
        group_reviewed = reviewed_ids & group_handled_ids
        group_successful = [
            message for message in group if message.processing_status is ProcessingStatus.PROCESSED
        ]
        group_auto = [message for message in group_successful if message.id not in group_reviewed]
        group_failed = [
            message
            for message in group_handled
            if message.processing_status is ProcessingStatus.FAILED
        ]
        carrier_items.append(
            CarrierAnalyticsItem(
                carrier_id=carrier_id,
                carrier_name=group[0].carrier.name,
                messages=len(group),
                automation_rate=_rate(len(group_auto), len(group_successful)),
                review_rate=_rate(len(group_reviewed), len(group_handled)),
                failure_rate=_rate(len(group_failed), len(group_handled)),
            )
        )
    carrier_items.sort(key=lambda item: (-item.messages, item.carrier_name.casefold()))

    attachments = (
        list(
            db.scalars(
                select(Attachment)
                .join(CarrierMessage)
                .where(
                    CarrierMessage.agency_id == current.user.agency_id,
                    CarrierMessage.id.in_(message_ids),
                    or_(
                        func.lower(Attachment.mime_type) == "application/pdf",
                        func.lower(Attachment.filename).like("%.pdf"),
                    ),
                )
            ).all()
        )
        if message_ids
        else []
    )
    pdf_attempts = [
        item for item in attachments if item.processing_status is not AttachmentStatus.PENDING
    ]
    extracted = sum(item.processing_status is AttachmentStatus.EXTRACTED for item in pdf_attempts)
    needs_ocr = sum(item.processing_status is AttachmentStatus.NEEDS_OCR for item in pdf_attempts)
    failed_pdf = sum(
        item.processing_status in {AttachmentStatus.FAILED, AttachmentStatus.UNSUPPORTED}
        for item in pdf_attempts
    )

    local_dates = [message.received_at.astimezone(timezone).date() for message in messages]
    trend_counts: Counter[str] = Counter()
    if time_range in {"7d", "30d"}:
        assert start_date is not None and days is not None
        labels = [(start_date + timedelta(days=index)).isoformat() for index in range(days)]
        trend_counts.update(date_value.isoformat() for date_value in local_dates)
    elif time_range == "90d":
        assert start_date is not None
        labels = []
        for index in range(13):
            bucket_start = start_date + timedelta(days=index * 7)
            if bucket_start > today:
                break
            labels.append(bucket_start.isoformat())
        for date_value in local_dates:
            index = min((date_value - start_date).days // 7, len(labels) - 1)
            trend_counts[labels[index]] += 1
    else:
        first = min(local_dates, default=today).replace(day=1)
        labels = []
        cursor = first
        while cursor <= today:
            labels.append(cursor.strftime("%Y-%m"))
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        trend_counts.update(date_value.strftime("%Y-%m") for date_value in local_dates)

    return AnalyticsResponse(
        range=time_range,
        start_date=start_date,
        end_date=today,
        carrier_messages=total,
        automation_rate=_rate(len(automatic), len(successful)),
        review_rate=_rate(len(reviewed_handled_ids), len(handled)),
        failure_rate=_rate(len(failures), len(handled)),
        average_processing_seconds=round(sum(durations) / len(durations), 1) if durations else None,
        pdf_extraction_success_rate=_rate(extracted, len(pdf_attempts)),
        outcomes=outcome_items,
        volume_trend=[
            AnalyticsTrendItem(label=label, count=trend_counts[label]) for label in labels
        ],
        classifications=classification_items,
        carrier_performance=carrier_items,
        attachments=AttachmentAnalytics(
            pdfs_processed=len(pdf_attempts),
            extracted_successfully=extracted,
            needs_ocr=needs_ocr,
            failed_or_unsupported=failed_pdf,
        ),
    )


def audit_logs(
    db: Session,
    current: AuthContext,
    *,
    page: int,
    page_size: int,
    event_type: str | None,
    severity: AuditSeverity | None,
    actor: str | None,
    category: str | None,
    exclude_gmail_sync_completed: bool = False,
) -> AuditLogResponse:
    query = select(AuditEvent).where(AuditEvent.agency_id == current.user.agency_id)
    if exclude_gmail_sync_completed:
        query = query.where(AuditEvent.event_type != "GMAIL_SYNC_COMPLETED")
    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    if severity:
        query = query.where(AuditEvent.severity == severity)
    if actor == "system":
        query = query.where(AuditEvent.actor_user_id.is_(None))
    elif actor:
        try:
            actor_id = int(actor)
        except ValueError:
            query = query.where(AuditEvent.id == -1)
        else:
            valid_actor = db.scalar(
                select(User.id).where(
                    User.id == actor_id,
                    User.agency_id == current.user.agency_id,
                )
            )
            query = query.where(
                AuditEvent.actor_user_id == actor_id
                if valid_actor is not None
                else AuditEvent.id == -1
            )
    if category:
        clause = _category_clause(category.upper())
        query = query.where(clause if clause is not None else AuditEvent.id == -1)
    return _audit_page(db, current, query=query, page=page, page_size=page_size)


def activity_logs(
    db: Session,
    current: AuthContext,
    *,
    page: int,
    page_size: int,
    action_group: str | None,
) -> AuditLogResponse:
    query = select(AuditEvent).where(
        AuditEvent.agency_id == current.user.agency_id,
        AuditEvent.actor_user_id == current.user.id,
    )
    if action_group:
        clause = _category_clause(action_group.upper())
        query = query.where(clause if clause is not None else AuditEvent.id == -1)
    return _audit_page(db, current, query=query, page=page, page_size=page_size)


def _audit_page(
    db: Session,
    current: AuthContext,
    *,
    query,
    page: int,
    page_size: int,
) -> AuditLogResponse:
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    events = db.scalars(
        query.options(joinedload(AuditEvent.actor))
        .order_by(AuditEvent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    case_ids = {event.case_id for event in events if event.case_id is not None}
    task_ids = {event.task_id for event in events if event.task_id is not None}
    message_ids = {
        event.carrier_message_id for event in events if event.carrier_message_id is not None
    }
    case_labels = (
        {
            case.id: f"{case.client_name} · {case.policy_number or 'Policy number pending'}"
            for case in db.scalars(
                select(PolicyCase).where(
                    PolicyCase.id.in_(case_ids),
                    PolicyCase.agency_id == current.user.agency_id,
                )
            ).all()
        }
        if case_ids
        else {}
    )
    task_titles = (
        {
            task.id: task.title
            for task in db.scalars(
                select(Task).where(
                    Task.id.in_(task_ids),
                    Task.agency_id == current.user.agency_id,
                )
            ).all()
        }
        if task_ids
        else {}
    )
    reviews = (
        db.scalars(
            select(ReviewItem)
            .where(
                ReviewItem.carrier_message_id.in_(message_ids),
                ReviewItem.agency_id == current.user.agency_id,
            )
            .order_by(ReviewItem.id.desc())
        ).all()
        if message_ids
        else []
    )
    reviews_by_message = {}
    for review in reviews:
        reviews_by_message.setdefault(review.carrier_message_id, review)
    review_labels_by_message = {
        message_id: f"Review {review.reason_code.replace('_', ' ').title()}"
        for message_id, review in reviews_by_message.items()
    }
    return AuditLogResponse(
        items=[
            AuditLogItem(
                id=event.id,
                event_type=event.event_type,
                event_label=audit_event_label(event.event_type),
                category=AUDIT_CATEGORY_LABELS[audit_category(event.event_type)],
                severity=event.severity,
                actor_name=event.actor.full_name if event.actor else None,
                actor_user_id=event.actor_user_id,
                description=event.description,
                case_id=event.case_id,
                case_label=case_labels.get(event.case_id),
                task_id=event.task_id,
                task_title=task_titles.get(event.task_id),
                review_id=(
                    reviews_by_message[event.carrier_message_id].id
                    if event.carrier_message_id in reviews_by_message
                    and audit_category(event.event_type) == "REVIEWS"
                    else None
                ),
                review_label=(
                    review_labels_by_message[event.carrier_message_id]
                    if event.carrier_message_id in reviews_by_message
                    and audit_category(event.event_type) == "REVIEWS"
                    else None
                ),
                metadata=event.event_metadata,
                created_at=event.created_at,
            )
            for event in events
        ],
        page=page_info(page, page_size, total),
    )
