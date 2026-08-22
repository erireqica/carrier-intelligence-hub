from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.schemas.domain import (
    ActivityItem,
    AgentListItem,
    AnalyticsResponse,
    AuditLogItem,
    AuditLogResponse,
    DashboardMetrics,
    DashboardResponse,
    WorkloadItem,
)
from app.core.time import utc_now
from app.models.audit import AuditEvent
from app.models.carriers import Carrier
from app.models.enums import (
    AuditSeverity,
    GmailConnectionStatus,
    GmailHealth,
    GmailLabelSyncStatus,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
    UserRole,
)
from app.models.gmail_labels import GmailThreadLabelSync
from app.models.operations import CarrierMessage, PolicyCase, ReviewItem, Task
from app.models.organization import GmailConnection, User
from app.services.auth import AuthContext
from app.services.operations import agent_brief, case_item, page_info, scoped_cases_query

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
    if event_type.startswith(("USER_", "PROFILE_", "PASSWORD_")):
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
    case_scope = scoped_cases_query(current).where(PolicyCase.dismissed_at.is_(None))
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
                Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
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
                Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
                Task.due_at < utc_now(),
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
            or_(ReviewItem.case_id.is_(None), PolicyCase.dismissed_at.is_(None)),
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
                func.count(Task.id).filter(PolicyCase.dismissed_at.is_(None)),
            )
            .outerjoin(
                Task,
                (Task.assigned_agent_id == User.id)
                & Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
            )
            .outerjoin(PolicyCase, Task.case_id == PolicyCase.id)
            .where(User.agency_id == current.user.agency_id, User.is_active.is_(True))
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


def list_agents(db: Session, current: AuthContext) -> list[AgentListItem]:
    users = db.scalars(
        select(User).where(User.agency_id == current.user.agency_id).order_by(User.full_name)
    ).all()
    output: list[AgentListItem] = []
    for user in users:
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
        output.append(
            AgentListItem(
                id=user.id,
                full_name=user.full_name,
                email=user.email,
                role=user.role,
                is_active=user.is_active,
                last_login_at=user.last_login_at,
                open_tasks=open_tasks,
                urgent_cases=urgent_cases,
                gmail_connections=gmail_count,
            )
        )
    return output


def analytics(db: Session, current: AuthContext) -> AnalyticsResponse:
    agency_id = current.user.agency_id
    cases_by_status = dict(
        db.execute(
            select(PolicyCase.current_policy_status, func.count())
            .where(PolicyCase.agency_id == agency_id)
            .group_by(PolicyCase.current_policy_status)
        ).all()
    )
    cases_by_carrier = dict(
        db.execute(
            select(PolicyCase.carrier_id, func.count())
            .where(PolicyCase.agency_id == agency_id)
            .group_by(PolicyCase.carrier_id)
        ).all()
    )
    carrier_names = dict(
        db.execute(select(Carrier.id, Carrier.name).where(Carrier.agency_id == agency_id)).all()
    )
    workload_rows = db.execute(
        select(User, func.count(Task.id))
        .outerjoin(
            Task,
            (Task.assigned_agent_id == User.id)
            & Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
        )
        .where(User.agency_id == agency_id, User.is_active.is_(True))
        .group_by(User.id)
        .order_by(User.full_name, User.id)
    ).all()
    task_counts = db.execute(
        select(
            func.count().filter(Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS])),
            func.count().filter(
                Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]), Task.due_at < utc_now()
            ),
        ).where(Task.agency_id == agency_id)
    ).one()
    message_counts = db.execute(
        select(
            func.count().filter(CarrierMessage.processing_status == ProcessingStatus.PROCESSED),
            func.count().filter(CarrierMessage.processing_status == ProcessingStatus.FAILED),
        ).where(CarrierMessage.agency_id == agency_id)
    ).one()
    return AnalyticsResponse(
        cases_by_status={key.value: value for key, value in cases_by_status.items()},
        cases_by_carrier={carrier_names[key]: value for key, value in cases_by_carrier.items()},
        workload_by_agent=[
            WorkloadItem(agent=agent_brief(user), open_tasks=count) for user, count in workload_rows
        ],
        urgent_high_cases=db.scalar(
            select(func.count())
            .select_from(PolicyCase)
            .where(PolicyCase.agency_id == agency_id, PolicyCase.priority.in_(["URGENT", "HIGH"]))
        )
        or 0,
        open_tasks=task_counts[0],
        overdue_tasks=task_counts[1],
        open_reviews=db.scalar(
            select(func.count())
            .select_from(ReviewItem)
            .where(
                ReviewItem.agency_id == agency_id,
                ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
            )
        )
        or 0,
        processed_messages=message_counts[0],
        failed_messages=message_counts[1],
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
) -> AuditLogResponse:
    query = select(AuditEvent).where(AuditEvent.agency_id == current.user.agency_id)
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
