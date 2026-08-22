from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.dependencies import DbSession, ManagerCsrfUser, ManagerUser
from app.api.schemas.domain import (
    AgentCreateInput,
    AgentListItem,
    AgentListResponse,
    AnalyticsResponse,
    AuditLogResponse,
    CarrierItem,
    CarrierWrite,
    DomainWrite,
    EnabledUpdate,
    SenderWrite,
)
from app.models.enums import AuditSeverity
from app.services import agents as agent_service
from app.services import carriers as carrier_service
from app.services import reporting

router = APIRouter(prefix="/manager", tags=["manager"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/agents", response_model=AgentListResponse)
def agents(
    current: ManagerUser, db: DbSession, page: Page = 1, page_size: PageSize = 10
) -> AgentListResponse:
    return reporting.list_agents(db, current, page=page, page_size=page_size)


@router.post("/agents", response_model=AgentListItem, status_code=201)
def create_agent(data: AgentCreateInput, current: ManagerCsrfUser, db: DbSession) -> AgentListItem:
    agent = agent_service.create_agent(db, current, data)
    return reporting.agent_list_item(db, agent)


@router.patch("/agents/{agent_id}", response_model=AgentListItem)
def set_agent_enabled(
    agent_id: int, data: EnabledUpdate, current: ManagerCsrfUser, db: DbSession
) -> AgentListItem:
    agent = agent_service.set_agent_enabled(db, current, agent_id, is_enabled=data.is_enabled)
    return reporting.agent_list_item(db, agent)


@router.delete("/agents/{agent_id}", status_code=204)
def remove_agent(agent_id: int, current: ManagerCsrfUser, db: DbSession) -> None:
    agent_service.remove_agent(db, current, agent_id)


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


@router.delete("/carriers/{carrier_id}", status_code=204)
def delete_carrier(carrier_id: int, current: ManagerCsrfUser, db: DbSession) -> None:
    carrier_service.delete_carrier(db, current, carrier_id)


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
def analytics(
    current: ManagerUser,
    db: DbSession,
    range: Literal["7d", "30d", "90d", "all"] = "30d",
) -> AnalyticsResponse:
    return reporting.analytics(db, current, time_range=range)


@router.get("/audit-events", response_model=AuditLogResponse)
def audit_events(
    current: ManagerUser,
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 50,
    event_type: str | None = None,
    severity: AuditSeverity | None = None,
    actor: str | None = None,
    category: str | None = None,
) -> AuditLogResponse:
    return reporting.audit_logs(
        db,
        current,
        page=page,
        page_size=page_size,
        event_type=event_type,
        severity=severity,
        actor=actor,
        category=category,
    )
