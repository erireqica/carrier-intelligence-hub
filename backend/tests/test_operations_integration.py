import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.audit import AuditEvent
from app.models.carriers import Carrier, CarrierDomain, CarrierSender
from app.models.enums import (
    GmailConnectionStatus,
    ProcessingStatus,
    TaskStatus,
)
from app.models.operations import CarrierMessage, PolicyCase, ReviewItem, Task
from app.models.organization import Agency, GmailConnection, User


def test_role_authorization_case_and_task_scoping(client: TestClient, db: Session, login) -> None:
    agent_auth = login(client, "agent.one@demo.local")
    assert client.get("/api/v1/manager/agents").status_code == 403

    cases = client.get("/api/v1/cases")
    assert cases.status_code == 200
    names = {item["client_name"] for item in cases.json()["items"]}
    assert names == {"John Doe", "Robert Johnson"}
    mary = db.scalar(select(PolicyCase).where(PolicyCase.client_name == "Mary Smith"))
    assert mary is not None
    assert client.get(f"/api/v1/cases/{mary.id}").status_code == 404

    mary_task = db.scalar(select(Task).where(Task.case_id == mary.id))
    assert mary_task is not None
    denied = client.patch(
        f"/api/v1/tasks/{mary_task.id}",
        json={"status": "COMPLETED"},
        headers={"X-CSRF-Token": agent_auth["csrf_token"]},
    )
    assert denied.status_code == 404

    own_task = db.scalar(
        select(Task)
        .join(User, Task.assigned_agent_id == User.id)
        .where(User.email == "agent.one@demo.local", Task.status != TaskStatus.COMPLETED)
    )
    assert own_task is not None
    assert (
        client.patch(f"/api/v1/tasks/{own_task.id}", json={"status": "COMPLETED"}).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/tasks/{own_task.id}",
            json={"status": "COMPLETED"},
            headers={"X-CSRF-Token": "invalid"},
        ).status_code
        == 403
    )
    updated = client.patch(
        f"/api/v1/tasks/{own_task.id}",
        json={"status": "COMPLETED"},
        headers={"X-CSRF-Token": agent_auth["csrf_token"]},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "COMPLETED"
    assert updated.json()["completed_at"] is not None
    assert db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.event_type == "TASK_STATUS_CHANGED", AuditEvent.task_id == own_task.id)
    )

    review = db.scalar(select(ReviewItem).where(ReviewItem.status == "OPEN"))
    assert review is not None
    assert client.get("/api/v1/reviews").json()["page"]["total"] == 1
    login(client, "agent.two@demo.local")
    assert client.get("/api/v1/reviews").json()["page"]["total"] == 0
    assert client.get(f"/api/v1/reviews/{review.id}").status_code == 404

    manager_auth = login(client, "manager@demo.local")
    assert client.get("/api/v1/manager/agents").status_code == 200
    assert client.get("/api/v1/cases").json()["page"]["total"] == 3
    analytics = client.get("/api/v1/manager/analytics")
    assert analytics.status_code == 200
    assert analytics.json()["cases_by_carrier"] == {
        "Aetna": 1,
        "Americo": 1,
        "American Amicable / AMAM": 1,
    }
    reassigned = client.patch(
        f"/api/v1/tasks/{mary_task.id}",
        json={"assigned_agent_id": manager_auth["user"]["id"]},
        headers={"X-CSRF-Token": manager_auth["csrf_token"]},
    )
    assert reassigned.status_code == 200


