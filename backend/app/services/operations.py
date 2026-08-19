import math

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.schemas.domain import (
    ActivityItem,
    AgentBrief,
    AttachmentItem,
    CarrierBrief,
    CaseDetail,
    CaseListItem,
    CaseListResponse,
    EvidenceItem,
    MessageItem,
    PageInfo,
    ReviewItemResponse,
    ReviewListResponse,
    ReviewUpdate,
    TaskItem,
    TaskListResponse,
    TaskUpdate,
)
from app.core.time import utc_now
from app.models.audit import AuditEvent
from app.models.enums import PolicyStatus, Priority, ReviewStatus, TaskStatus, UserRole
from app.models.operations import CarrierMessage, PolicyCase, ReviewItem, Task
from app.models.organization import User
from app.services.audit import record_audit_event
from app.services.auth import AuthContext


def page_info(page: int, page_size: int, total: int) -> PageInfo:
    return PageInfo(
        page=page,
        page_size=page_size,
        total=total,
        pages=max(1, math.ceil(total / page_size)),
    )


def agent_brief(user: User) -> AgentBrief:
    return AgentBrief(id=user.id, full_name=user.full_name, email=user.email)


def task_item(task: Task) -> TaskItem:
    return TaskItem(
        id=task.id,
        case_id=task.case_id,
        client_name=task.case.client_name,
        policy_number=task.case.policy_number,
        title=task.title,
        description=task.description,
        priority=task.priority,
        due_at=task.due_at,
        status=task.status,
        completed_at=task.completed_at,
        assigned_agent=agent_brief(task.assigned_agent),
    )


