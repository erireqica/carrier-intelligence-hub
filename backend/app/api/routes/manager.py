from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import DbSession, ManagerCsrfUser, ManagerUser
from app.api.schemas.domain import (
    AgentListItem,
    AnalyticsResponse,
    AuditLogResponse,
    CarrierItem,
    CarrierWrite,
    DomainWrite,
    EnabledUpdate,
    SenderWrite,
)
from app.models.enums import AuditSeverity
from app.services import carriers as carrier_service
from app.services import reporting

router = APIRouter(prefix="/manager", tags=["manager"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/agents", response_model=list[AgentListItem])
def agents(current: ManagerUser, db: DbSession) -> list[AgentListItem]:
    return reporting.list_agents(db, current)


@router.get("/carriers", response_model=list[CarrierItem])
def carriers(current: ManagerUser, db: DbSession) -> list[CarrierItem]:
    return carrier_service.list_carriers(db, current)


@router.post("/carriers", response_model=CarrierItem, status_code=201)
def create_carrier(data: CarrierWrite, current: ManagerCsrfUser, db: DbSession) -> CarrierItem:
    return carrier_service.create_carrier(db, current, data)


@router.put("/carriers/{carrier_id}", response_model=CarrierItem)
def update_carrier(
    carrier_id: int, data: CarrierWrite, current: ManagerCsrfUser, db: DbSession
) -> CarrierItem:
    return carrier_service.update_carrier(db, current, carrier_id, data)


@router.post("/carriers/{carrier_id}/domains", response_model=CarrierItem)
def add_domain(
    carrier_id: int, data: DomainWrite, current: ManagerCsrfUser, db: DbSession
) -> CarrierItem:
    return carrier_service.add_domain(db, current, carrier_id, data)


@router.patch("/carriers/{carrier_id}/domains/{domain_id}", response_model=CarrierItem)
def update_domain(
    carrier_id: int,
    domain_id: int,
    data: EnabledUpdate,
    current: ManagerCsrfUser,
    db: DbSession,
) -> CarrierItem:
    return carrier_service.set_whitelist_enabled(
        db,
        current,
        carrier_id=carrier_id,
        item_id=domain_id,
        item_type="domain",
        is_enabled=data.is_enabled,
    )


@router.delete("/carriers/{carrier_id}/domains/{domain_id}", response_model=CarrierItem)
def remove_domain(
    carrier_id: int,
    domain_id: int,
    current: ManagerCsrfUser,
    db: DbSession,
) -> CarrierItem:
    return carrier_service.remove_whitelist_entry(
        db,
        current,
        carrier_id=carrier_id,
        item_id=domain_id,
        item_type="domain",
    )


@router.post("/carriers/{carrier_id}/senders", response_model=CarrierItem)
def add_sender(
    carrier_id: int, data: SenderWrite, current: ManagerCsrfUser, db: DbSession
) -> CarrierItem:
    return carrier_service.add_sender(db, current, carrier_id, data)


@router.patch("/carriers/{carrier_id}/senders/{sender_id}", response_model=CarrierItem)
def update_sender(
    carrier_id: int,
    sender_id: int,
    data: EnabledUpdate,
    current: ManagerCsrfUser,
    db: DbSession,
) -> CarrierItem:
    return carrier_service.set_whitelist_enabled(
        db,
        current,
        carrier_id=carrier_id,
        item_id=sender_id,
        item_type="sender",
        is_enabled=data.is_enabled,
    )


@router.delete("/carriers/{carrier_id}/senders/{sender_id}", response_model=CarrierItem)
def remove_sender(
    carrier_id: int,
    sender_id: int,
    current: ManagerCsrfUser,
    db: DbSession,
) -> CarrierItem:
    return carrier_service.remove_whitelist_entry(
        db,
        current,
        carrier_id=carrier_id,
        item_id=sender_id,
        item_type="sender",
    )


@router.get("/analytics", response_model=AnalyticsResponse)
def analytics(current: ManagerUser, db: DbSession) -> AnalyticsResponse:
    return reporting.analytics(db, current)


@router.get("/audit-events", response_model=AuditLogResponse)
def audit_events(
    current: ManagerUser,
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 50,
    event_type: str | None = None,
    severity: AuditSeverity | None = None,
) -> AuditLogResponse:
    return reporting.audit_logs(
        db,
        current,
        page=page,
        page_size=page_size,
        event_type=event_type,
        severity=severity,
    )


@router.get("/activity", response_model=AuditLogResponse)
def activity(
    current: ManagerUser,
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 50,
    actor_user_id: int | None = None,
    action_group: str | None = None,
    include_system: bool = False,
) -> AuditLogResponse:
    return reporting.activity_logs(
        db,
        current,
        page=page,
        page_size=page_size,
        actor_user_id=actor_user_id,
        action_group=action_group,
        include_system=include_system,
    )