def test_manager_carrier_whitelist_and_review_workflows(
    client: TestClient, db: Session, login
) -> None:
    auth = login(client, "manager@demo.local")
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    created = client.post(
        "/api/v1/manager/carriers",
        json={"name": "Example Mutual", "code": "EXM", "is_enabled": True},
        headers=headers,
    )
    assert created.status_code == 201
    carrier_id = created.json()["id"]
    duplicate = client.post(
        "/api/v1/manager/carriers",
        json={"name": "Example Mutual", "code": "EXM", "is_enabled": True},
        headers=headers,
    )
    assert duplicate.status_code == 409

    domain = client.post(
        f"/api/v1/manager/carriers/{carrier_id}/domains",
        json={"domain": "@EXAMPLE.COM", "is_enabled": True},
        headers=headers,
    )
    assert domain.status_code == 200
    domain_id = domain.json()["domains"][0]["id"]
    assert domain.json()["domains"][0]["domain"] == "example.com"
    assert (
        client.post(
            f"/api/v1/manager/carriers/{carrier_id}/domains",
            json={"domain": "example.com", "is_enabled": True},
            headers=headers,
        ).status_code
        == 409
    )
    toggled = client.patch(
        f"/api/v1/manager/carriers/{carrier_id}/domains/{domain_id}",
        json={"is_enabled": False},
        headers=headers,
    )
    assert toggled.json()["domains"][0]["is_enabled"] is False

    sender = client.post(
        f"/api/v1/manager/carriers/{carrier_id}/senders",
        json={"email": "Notices@Example.COM", "is_enabled": True},
        headers=headers,
    )
    sender_id = sender.json()["senders"][0]["id"]
    assert sender.json()["senders"][0]["email"] == "notices@example.com"
    assert (
        client.post(
            f"/api/v1/manager/carriers/{carrier_id}/senders",
            json={"email": "notices@example.com", "is_enabled": True},
            headers=headers,
        ).status_code
        == 409
    )
    assert (
        client.delete(
            f"/api/v1/manager/carriers/{carrier_id}/senders/{sender_id}", headers=headers
        ).json()["senders"]
        == []
    )
    assert (
        client.delete(
            f"/api/v1/manager/carriers/{carrier_id}/domains/{domain_id}", headers=headers
        ).json()["domains"]
        == []
    )

    review = db.scalar(select(ReviewItem).where(ReviewItem.status == "OPEN"))
    assert review is not None
    in_review = client.patch(
        f"/api/v1/reviews/{review.id}",
        json={
            "status": "IN_REVIEW",
            "resolution_notes": "Reviewed against the source email.",
        },
        headers=headers,
    )
    assert in_review.status_code == 200
    assert in_review.json()["status"] == "IN_REVIEW"
    assert in_review.json()["resolved_at"] is None
    for terminal in ("RESOLVED", "DISMISSED"):
        rejected = client.patch(
            f"/api/v1/reviews/{review.id}",
            json={"status": terminal, "resolution_notes": "Bypass attempt."},
            headers=headers,
        )
        assert rejected.status_code == 422
    db.refresh(review)
    assert review.status.value == "IN_REVIEW"
    logs = client.get("/api/v1/manager/audit-events?page_size=100")
    assert logs.status_code == 200
    event_types = {item["event_type"] for item in logs.json()["items"]}
    assert {"CARRIER_CREATED", "WHITELIST_UPDATED", "CASE_REVIEWED"} <= event_types


def test_seed_is_idempotent(seeded_db: Session) -> None:
    from app.db.seed import seed_demo_data

    before = {
        "agencies": seeded_db.scalar(select(func.count()).select_from(Agency)),
        "users": seeded_db.scalar(select(func.count()).select_from(User)),
        "carriers": seeded_db.scalar(select(func.count()).select_from(Carrier)),
        "domains": seeded_db.scalar(select(func.count()).select_from(CarrierDomain)),
        "senders": seeded_db.scalar(select(func.count()).select_from(CarrierSender)),
        "cases": seeded_db.scalar(select(func.count()).select_from(PolicyCase)),
        "tasks": seeded_db.scalar(select(func.count()).select_from(Task)),
        "reviews": seeded_db.scalar(select(func.count()).select_from(ReviewItem)),
    }
    seed_demo_data(seeded_db, "demo-test-password")
    after = {
        "agencies": seeded_db.scalar(select(func.count()).select_from(Agency)),
        "users": seeded_db.scalar(select(func.count()).select_from(User)),
        "carriers": seeded_db.scalar(select(func.count()).select_from(Carrier)),
        "domains": seeded_db.scalar(select(func.count()).select_from(CarrierDomain)),
        "senders": seeded_db.scalar(select(func.count()).select_from(CarrierSender)),
        "cases": seeded_db.scalar(select(func.count()).select_from(PolicyCase)),
        "tasks": seeded_db.scalar(select(func.count()).select_from(Task)),
        "reviews": seeded_db.scalar(select(func.count()).select_from(ReviewItem)),
    }
    assert before == after


