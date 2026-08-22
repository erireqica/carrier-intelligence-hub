import math
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy import case as sql_case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.schemas.domain import (
    ActivityItem,
    AgentBrief,
    AttachmentItem,
    CarrierBrief,
    CaseCorrectionInput,
    CaseDetail,
    CaseListItem,
    CaseListResponse,
    EvidenceItem,
    ManualTaskCreate,
    MessageAnalysisResponse,
    MessageItem,
    PageInfo,
    ReviewDetailResponse,
    ReviewIssue,
    ReviewIssueValue,
    ReviewItemResponse,
    ReviewListResponse,
    ReviewUpdate,
    TaskItem,
    TaskListResponse,
    TaskUpdate,
)
from app.core.config import get_settings
from app.core.time import utc_now
from app.integrations.ai.schemas import AnalysisResult
from app.models.audit import AuditEvent
from app.models.enums import (
    CaseAssignmentSource,
    PolicyStatus,
    Priority,
    ReviewStatus,
    TaskStatus,
    UserRole,
)
from app.models.operations import (
    Attachment,
    CarrierMessage,
    CaseEvidence,
    PolicyCase,
    ReviewItem,
    Task,
)
from app.models.organization import User
from app.processing.ambiguities import verify_interpretation_ambiguities
from app.processing.source import build_source_bundle
from app.services.audit import record_audit_event
from app.services.auth import AuthContext
from app.services.gmail_labels import enqueue_for_message


def page_info(page: int, page_size: int, total: int) -> PageInfo:
    return PageInfo(
        page=page,
        page_size=page_size,
        total=total,
        pages=max(1, math.ceil(total / page_size)),
    )


def valid_page(page: int, page_size: int, total: int) -> int:
    return min(page, max(1, math.ceil(total / page_size)))


def agent_brief(user: User) -> AgentBrief:
    from app.services.avatars import avatar_url

    return AgentBrief(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        avatar_url=avatar_url(user),
    )


def business_date(value: datetime | None, timezone_name: str) -> date | None:
    if value is None:
        return None
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = UTC
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(timezone).date()


def task_item(task: Task, agency_timezone: str) -> TaskItem:
    return TaskItem(
        id=task.id,
        case_id=task.case_id,
        client_name=task.case.client_name,
        policy_number=task.case.policy_number,
        title=task.title,
        description=task.description,
        priority=task.priority,
        due_at=business_date(task.due_at, agency_timezone),
        status=task.status,
        created_at=task.created_at,
        completed_at=task.completed_at,
        assigned_agent=agent_brief(task.assigned_agent),
        is_manual=task.created_by_user_id is not None,
        created_by=agent_brief(task.created_by) if task.created_by else None,
        completed_by=agent_brief(task.completed_by) if task.completed_by else None,
    )