def case_item(case: PolicyCase) -> CaseListItem:
    return CaseListItem(
        id=case.id,
        client_name=case.client_name,
        policy_number=case.policy_number,
        policy_status=case.current_policy_status,
        priority=case.priority,
        summary=case.summary,
        deadline=case.current_deadline,
        updated_at=case.updated_at,
        carrier=CarrierBrief(id=case.carrier.id, name=case.carrier.name, code=case.carrier.code),
        assigned_agent=agent_brief(case.assigned_agent) if case.assigned_agent else None,
        needs_review=any(
            item.status in {ReviewStatus.OPEN, ReviewStatus.IN_REVIEW} for item in case.reviews
        ),
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
) -> CaseListResponse:
    query = scoped_cases_query(current)
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
    cases = db.scalars(
        query.options(
            joinedload(PolicyCase.carrier),
            joinedload(PolicyCase.assigned_agent),
            selectinload(PolicyCase.reviews),
        )
        .order_by(PolicyCase.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return CaseListResponse(
        items=[case_item(case) for case in cases], page=page_info(page, page_size, total)
    )


def get_case_detail(db: Session, current: AuthContext, case_id: int) -> CaseDetail:
    query = (
        scoped_cases_query(current)
        .where(PolicyCase.id == case_id)
        .options(
            joinedload(PolicyCase.carrier),
            joinedload(PolicyCase.assigned_agent),
            selectinload(PolicyCase.reviews),
            selectinload(PolicyCase.messages).selectinload(CarrierMessage.attachments),
            selectinload(PolicyCase.tasks).joinedload(Task.assigned_agent),
            selectinload(PolicyCase.evidence),
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
    base = case_item(case).model_dump()
    return CaseDetail(
        **base,
        premium_amount=case.premium_amount,
        currency=case.currency,
        effective_date=case.effective_date,
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
            )
            for message in case.messages
        ],
        attachments=[
            AttachmentItem(
                id=attachment.id,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
                size_bytes=attachment.size_bytes,
                processing_status=attachment.processing_status,
            )
            for message in case.messages
            for attachment in message.attachments
        ],
        tasks=[task_item(task) for task in case.tasks],
        evidence=[
            EvidenceItem(
                id=evidence.id,
                field_name=evidence.field_name,
                source_type=evidence.source_type,
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
) -> TaskListResponse:
    query = select(Task).where(Task.agency_id == current.user.agency_id)
    if current.user.role is UserRole.AGENT:
        query = query.where(Task.assigned_agent_id == current.user.id)
    elif assigned_agent_id:
        query = query.where(Task.assigned_agent_id == assigned_agent_id)
    if task_status:
        query = query.where(Task.status == task_status)
    if priority:
        query = query.where(Task.priority == priority)
    if overdue is True:
        query = query.where(
            Task.due_at < utc_now(), Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS])
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    tasks = db.scalars(
        query.options(joinedload(Task.case), joinedload(Task.assigned_agent))
        .order_by(Task.due_at.asc().nullslast(), Task.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return TaskListResponse(
        items=[task_item(task) for task in tasks], page=page_info(page, page_size, total)
    )


def update_task(db: Session, current: AuthContext, task_id: int, update: TaskUpdate) -> TaskItem:
    task = db.scalar(
        select(Task)
        .options(joinedload(Task.case), joinedload(Task.assigned_agent))
        .where(Task.id == task_id, Task.agency_id == current.user.agency_id)
    )
    if task is None or (
        current.user.role is UserRole.AGENT and task.assigned_agent_id != current.user.id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    previous_status = task.status
    if update.status is not None:
        task.status = update.status
        task.completed_at = utc_now() if update.status is TaskStatus.COMPLETED else None
    if update.assigned_agent_id is not None:
        if current.user.role is not UserRole.MANAGER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Manager access required"
            )
        assignee = db.scalar(
            select(User).where(
                User.id == update.assigned_agent_id,
                User.agency_id == current.user.agency_id,
                User.is_active.is_(True),
            )
        )
        if assignee is None:
            raise HTTPException(status_code=422, detail="Assigned agent is invalid")
        task.assigned_agent = assignee
        task.assigned_agent_id = assignee.id

    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        case_id=task.case_id,
        task_id=task.id,
        event_type="TASK_STATUS_CHANGED" if update.status else "TASK_ASSIGNED",
        description=f"Task updated: {task.title}",
        metadata={"previous_status": previous_status.value, "new_status": task.status.value},
    )
    db.commit()
    db.refresh(task)
    return task_item(task)


def list_reviews(
    db: Session,
    current: AuthContext,
    *,
    page: int,
    page_size: int,
    review_status: ReviewStatus | None,
) -> ReviewListResponse:
    query = select(ReviewItem).where(ReviewItem.agency_id == current.user.agency_id)
    if current.user.role is UserRole.AGENT:
        query = query.join(PolicyCase, ReviewItem.case_id == PolicyCase.id, isouter=True).where(
            or_(
                ReviewItem.assigned_reviewer_id == current.user.id,
                PolicyCase.assigned_agent_id == current.user.id,
            )
        )
    if review_status:
        query = query.where(ReviewItem.status == review_status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    reviews = (
        db.scalars(
            query.options(
                joinedload(ReviewItem.case),
                joinedload(ReviewItem.carrier_message).joinedload(CarrierMessage.carrier),
                joinedload(ReviewItem.assigned_reviewer),
            )
            .order_by(ReviewItem.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .unique()
        .all()
    )
    items = [
        ReviewItemResponse(
            id=item.id,
            case_id=item.case_id,
            client_name=item.case.client_name if item.case else None,
            policy_number=item.case.policy_number if item.case else None,
            carrier_name=item.carrier_message.carrier.name,
            message_subject=item.carrier_message.subject,
            reason_code=item.reason_code,
            reason=item.reason,
            status=item.status,
            resolution_notes=item.resolution_notes,
            assigned_reviewer=(
                agent_brief(item.assigned_reviewer) if item.assigned_reviewer else None
            ),
            created_at=item.created_at,
            resolved_at=item.resolved_at,
        )
        for item in reviews
    ]
    return ReviewListResponse(items=items, page=page_info(page, page_size, total))


def get_review_item(db: Session, current: AuthContext, review_id: int) -> ReviewItemResponse:
    query = (
        select(ReviewItem)
        .where(
            ReviewItem.id == review_id,
            ReviewItem.agency_id == current.user.agency_id,
        )
        .options(
            joinedload(ReviewItem.case),
            joinedload(ReviewItem.carrier_message).joinedload(CarrierMessage.carrier),
            joinedload(ReviewItem.assigned_reviewer),
        )
    )
    if current.user.role is UserRole.AGENT:
        query = query.join(PolicyCase, ReviewItem.case_id == PolicyCase.id, isouter=True).where(
            or_(
                ReviewItem.assigned_reviewer_id == current.user.id,
                PolicyCase.assigned_agent_id == current.user.id,
            )
        )
    item = db.scalar(query)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return ReviewItemResponse(
        id=item.id,
        case_id=item.case_id,
        client_name=item.case.client_name if item.case else None,
        policy_number=item.case.policy_number if item.case else None,
        carrier_name=item.carrier_message.carrier.name,
        message_subject=item.carrier_message.subject,
        reason_code=item.reason_code,
        reason=item.reason,
        status=item.status,
        resolution_notes=item.resolution_notes,
        assigned_reviewer=(agent_brief(item.assigned_reviewer) if item.assigned_reviewer else None),
        created_at=item.created_at,
        resolved_at=item.resolved_at,
    )


def update_review(
    db: Session, current: AuthContext, review_id: int, update: ReviewUpdate
) -> ReviewItemResponse:
    get_review_item(db, current, review_id)
    item = db.get(ReviewItem, review_id)
    assert item is not None
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