def test_carrier_messages_support_pre_analysis_lifecycle(seeded_db: Session) -> None:
    agency = seeded_db.scalar(select(Agency))
    carrier = seeded_db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    assert agency is not None and carrier is not None

    for processing_status in (
        ProcessingStatus.RECEIVED,
        ProcessingStatus.PROCESSING,
        ProcessingStatus.FAILED,
        ProcessingStatus.NEEDS_REVIEW,
    ):
        seeded_db.add(
            CarrierMessage(
                agency_id=agency.id,
                carrier_id=carrier.id,
                gmail_message_id=f"lifecycle-{processing_status.value.lower()}",
                sender="lifecycle@example.test",
                subject=f"Lifecycle {processing_status.value}",
                received_at=utc_now(),
                classification=None,
                summary=None,
                priority=None,
                processing_status=processing_status,
                raw_content="Synthetic source message.",
                cleaned_content="Synthetic source message.",
            )
        )
    seeded_db.flush()

    processed_messages = seeded_db.scalars(
        select(CarrierMessage).where(CarrierMessage.processing_status == ProcessingStatus.PROCESSED)
    ).all()
    assert processed_messages
    assert all(
        message.classification is not None
        and message.summary is not None
        and message.priority is not None
        for message in processed_messages
    )

    with pytest.raises(IntegrityError), seeded_db.begin_nested():
        seeded_db.add(
            CarrierMessage(
                agency_id=agency.id,
                carrier_id=carrier.id,
                gmail_message_id="invalid-processed-message",
                sender="lifecycle@example.test",
                subject="Invalid processed message",
                received_at=utc_now(),
                classification=None,
                summary=None,
                priority=None,
                processing_status=ProcessingStatus.PROCESSED,
                raw_content="Synthetic source message.",
                cleaned_content="Synthetic source message.",
            )
        )
        seeded_db.flush()


def test_case_detail_serializes_unanalyzed_message(client: TestClient, db: Session, login) -> None:
    case = db.scalar(select(PolicyCase).where(PolicyCase.client_name == "John Doe"))
    assert case is not None
    message = CarrierMessage(
        agency_id=case.agency_id,
        case_id=case.id,
        carrier_id=case.carrier_id,
        gmail_message_id="case-detail-processing-message",
        sender="lifecycle@example.test",
        subject="New source awaiting analysis",
        received_at=utc_now(),
        classification=None,
        summary=None,
        priority=None,
        processing_status=ProcessingStatus.PROCESSING,
        raw_content="Synthetic source message.",
        cleaned_content="Synthetic source message.",
    )
    db.add(message)
    db.commit()

    login(client, "agent.one@demo.local")
    response = client.get(f"/api/v1/cases/{case.id}")
    assert response.status_code == 200
    payload = next(
        item
        for item in response.json()["messages"]
        if item["subject"] == "New source awaiting analysis"
    )
    assert payload["processing_status"] == "PROCESSING"
    assert payload["classification"] is None
    assert payload["summary"] is None
    assert payload["priority"] is None


def test_dashboard_gmail_health_states(client: TestClient, db: Session, login) -> None:
    login(client, "agent.one@demo.local")
    dashboard = client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["gmail_connected"] is False
    assert dashboard.json()["gmail_health"] == "NOT_CONNECTED"


@pytest.mark.parametrize(
    ("connection_status", "expected_connected", "expected_health"),
    [
        (GmailConnectionStatus.CONNECTED, True, "CONNECTED"),
        (GmailConnectionStatus.NEEDS_REAUTH, False, "NEEDS_ATTENTION"),
        (GmailConnectionStatus.ERROR, False, "NEEDS_ATTENTION"),
        (GmailConnectionStatus.DISCONNECTED, False, "NOT_CONNECTED"),
    ],
)
def test_dashboard_gmail_health_reflects_connection_status(
    client: TestClient,
    db: Session,
    login,
    connection_status: GmailConnectionStatus,
    expected_connected: bool,
    expected_health: str,
) -> None:
    owner = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    db.add(
        GmailConnection(
            agency_id=owner.agency_id,
            user_id=owner.id,
            gmail_address=f"{connection_status.value.lower()}@example.test",
            status=connection_status,
        )
    )
    db.commit()

    login(client, owner.email)
    payload = client.get("/api/v1/dashboard").json()
    assert payload["gmail_connected"] is expected_connected
    assert payload["gmail_health"] == expected_health


