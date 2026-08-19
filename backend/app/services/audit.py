from typing import Any

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.audit import AuditEvent
from app.models.enums import AuditSeverity


def record_audit_event(
    db: Session,
    *,
    agency_id: int,
    event_type: str,
    description: str,
    actor_user_id: int | None = None,
    case_id: int | None = None,
    carrier_message_id: int | None = None,
    task_id: int | None = None,
    severity: AuditSeverity = AuditSeverity.INFO,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        agency_id=agency_id,
        actor_user_id=actor_user_id,
        case_id=case_id,
        carrier_message_id=carrier_message_id,
        task_id=task_id,
        event_type=event_type,
        severity=severity,
        description=description,
        event_metadata=metadata or {},
        created_at=utc_now(),
    )
    db.add(event)
    return event