def task_due_at(value: date | None, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = UTC
    return datetime.combine(value, time(17, 0), timezone).astimezone(UTC)


def case_item(case: PolicyCase, agency_timezone: str, current: AuthContext) -> CaseListItem:
    return CaseListItem(
        id=case.id,
        client_name=case.client_name,
        policy_number=case.policy_number,
        policy_status=case.current_policy_status,
        priority=case.priority,
        summary=case.summary,
        deadline=business_date(case.current_deadline, agency_timezone),
        updated_at=case.updated_at,
        carrier=CarrierBrief(id=case.carrier.id, name=case.carrier.name, code=case.carrier.code),
        assigned_agent=agent_brief(case.assigned_agent) if case.assigned_agent else None,
        needs_review=any(
            item.status in {ReviewStatus.OPEN, ReviewStatus.IN_REVIEW} for item in case.reviews
        ),
        dismissed_at=case.dismissed_at,
        completed_at=case.completed_at,
        can_manage_lifecycle=(
            current.user.role is UserRole.MANAGER or case.assigned_agent_id == current.user.id
        ),
    )


def case_completion_blockers(case: PolicyCase) -> list[str]:
    blockers: list[str] = []
    if any(task.status in {TaskStatus.OPEN, TaskStatus.IN_PROGRESS} for task in case.tasks):
        blockers.append("Complete all active tasks before completing this case.")
    if any(review.status in {ReviewStatus.OPEN, ReviewStatus.IN_REVIEW} for review in case.reviews):
        blockers.append("Resolve the active review before completing this case.")
    return blockers


def attachment_item(attachment: Attachment) -> AttachmentItem:
    preview = None
    if attachment.extracted_text:
        preview = attachment.extracted_text[:4_000]
    return AttachmentItem(
        id=attachment.id,
        filename=attachment.filename,
        mime_type=attachment.mime_type,
        size_bytes=attachment.size_bytes,
        processing_status=attachment.processing_status,
        page_count=attachment.page_count,
        extraction_error_code=attachment.extraction_error_code,
        extracted_text_preview=preview,
    )


def scoped_cases_query(current: AuthContext) -> Select[tuple[PolicyCase]]:
    query = select(PolicyCase).where(PolicyCase.agency_id == current.user.agency_id)
    if current.user.role is UserRole.AGENT:
        query = query.where(PolicyCase.assigned_agent_id == current.user.id)
    return query


def list_cases(
    db: Session,
    current: AuthContext,
    *,
    page: int,
    page_size: int,
    search: str | None,
    carrier_id: int | None,
    policy_status: PolicyStatus | None,
    priority: Priority | None,
    assigned_agent_id: int | None,
    lifecycle: str,
) -> CaseListResponse:
    query = scoped_cases_query(current)
    if lifecycle == "DISMISSED":
        query = query.where(PolicyCase.dismissed_at.is_not(None))
    elif lifecycle == "COMPLETED":
        query = query.where(
            PolicyCase.dismissed_at.is_(None),
            PolicyCase.completed_at.is_not(None),
        )
    else:
        query = query.where(
            PolicyCase.dismissed_at.is_(None),
            PolicyCase.completed_at.is_(None),
        )
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(PolicyCase.client_name.ilike(term), PolicyCase.policy_number.ilike(term))
        )
    if carrier_id:
        query = query.where(PolicyCase.carrier_id == carrier_id)
    if policy_status:
        query = query.where(PolicyCase.current_policy_status == policy_status)
    if priority:
        query = query.where(PolicyCase.priority == priority)
    if assigned_agent_id and current.user.role is UserRole.MANAGER:
        query = query.where(PolicyCase.assigned_agent_id == assigned_agent_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    page = valid_page(page, page_size, total)
    cases = db.scalars(
        query.options(
            joinedload(PolicyCase.carrier),
            joinedload(PolicyCase.assigned_agent),
            joinedload(PolicyCase.completed_by),
            selectinload(PolicyCase.reviews),
        )
        .order_by(PolicyCase.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return CaseListResponse(
        items=[case_item(case, current.agency.timezone, current) for case in cases],
        page=page_info(page, page_size, total),
    )


def set_case_dismissed(
    db: Session, current: AuthContext, case_id: int, *, dismissed: bool
) -> CaseDetail:
    query = select(PolicyCase).where(
        PolicyCase.id == case_id,
        PolicyCase.agency_id == current.user.agency_id,
    )
    if current.user.role is UserRole.AGENT:
        query = query.where(PolicyCase.assigned_agent_id == current.user.id)
    case = db.scalar(query)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if dismissed == (case.dismissed_at is not None):
        return get_case_detail(db, current, case.id)
    case.dismissed_at = utc_now() if dismissed else None
    case.dismissed_by_user_id = current.user.id if dismissed else None
    record_audit_event(
        db,
        agency_id=case.agency_id,
        actor_user_id=current.user.id,
        case_id=case.id,
        event_type="CASE_DISMISSED" if dismissed else "CASE_RESTORED",
        description=(
            f"Case {'dismissed from' if dismissed else 'restored to'} active work by "
            f"{'manager' if current.user.role is UserRole.MANAGER else 'assigned agent'}"
        ),
    )
    db.commit()
    db.expire_all()
    return get_case_detail(db, current, case.id)


def set_case_completed(
    db: Session, current: AuthContext, case_id: int, *, completed: bool
) -> CaseDetail:
    if current.user.role is not UserRole.AGENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Case completion is performed by the assigned agent",
        )
    case = db.scalar(
        select(PolicyCase)
        .where(
            PolicyCase.id == case_id,
            PolicyCase.agency_id == current.user.agency_id,
            PolicyCase.assigned_agent_id == current.user.id,
        )
        .with_for_update()
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.dismissed_at is not None:
        raise HTTPException(status_code=409, detail="Restore this case before changing completion")

    if completed:
        if case.completed_at is not None:
            return get_case_detail(db, current, case.id)
        active_tasks = (
            db.scalar(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.case_id == case.id,
                    Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
                )
            )
            or 0
        )
        active_reviews = (
            db.scalar(
                select(func.count())
                .select_from(ReviewItem)
                .where(
                    ReviewItem.case_id == case.id,
                    ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
                )
            )
            or 0
        )
        blockers: list[str] = []
        if active_tasks:
            blockers.append("Complete all active tasks before completing this case.")
        if active_reviews:
            blockers.append("Resolve the active review before completing this case.")
        if blockers:
            raise HTTPException(status_code=409, detail=" ".join(blockers))
        case.completed_at = utc_now()
        case.completed_by_user_id = current.user.id
        event_type = "CASE_COMPLETED"
        description = f"{current.user.full_name} completed the case"
    else:
        if case.completed_at is None:
            return get_case_detail(db, current, case.id)
        case.completed_at = None
        case.completed_by_user_id = None
        event_type = "CASE_REOPENED"
        description = f"{current.user.full_name} reopened the case"

    record_audit_event(
        db,
        agency_id=case.agency_id,
        actor_user_id=current.user.id,
        case_id=case.id,
        event_type=event_type,
        description=description,
    )
    db.commit()
    db.expire_all()
    return get_case_detail(db, current, case.id)


def get_case_detail(db: Session, current: AuthContext, case_id: int) -> CaseDetail:
    query = (
        scoped_cases_query(current)
        .where(PolicyCase.id == case_id)
        .options(
            joinedload(PolicyCase.carrier),
            joinedload(PolicyCase.assigned_agent),
            joinedload(PolicyCase.completed_by),
            selectinload(PolicyCase.reviews),
            selectinload(PolicyCase.messages).selectinload(CarrierMessage.attachments),
            selectinload(PolicyCase.messages).joinedload(CarrierMessage.analysis),
            selectinload(PolicyCase.tasks).joinedload(Task.assigned_agent),
            selectinload(PolicyCase.tasks).joinedload(Task.created_by),
            selectinload(PolicyCase.tasks).joinedload(Task.completed_by),
            selectinload(PolicyCase.evidence).joinedload(CaseEvidence.attachment),
        )
    )
    case = db.scalar(query)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    activity = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.agency_id == current.user.agency_id, AuditEvent.case_id == case.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(30)
    ).all()
    base = case_item(case, current.agency.timezone, current).model_dump()
    completion_blockers = case_completion_blockers(case)
    is_assigned_agent = (
        current.user.role is UserRole.AGENT and case.assigned_agent_id == current.user.id
    )
    return CaseDetail(
        **base,
        premium_amount=case.premium_amount,
        currency=case.currency,
        effective_date=case.effective_date,
        completed_by=agent_brief(case.completed_by) if case.completed_by else None,
        can_complete=(
            is_assigned_agent
            and case.dismissed_at is None
            and case.completed_at is None
            and not completion_blockers
        ),
        can_reopen=(
            is_assigned_agent and case.dismissed_at is None and case.completed_at is not None
        ),
        completion_blockers=completion_blockers,
        messages=[
            MessageItem(
                id=message.id,
                sender=message.sender,
                subject=message.subject,
                received_at=message.received_at,
                classification=message.classification,
                summary=message.summary,
                priority=message.priority,
                processing_status=message.processing_status,
                cleaned_content=message.cleaned_content,
                original_deadline_text=message.original_deadline_text,
                analysis_confidence=(
                    float(message.analysis.overall_confidence) if message.analysis else None
                ),
                validation_flags=(
                    list(message.analysis.validation_flags) if message.analysis else []
                ),
                review_id=next(
                    (
                        review.id
                        for review in case.reviews
                        if review.carrier_message_id == message.id
                        and review.status in {ReviewStatus.OPEN, ReviewStatus.IN_REVIEW}
                    ),
                    None,
                ),
            )
            for message in case.messages
        ],
        attachments=[
            attachment_item(attachment)
            for message in case.messages
            for attachment in message.attachments
        ],
        tasks=[task_item(task, current.agency.timezone) for task in case.tasks],
        evidence=[
            EvidenceItem(
                id=evidence.id,
                field_name=evidence.field_name,
                source_type=evidence.source_type,
                attachment_filename=(
                    evidence.attachment.filename if evidence.attachment is not None else None
                ),
                excerpt=evidence.excerpt,
            )
            for evidence in case.evidence
        ],
        activity=[
            ActivityItem(
                id=event.id,
                event_type=event.event_type,
                severity=event.severity,
                description=event.description,
                created_at=event.created_at,
            )
            for event in activity
        ],
    )


def assign_case(
    db: Session,
    current: AuthContext,
    case_id: int,
    assigned_agent_id: int,
) -> CaseDetail:
    case = db.scalar(
        select(PolicyCase).where(
            PolicyCase.id == case_id,
            PolicyCase.agency_id == current.user.agency_id,
        )
    )
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    if case.dismissed_at is not None:
        raise HTTPException(status_code=409, detail="Restore this case before reassigning it")
    assignee = db.scalar(
        select(User).where(
            User.id == assigned_agent_id,
            User.agency_id == current.user.agency_id,
            User.role == UserRole.AGENT,
            User.is_active.is_(True),
        )
    )
    if assignee is None:
        raise HTTPException(status_code=422, detail="Assigned agent is invalid")

    from app.services.message_processing import reconcile_case_operational_ownership

    ownership = reconcile_case_operational_ownership(
        db,
        case,
        assigned_agent_id=assignee.id,
        assignment_source=CaseAssignmentSource.MANAGER,
        actor_user_id=current.user.id,
    )
    previous_assignee_id = ownership.previous_assignee_id
    assignment_changed = previous_assignee_id != assignee.id
    if assignment_changed:
        record_audit_event(
            db,
            agency_id=current.user.agency_id,
            actor_user_id=current.user.id,
            case_id=case.id,
            event_type="CASE_REASSIGNED" if previous_assignee_id is not None else "CASE_ASSIGNED",
            description="Case assignment changed",
            metadata={
                "previous_assignee_id": previous_assignee_id,
                "new_assignee_id": assignee.id,
                "active_tasks_transferred": ownership.active_tasks_reassigned,
                "active_reviews_transferred": ownership.active_reviews_reassigned,
                "source_messages_linked": ownership.source_messages_linked,
                "ownership_conflicts_reconciled": (ownership.ownership_conflicts_reconciled),
            },
        )
    db.commit()
    db.expire_all()
    return get_case_detail(db, current, case.id)


def list_tasks(
    db: Session,
    current: AuthContext,
    *,
    page: int,
    page_size: int,
    task_status: TaskStatus | None,
    priority: Priority | None,
    overdue: bool | None,
    assigned_agent_id: int | None,
    task_view: str,
) -> TaskListResponse:
    query = (
        select(Task)
        .join(PolicyCase, Task.case_id == PolicyCase.id)
        .where(Task.agency_id == current.user.agency_id, PolicyCase.dismissed_at.is_(None))
    )
    if current.user.role is UserRole.AGENT:
        query = query.where(Task.assigned_agent_id == current.user.id)
    elif assigned_agent_id:
        query = query.where(Task.assigned_agent_id == assigned_agent_id)
    if task_status:
        query = query.where(Task.status == task_status)
    elif task_view == "TODO":
        query = query.where(Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]))
    elif task_view == "OPEN":
        query = query.where(Task.status == TaskStatus.OPEN)
    elif task_view == "IN_PROGRESS":
        query = query.where(Task.status == TaskStatus.IN_PROGRESS)
    elif task_view == "COMPLETED":
        query = query.where(Task.status == TaskStatus.COMPLETED)
    elif task_view == "DISMISSED":
        query = query.where(Task.status == TaskStatus.DISMISSED)
    if priority:
        query = query.where(Task.priority == priority)
    if overdue is True:
        query = query.where(
            Task.due_at < utc_now(), Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS])
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    page = valid_page(page, page_size, total)
    status_order = sql_case(
        (Task.status == TaskStatus.IN_PROGRESS, 0),
        (Task.status == TaskStatus.OPEN, 1),
        (Task.status == TaskStatus.COMPLETED, 2),
        (Task.status == TaskStatus.DISMISSED, 3),
        else_=4,
    )
    tasks = db.scalars(
        query.options(
            joinedload(Task.case),
            joinedload(Task.assigned_agent),
            joinedload(Task.created_by),
            joinedload(Task.completed_by),
        )
        .order_by(status_order, Task.due_at.asc().nullslast(), Task.created_at.asc(), Task.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return TaskListResponse(
        items=[task_item(task, current.agency.timezone) for task in tasks],
        page=page_info(page, page_size, total),
    )


def create_manual_task(
    db: Session,
    current: AuthContext,
    case_id: int,
    data: ManualTaskCreate,
) -> TaskItem:
    if current.user.role is not UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent access required")
    case = db.scalar(
        select(PolicyCase)
        .where(
            PolicyCase.id == case_id,
            PolicyCase.agency_id == current.user.agency_id,
            PolicyCase.assigned_agent_id == current.user.id,
        )
        .with_for_update()
    )
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    if case.dismissed_at is not None:
        raise HTTPException(status_code=409, detail="Restore this case before adding tasks")
    if case.completed_at is not None:
        raise HTTPException(status_code=409, detail="Reopen this case before adding tasks")

    task = Task(
        agency_id=case.agency_id,
        case_id=case.id,
        assigned_agent_id=current.user.id,
        created_by_user_id=current.user.id,
        title=data.title,
        description=data.description,
        priority=data.priority,
        due_at=task_due_at(data.due_date, current.agency.timezone),
        status=TaskStatus.OPEN,
    )
    db.add(task)
    db.flush()
    record_audit_event(
        db,
        agency_id=case.agency_id,
        actor_user_id=current.user.id,
        case_id=case.id,
        task_id=task.id,
        event_type="TASK_CREATED_MANUALLY",
        description=f'{current.user.full_name} added task "{task.title}"',
        metadata={
            "origin": "MANUAL",
            "priority": task.priority.value,
            "due_date": data.due_date.isoformat() if data.due_date else None,
        },
    )
    db.commit()
    return task_item(task, current.agency.timezone)


def update_task(db: Session, current: AuthContext, task_id: int, update: TaskUpdate) -> TaskItem:
    task = db.scalar(
        select(Task)
        .options(
            joinedload(Task.case),
            joinedload(Task.assigned_agent),
            joinedload(Task.created_by),
            joinedload(Task.completed_by),
        )
        .where(Task.id == task_id, Task.agency_id == current.user.agency_id)
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if current.user.role is not UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent access required")
    if task.assigned_agent_id != current.user.id or task.case.assigned_agent_id != current.user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    if task.case.dismissed_at is not None:
        raise HTTPException(status_code=409, detail="Restore this case before updating its tasks")
    locked_case = db.scalar(
        select(PolicyCase).where(PolicyCase.id == task.case_id).with_for_update()
    )
    assert locked_case is not None
    if locked_case.completed_at is not None:
        raise HTTPException(status_code=409, detail="Reopen this case before updating its tasks")

    previous_status = task.status
    status_changed = update.status != task.status

    if status_changed:
        task.status = update.status
        task.completed_at = utc_now() if update.status is TaskStatus.COMPLETED else None
        task.completed_by_user_id = (
            current.user.id if update.status is TaskStatus.COMPLETED else None
        )

    if status_changed:
        record_audit_event(
            db,
            agency_id=current.user.agency_id,
            actor_user_id=current.user.id,
            case_id=task.case_id,
            task_id=task.id,
            event_type="TASK_STATUS_CHANGED",
            description=f"Task status changed: {task.title}",
            metadata={
                "previous_status": previous_status.value,
                "new_status": task.status.value,
            },
        )
    if not status_changed:
        return task_item(task, current.agency.timezone)

    if status_changed and task.source_message is not None:
        enqueue_for_message(db, task.source_message)

    db.commit()
    db.refresh(task)
    return task_item(task, current.agency.timezone)


def list_reviews(
    db: Session,
    current: AuthContext,
    *,
    page: int,
    page_size: int,
    review_status: ReviewStatus | None,
    review_view: str,
) -> ReviewListResponse:
    query = scoped_reviews_query(current)
    if review_status:
        query = query.where(ReviewItem.status == review_status)
        if review_status in {ReviewStatus.OPEN, ReviewStatus.IN_REVIEW}:
            query = query.where(
                or_(
                    ReviewItem.case_id.is_(None),
                    and_(
                        PolicyCase.dismissed_at.is_(None),
                        PolicyCase.completed_at.is_(None),
                    ),
                )
            )
    elif review_view == "ACTIONABLE":
        query = query.where(
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
            or_(
                ReviewItem.case_id.is_(None),
                and_(
                    PolicyCase.dismissed_at.is_(None),
                    PolicyCase.completed_at.is_(None),
                ),
            ),
        )
    elif review_view == "RESOLVED":
        query = query.where(ReviewItem.status == ReviewStatus.RESOLVED)
    elif review_view == "DISMISSED":
        query = query.where(ReviewItem.status == ReviewStatus.DISMISSED)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    page = valid_page(page, page_size, total)
    reviews = (
        db.scalars(
            query.options(
                joinedload(ReviewItem.case),
                joinedload(ReviewItem.carrier_message).joinedload(CarrierMessage.carrier),
                joinedload(ReviewItem.carrier_message).joinedload(CarrierMessage.analysis),
                joinedload(ReviewItem.assigned_reviewer),
            )
            .order_by(ReviewItem.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .unique()
        .all()
    )
    items = [review_item_response(item) for item in reviews]
    return ReviewListResponse(items=items, page=page_info(page, page_size, total))


def scoped_reviews_query(current: AuthContext) -> Select[tuple[ReviewItem]]:
    query = (
        select(ReviewItem)
        .join(PolicyCase, ReviewItem.case_id == PolicyCase.id, isouter=True)
        .where(ReviewItem.agency_id == current.user.agency_id)
    )
    if current.user.role is not UserRole.AGENT:
        return query

    active_statuses = (ReviewStatus.OPEN, ReviewStatus.IN_REVIEW)
    terminal_statuses = (ReviewStatus.RESOLVED, ReviewStatus.DISMISSED)
    return query.where(
        or_(
            and_(
                ReviewItem.status.in_(active_statuses),
                ReviewItem.case_id.is_not(None),
                PolicyCase.assigned_agent_id == current.user.id,
                PolicyCase.dismissed_at.is_(None),
                PolicyCase.completed_at.is_(None),
            ),
            and_(
                ReviewItem.status.in_(active_statuses),
                ReviewItem.case_id.is_(None),
                ReviewItem.assigned_reviewer_id == current.user.id,
            ),
            and_(
                ReviewItem.status.in_(terminal_statuses),
                or_(
                    ReviewItem.assigned_reviewer_id == current.user.id,
                    PolicyCase.assigned_agent_id == current.user.id,
                ),
            ),
        )
    )


def _review_query(current: AuthContext) -> Select[tuple[ReviewItem]]:
    return scoped_reviews_query(current).options(
        joinedload(ReviewItem.case),
        joinedload(ReviewItem.carrier_message).joinedload(CarrierMessage.carrier),
        joinedload(ReviewItem.carrier_message).joinedload(CarrierMessage.analysis),
        joinedload(ReviewItem.carrier_message).selectinload(CarrierMessage.attachments),
        joinedload(ReviewItem.assigned_reviewer),
    )


def get_review_entity(db: Session, current: AuthContext, review_id: int) -> ReviewItem:
    item = db.scalar(
        _review_query(current).where(
            ReviewItem.id == review_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return item


def get_review_item(db: Session, current: AuthContext, review_id: int) -> ReviewItemResponse:
    return review_item_response(get_review_entity(db, current, review_id))


def review_item_response(item: ReviewItem) -> ReviewItemResponse:
    proposed = None
    confidence = None
    if item.carrier_message.analysis is not None:
        confidence = float(item.carrier_message.analysis.overall_confidence)
        try:
            proposed = AnalysisResult.model_validate(
                item.carrier_message.analysis.model_result_json
            )
        except ValueError:
            proposed = None
    ownership_issue = item.reason_code in {"CASE_OWNER_CONFLICT", "OPERATIONAL_OWNER_REQUIRED"}
    issue_title = (
        "Multiple cases match this message"
        if item.reason_code == "CASE_MATCH_CONFLICT"
        else "Case ownership requires manager attention"
        if ownership_issue
        else "Carrier information needs confirmation"
    )
    return ReviewItemResponse(
        id=item.id,
        message_id=item.carrier_message_id,
        case_id=item.case_id,
        client_name=item.case.client_name
        if item.case
        else proposed.client_name
        if proposed
        else None,
        policy_number=(
            item.case.policy_number if item.case else proposed.policy_number if proposed else None
        ),
        carrier_name=item.carrier_message.carrier.name,
        message_subject=item.carrier_message.subject,
        reason_code=item.reason_code,
        reason=item.reason,
        status=item.status,
        resolution_notes=item.resolution_notes,
        assigned_reviewer=(agent_brief(item.assigned_reviewer) if item.assigned_reviewer else None),
        created_at=item.created_at,
        resolved_at=item.resolved_at,
        analysis_confidence=confidence,
        issue_title=issue_title,
        issue_summary=item.reason,
    )


def _message_analysis_response(db: Session, message: CarrierMessage) -> MessageAnalysisResponse:
    analysis = message.analysis
    proposed = None
    final = None
    if analysis is not None:
        try:
            proposed = AnalysisResult.model_validate(analysis.model_result_json)
        except ValueError:
            proposed = None
        if analysis.final_result_json:
            try:
                final = AnalysisResult.model_validate(analysis.final_result_json)
            except ValueError:
                final = None
    review_id = db.scalar(
        select(ReviewItem.id)
        .where(
            ReviewItem.carrier_message_id == message.id,
            ReviewItem.status.in_([ReviewStatus.OPEN, ReviewStatus.IN_REVIEW]),
        )
        .order_by(ReviewItem.id.desc())
        .limit(1)
    )
    return MessageAnalysisResponse(
        message_id=message.id,
        carrier_name=message.carrier.name,
        processing_status=message.processing_status,
        case_id=message.case_id,
        review_id=review_id,
        model_name=analysis.model_name if analysis else None,
        schema_version=analysis.schema_version if analysis else None,
        prompt_version=analysis.prompt_version if analysis else None,
        overall_confidence=float(analysis.overall_confidence) if analysis else None,
        validation_flags=list(analysis.validation_flags) if analysis else [],
        proposed_result=proposed,
        final_result=final,
        source_content=message.cleaned_content,
        attachments=[attachment_item(item) for item in message.attachments],
    )


def message_analysis_response(
    db: Session, current: AuthContext, message_id: int
) -> MessageAnalysisResponse:
    from app.services.message_processing import authorize_message

    return _message_analysis_response(db, authorize_message(db, current, message_id))


def get_review_detail(db: Session, current: AuthContext, review_id: int) -> ReviewDetailResponse:
    item = get_review_entity(db, current, review_id)
    base = review_item_response(item)
    bundle = build_source_bundle(item.carrier_message, max_chars=get_settings().ai_max_source_chars)
    proposed = None
    if item.carrier_message.analysis is not None:
        try:
            proposed = AnalysisResult.model_validate(
                item.carrier_message.analysis.model_result_json
            )
        except ValueError:
            proposed = None
    ambiguities = verify_interpretation_ambiguities(
        bundle, proposed.interpretation_ambiguities if proposed else []
    )
    issues = [
        ReviewIssue(
            code=f"INTERPRETATION_AMBIGUITY_{index}",
            category="INTERPRETATION_AMBIGUITY",
            title="More than one interpretation is plausible",
            message=(
                f"{ambiguity.explanation} Choose the interpretation best supported by "
                "the available communication."
            ),
            field_name=ambiguity.field_name,
            human_resolvable=True,
            values=[
                ReviewIssueValue(
                    source_id=value.source_id,
                    source_label=value.source_label,
                    value=value.interpretation,
                    excerpt=value.excerpt,
                )
                for value in ambiguity.candidates
            ],
        )
        for index, ambiguity in enumerate(ambiguities, start=1)
    ]
    if not issues and item.reason_code == "CASE_MATCH_CONFLICT":
        from app.services.message_processing import _case_candidates

        candidates = _case_candidates(db, item.carrier_message, proposed) if proposed else []
        accessible_ids = set(
            db.scalars(
                scoped_cases_query(current)
                .where(
                    PolicyCase.id.in_([case.id for case in candidates]),
                    PolicyCase.dismissed_at.is_(None),
                )
                .with_only_columns(PolicyCase.id)
            ).all()
        )
        candidates = [case for case in candidates if case.id in accessible_ids]
        issues.append(
            ReviewIssue(
                code="CASE_MATCH_CONFLICT",
                category="CASE_MATCH_CONFLICT",
                title="Multiple cases match this message",
                message=(
                    "Carrier Hub found more than one agency case with the same reliable "
                    "identity. Confirm the correct case before applying."
                ),
                field_name="case_id",
                human_resolvable=True,
                values=[
                    ReviewIssueValue(
                        source_id=f"case:{case.id}",
                        source_label=f"Existing case {case.id}",
                        value=f"{case.client_name} · {case.policy_number}",
                    )
                    for case in candidates
                ],
            )
        )
    if not issues:
        ownership_issue = item.reason_code in {
            "CASE_OWNER_CONFLICT",
            "OPERATIONAL_OWNER_REQUIRED",
        }
        issues.append(
            ReviewIssue(
                code=item.reason_code,
                category="OWNERSHIP" if ownership_issue else "CONTENT_VALIDATION",
                title=(
                    "Case ownership requires manager attention"
                    if ownership_issue
                    else "Carrier information needs confirmation"
                ),
                message=item.reason,
                human_resolvable=not ownership_issue,
            )
        )
    return ReviewDetailResponse(
        **base.model_dump(),
        analysis=_message_analysis_response(db, item.carrier_message),
        issues=issues,
    )


def update_review(
    db: Session, current: AuthContext, review_id: int, update: ReviewUpdate
) -> ReviewItemResponse:
    if current.user.role is UserRole.MANAGER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Review decisions are completed by the assigned agent",
        )
    get_review_item(db, current, review_id)
    item = db.get(ReviewItem, review_id)
    assert item is not None
    if item.case_id is not None and update.status in {ReviewStatus.OPEN, ReviewStatus.IN_REVIEW}:
        case = db.scalar(select(PolicyCase).where(PolicyCase.id == item.case_id).with_for_update())
        if case is not None and case.completed_at is not None:
            raise HTTPException(
                status_code=409,
                detail="Reopen this case before returning its review to active work",
            )
    item.status = update.status
    item.resolution_notes = update.resolution_notes
    item.resolved_at = (
        utc_now() if update.status in {ReviewStatus.RESOLVED, ReviewStatus.DISMISSED} else None
    )
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        case_id=item.case_id,
        carrier_message_id=item.carrier_message_id,
        event_type="CASE_REVIEWED",
        description=f"Review item moved to {item.status.value.replace('_', ' ').title()}",
    )
    db.commit()
    return get_review_item(db, current, review_id)


def correct_case(
    db: Session,
    current: AuthContext,
    case_id: int,
    correction: CaseCorrectionInput,
) -> CaseDetail:
    query = select(PolicyCase).where(
        PolicyCase.id == case_id,
        PolicyCase.agency_id == current.user.agency_id,
    )
    if current.user.role is UserRole.AGENT:
        query = query.where(PolicyCase.assigned_agent_id == current.user.id)
    case = db.scalar(query)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.dismissed_at is not None:
        raise HTTPException(status_code=409, detail="Restore this case before correcting it")
    if correction.policy_number:
        conflict = db.scalar(
            select(PolicyCase.id).where(
                PolicyCase.agency_id == case.agency_id,
                PolicyCase.carrier_id == case.carrier_id,
                PolicyCase.policy_number == correction.policy_number,
                PolicyCase.id != case.id,
            )
        )
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail="That policy number is already used for this carrier",
            )

    changed_fields: list[str] = []
    enum_changes: dict[str, dict[str, str]] = {}
    values = {
        "client_name": correction.client_name,
        "policy_number": correction.policy_number,
        "current_policy_status": correction.policy_status,
        "priority": correction.priority,
        "summary": correction.summary,
        "premium_amount": correction.premium_amount,
        "currency": correction.currency,
        "effective_date": correction.effective_date,
    }
    for field_name, value in values.items():
        previous = getattr(case, field_name)
        if previous != value:
            setattr(case, field_name, value)
            public_name = "policy_status" if field_name == "current_policy_status" else field_name
            changed_fields.append(public_name)
            if field_name in {"current_policy_status", "priority"}:
                enum_changes[public_name] = {
                    "previous": previous.value,
                    "new": value.value,
                }

    deadline = None
    if correction.deadline is not None:
        try:
            agency_timezone = ZoneInfo(current.agency.timezone)
        except ZoneInfoNotFoundError:
            agency_timezone = UTC
        deadline = datetime.combine(
            correction.deadline, datetime.min.time(), tzinfo=agency_timezone
        ).astimezone(UTC)
    if business_date(case.current_deadline, current.agency.timezone) != correction.deadline:
        case.current_deadline = deadline
        changed_fields.append("deadline")

    if not changed_fields:
        return get_case_detail(db, current, case_id)
    record_audit_event(
        db,
        agency_id=case.agency_id,
        actor_user_id=current.user.id,
        case_id=case.id,
        event_type="CASE_CORRECTED",
        description=(
            "Case information corrected by manager"
            if current.user.role is UserRole.MANAGER
            else "Case information corrected by the assigned agent"
        ),
        metadata={
            "changed_fields": changed_fields,
            "reason": correction.reason,
            "enum_changes": enum_changes,
        },
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="That policy number is already used for this carrier",
        ) from error
    return get_case_detail(db, current, case_id)
