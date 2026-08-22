from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.dependencies import AgentUser, CsrfUser, CurrentUser, DbSession, ManagerCsrfUser
from app.api.schemas.domain import (
    AuditLogResponse,
    CaseAssignmentInput,
    CaseCorrectionInput,
    CaseDetail,
    CaseListResponse,
    DashboardResponse,
    ManualTaskCreate,
    ReviewItemResponse,
    ReviewListResponse,
    ReviewUpdate,
    TaskItem,
    TaskListResponse,
    TaskUpdate,
)
from app.models.enums import PolicyStatus, Priority, ReviewStatus, TaskStatus
from app.services import operations as operations_service
from app.services import reporting

router = APIRouter(tags=["operations"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
TaskStatusFilter = Annotated[TaskStatus | None, Query(alias="status")]
ReviewStatusFilter = Annotated[ReviewStatus | None, Query(alias="status")]


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(current: CurrentUser, db: DbSession) -> DashboardResponse:
    return reporting.dashboard(db, current)


@router.get("/cases", response_model=CaseListResponse)
def get_cases(
    current: CurrentUser,
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 10,
    search: str | None = None,
    carrier_id: int | None = None,
    policy_status: PolicyStatus | None = None,
    priority: Priority | None = None,
    assigned_agent_id: int | None = None,
    include_dismissed: bool = False,
) -> CaseListResponse:
    return operations_service.list_cases(
        db,
        current,
        page=page,
        page_size=page_size,
        search=search,
        carrier_id=carrier_id,
        policy_status=policy_status,
        priority=priority,
        assigned_agent_id=assigned_agent_id,
        include_dismissed=include_dismissed,
    )


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: int, current: CurrentUser, db: DbSession) -> CaseDetail:
    return operations_service.get_case_detail(db, current, case_id)


@router.post("/cases/{case_id}/dismiss", response_model=CaseDetail)
def dismiss_case(case_id: int, current: CsrfUser, db: DbSession) -> CaseDetail:
    return operations_service.set_case_dismissed(db, current, case_id, dismissed=True)


@router.post("/cases/{case_id}/restore", response_model=CaseDetail)
def restore_case(case_id: int, current: CsrfUser, db: DbSession) -> CaseDetail:
    return operations_service.set_case_dismissed(db, current, case_id, dismissed=False)


@router.patch("/cases/{case_id}/correction", response_model=CaseDetail)
def correct_case(
    case_id: int, data: CaseCorrectionInput, current: CsrfUser, db: DbSession
) -> CaseDetail:
    return operations_service.correct_case(db, current, case_id, data)


@router.patch("/cases/{case_id}/assignment", response_model=CaseDetail)
def assign_case(
    case_id: int,
    data: CaseAssignmentInput,
    current: ManagerCsrfUser,
    db: DbSession,
) -> CaseDetail:
    return operations_service.assign_case(db, current, case_id, data.assigned_agent_id)


@router.get("/tasks", response_model=TaskListResponse)
def get_tasks(
    current: CurrentUser,
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 10,
    task_status: TaskStatusFilter = None,
    priority: Priority | None = None,
    overdue: bool | None = None,
    assigned_agent_id: int | None = None,
    task_view: Annotated[
        Literal["TODO", "OPEN", "IN_PROGRESS", "COMPLETED", "DISMISSED", "ALL"],
        Query(alias="view"),
    ] = "TODO",
) -> TaskListResponse:
    return operations_service.list_tasks(
        db,
        current,
        page=page,
        page_size=page_size,
        task_status=task_status,
        priority=priority,
        overdue=overdue,
        assigned_agent_id=assigned_agent_id,
        task_view=task_view,
    )


@router.post("/cases/{case_id}/tasks", response_model=TaskItem, status_code=201)
def create_manual_task(
    case_id: int, data: ManualTaskCreate, current: CsrfUser, db: DbSession
) -> TaskItem:
    return operations_service.create_manual_task(db, current, case_id, data)


@router.patch("/tasks/{task_id}", response_model=TaskItem)
def patch_task(task_id: int, data: TaskUpdate, current: CsrfUser, db: DbSession) -> TaskItem:
    return operations_service.update_task(db, current, task_id, data)


@router.get("/reviews", response_model=ReviewListResponse)
def get_reviews(
    current: CurrentUser,
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 8,
    review_status: ReviewStatusFilter = None,
    review_view: Annotated[
        Literal["ACTIONABLE", "RESOLVED", "DISMISSED", "ALL"], Query(alias="view")
    ] = "ACTIONABLE",
) -> ReviewListResponse:
    return operations_service.list_reviews(
        db,
        current,
        page=page,
        page_size=page_size,
        review_status=review_status,
        review_view=review_view,
    )


@router.get("/activity", response_model=AuditLogResponse)
def get_activity(
    current: AgentUser,
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 50,
    action_group: str | None = None,
) -> AuditLogResponse:
    return reporting.activity_logs(
        db,
        current,
        page=page,
        page_size=page_size,
        action_group=action_group,
    )


@router.get("/reviews/{review_id}", response_model=ReviewItemResponse)
def get_review(review_id: int, current: CurrentUser, db: DbSession) -> ReviewItemResponse:
    return operations_service.get_review_item(db, current, review_id)


@router.patch("/reviews/{review_id}", response_model=ReviewItemResponse)
def patch_review(
    review_id: int, data: ReviewUpdate, current: CsrfUser, db: DbSession
) -> ReviewItemResponse:
    return operations_service.update_review(db, current, review_id, data)
