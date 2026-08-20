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
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
    UserRole,
)
from app.models.operations import CarrierMessage, PolicyCase, ReviewItem, Task
from app.models.organization import GmailConnection, User
from app.services.auth import AuthContext
from app.services.operations import agent_brief, case_item, page_info, scoped_cases_query


def dashboard(db: Session, current: AuthContext) -> DashboardResponse:
    case_scope = scoped_cases_query(current)
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
            .where(*task_filters, Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]))
        )
        or 0
    )
    overdue_tasks = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                *task_filters,
                Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
                Task.due_at < utc_now(),
            )
        )
        or 0
    )
    review_query = (
        select(func.count())
        .select_from(ReviewItem)
        .where(
            ReviewItem.agency_id == current.user.agency_id,
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
        )
    )
    if current.user.role is UserRole.AGENT:
        review_query = review_query.join(
            PolicyCase, ReviewItem.case_id == PolicyCase.id, isouter=True
        ).where(
            or_(
                ReviewItem.assigned_reviewer_id == current.user.id,
                PolicyCase.assigned_agent_id == current.user.id,
            )
        )
    review_items = db.scalar(review_query) or 0
    message_filters = [CarrierMessage.agency_id == current.user.agency_id]
    if current.user.role is UserRole.AGENT:
        message_filters.append(
            CarrierMessage.case_id.in_(case_scope.with_only_columns(PolicyCase.id))
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
            select(User, func.count(Task.id))
            .outerjoin(
                Task,
                (Task.assigned_agent_id == User.id)
                & Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
            )
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
        ),
        recent_cases=[case_item(item) for item in recent_cases],
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
                .where(GmailConnection.user_id == user.id)
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
) -> AuditLogResponse:
    query = select(AuditEvent).where(AuditEvent.agency_id == current.user.agency_id)
    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    if severity:
        query = query.where(AuditEvent.severity == severity)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    events = db.scalars(
        query.options(joinedload(AuditEvent.actor))
        .order_by(AuditEvent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return AuditLogResponse(
        items=[
            AuditLogItem(
                id=event.id,
                event_type=event.event_type,
                severity=event.severity,
                actor_name=event.actor.full_name if event.actor else None,
                description=event.description,
                case_id=event.case_id,
                task_id=event.task_id,
                metadata=event.event_metadata,
                created_at=event.created_at,
            )
            for event in events
        ],
        page=page_info(page, page_size, total),
    )