def test_dashboard_gmail_health_respects_agent_scope(
    client: TestClient, db: Session, login
) -> None:
    other_agent = db.scalar(select(User).where(User.email == "agent.two@demo.local"))
    assert other_agent is not None
    db.add(
        GmailConnection(
            agency_id=other_agent.agency_id,
            user_id=other_agent.id,
            gmail_address="other-agent@example.test",
            status=GmailConnectionStatus.CONNECTED,
        )
    )
    db.commit()

    login(client, "agent.one@demo.local")
    assert client.get("/api/v1/dashboard").json()["gmail_health"] == "NOT_CONNECTED"
    login(client, "manager@demo.local")
    assert client.get("/api/v1/dashboard").json()["gmail_health"] == "CONNECTED"


def test_task_patch_validation_and_change_specific_audits(
    client: TestClient, db: Session, login
) -> None:
    auth = login(client, "manager@demo.local")
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    task = db.scalar(select(Task).where(Task.status == TaskStatus.OPEN))
    target_agent = db.scalar(select(User).where(User.email == "agent.two@demo.local"))
    original_agent = (
        db.scalar(select(User).where(User.id == task.assigned_agent_id)) if task else None
    )
    assert task is not None and target_agent is not None and original_agent is not None

    assert client.patch(f"/api/v1/tasks/{task.id}", json={}, headers=headers).status_code == 422
    assert (
        client.patch(
            f"/api/v1/tasks/{task.id}",
            json={"status": None, "assigned_agent_id": None},
            headers=headers,
        ).status_code
        == 422
    )

    no_op = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"status": task.status.value, "assigned_agent_id": task.assigned_agent_id},
        headers=headers,
    )
    assert no_op.status_code == 200
    assert (
        db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.task_id == task.id))
        == 0
    )

    completed = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"status": "COMPLETED"},
        headers=headers,
    )
    assert completed.status_code == 200
    assert completed.json()["completed_at"] is not None
    status_event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.task_id == task.id,
            AuditEvent.event_type == "TASK_STATUS_CHANGED",
        )
    )
    assert status_event is not None
    assert status_event.event_metadata == {
        "previous_status": "OPEN",
        "new_status": "COMPLETED",
    }

    reassigned = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"assigned_agent_id": target_agent.id},
        headers=headers,
    )
    assert reassigned.status_code == 200
    assignment_event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.task_id == task.id,
            AuditEvent.event_type == "TASK_ASSIGNED",
        )
    )
    assert assignment_event is not None
    assert assignment_event.event_metadata == {
        "previous_assignee_id": original_agent.id,
        "new_assignee_id": target_agent.id,
    }

    combined = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"status": "IN_PROGRESS", "assigned_agent_id": original_agent.id},
        headers=headers,
    )
    assert combined.status_code == 200
    assert combined.json()["completed_at"] is None
    event_counts = dict(
        db.execute(
            select(AuditEvent.event_type, func.count())
            .where(AuditEvent.task_id == task.id)
            .group_by(AuditEvent.event_type)
        ).all()
    )
    assert event_counts == {"TASK_ASSIGNED": 2, "TASK_STATUS_CHANGED": 2}

    agent_auth = login(client, original_agent.email)
    forbidden = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"assigned_agent_id": original_agent.id},
        headers={"X-CSRF-Token": agent_auth["csrf_token"]},
    )
    assert forbidden.status_code == 403


def test_analytics_keeps_duplicate_display_names_separate(
    client: TestClient, db: Session, login
) -> None:
    agents = db.scalars(select(User).where(User.role == "AGENT").order_by(User.id)).all()
    assert len(agents) == 2
    agents[1].full_name = agents[0].full_name
    db.commit()

    login(client, "manager@demo.local")
    response = client.get("/api/v1/manager/analytics")
    assert response.status_code == 200
    matching = [
        item
        for item in response.json()["workload_by_agent"]
        if item["agent"]["full_name"] == agents[0].full_name
    ]
    assert len(matching) == 2
    assert {item["agent"]["id"] for item in matching} == {agents[0].id, agents[1].id}
