from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.audit import AuditEvent
from app.models.carriers import Carrier, CarrierDomain, CarrierSender
from app.models.enums import (
    CaseAssignmentSource,
    GmailConnectionStatus,
    ProcessingStatus,
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
    task_assignment_forbidden = client.patch(
        f"/api/v1/tasks/{mary_task.id}",
        json={"assigned_agent_id": manager_auth["user"]["id"]},
        headers={"X-CSRF-Token": manager_auth["csrf_token"]},
    )
    assert task_assignment_forbidden.status_code == 422


def test_business_deadlines_serialize_as_agency_local_dates(
    client: TestClient, db: Session, login
) -> None:
    agency = db.scalar(select(Agency))
    case = db.scalar(select(PolicyCase).where(PolicyCase.client_name == "John Doe"))
    task = db.scalar(select(Task).where(Task.case_id == case.id)) if case else None
    assert agency is not None and case is not None and task is not None
    agency.timezone = "America/Chicago"
    case.current_deadline = datetime(2026, 8, 28, 22, tzinfo=UTC)
    task.due_at = datetime(2026, 8, 28, 22, tzinfo=UTC)
    db.commit()

    login(client, "manager@demo.local")
    case_list = client.get("/api/v1/cases?page_size=100")
    case_detail = client.get(f"/api/v1/cases/{case.id}")
    task_list = client.get("/api/v1/tasks?page_size=100")

    assert case_list.status_code == case_detail.status_code == task_list.status_code == 200
    listed_case = next(item for item in case_list.json()["items"] if item["id"] == case.id)
    listed_task = next(item for item in task_list.json()["items"] if item["id"] == task.id)
    assert listed_case["deadline"] == "2026-08-28"
    assert case_detail.json()["deadline"] == "2026-08-28"
    assert (
        next(item for item in case_detail.json()["tasks"] if item["id"] == task.id)["due_at"]
        == "2026-08-28"
    )
    assert listed_task["due_at"] == "2026-08-28"
    assert "T" in listed_case["updated_at"]


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
    public_domain = client.post(
        f"/api/v1/manager/carriers/{carrier_id}/domains",
        json={"domain": "gmail.com", "is_enabled": True},
        headers=headers,
    )
    assert public_domain.status_code == 422
    assert "specific sender address" in public_domain.text
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
    public_sender = client.post(
        f"/api/v1/manager/carriers/{carrier_id}/senders",
        json={"email": "specific.sender@gmail.com", "is_enabled": True},
        headers=headers,
    )
    assert public_sender.status_code == 200
    public_sender_id = next(
        item["id"]
        for item in public_sender.json()["senders"]
        if item["email"] == "specific.sender@gmail.com"
    )
    assert (
        client.post(
            f"/api/v1/manager/carriers/{carrier_id}/senders",
            json={"email": "notices@example.com", "is_enabled": True},
            headers=headers,
        ).status_code
        == 409
    )
    client.delete(f"/api/v1/manager/carriers/{carrier_id}/senders/{sender_id}", headers=headers)
    assert (
        client.delete(
            f"/api/v1/manager/carriers/{carrier_id}/senders/{public_sender_id}", headers=headers
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
    manager_denied = client.patch(
        f"/api/v1/reviews/{review.id}",
        json={
            "status": "IN_REVIEW",
            "resolution_notes": "Reviewed against the source email.",
        },
        headers=headers,
    )
    assert manager_denied.status_code == 403
    assigned = review.assigned_reviewer
    assert assigned is not None
    agent_auth = login(client, assigned.email)
    in_review = client.patch(
        f"/api/v1/reviews/{review.id}",
        json={"status": "IN_REVIEW", "resolution_notes": "Reviewed against the source email."},
        headers={"X-CSRF-Token": agent_auth["csrf_token"]},
    )
    assert in_review.status_code == 200
    assert in_review.json()["status"] == "IN_REVIEW"
    assert in_review.json()["resolved_at"] is None
    for terminal in ("RESOLVED", "DISMISSED"):
        rejected = client.patch(
            f"/api/v1/reviews/{review.id}",
            json={"status": terminal, "resolution_notes": "Bypass attempt."},
            headers={"X-CSRF-Token": agent_auth["csrf_token"]},
        )
        assert rejected.status_code == 422
    db.refresh(review)
    assert review.status.value == "IN_REVIEW"
    login(client, "manager@demo.local")
    logs = client.get("/api/v1/manager/audit-events?page_size=100")
    assert logs.status_code == 200
    event_types = {item["event_type"] for item in logs.json()["items"]}
    assert {"CARRIER_CREATED", "WHITELIST_UPDATED", "CASE_REVIEWED"} <= event_types
    assert all(item["event_label"] and item["category"] for item in logs.json()["items"])
    carrier_logs = client.get(
        f"/api/v1/manager/audit-events?page_size=2&category=CARRIER_CONFIG&actor={auth['user']['id']}"
    )
    assert carrier_logs.status_code == 200
    assert carrier_logs.json()["page"]["page_size"] == 2
    assert carrier_logs.json()["page"]["total"] >= 2
    assert all(item["category"] == "Carrier config" for item in carrier_logs.json()["items"])
    assert all(
        item["actor_name"] == auth["user"]["full_name"] for item in carrier_logs.json()["items"]
    )
    system_logs = client.get("/api/v1/manager/audit-events?page_size=5&actor=system")
    assert system_logs.status_code == 200
    assert all(item["actor_user_id"] is None for item in system_logs.json()["items"])


def test_case_evidence_returns_trustworthy_attachment_provenance(
    client: TestClient, db: Session, login
) -> None:
    case = db.scalar(select(PolicyCase).where(PolicyCase.client_name == "John Doe"))
    assert case is not None
    attachment = db.scalar(
        select(Attachment)
        .join(CarrierMessage, Attachment.carrier_message_id == CarrierMessage.id)
        .where(CarrierMessage.case_id == case.id)
    )
    evidence = db.scalar(select(CaseEvidence).where(CaseEvidence.case_id == case.id))
    assert attachment is not None and evidence is not None
    evidence.attachment_id = attachment.id
    evidence.source_type = "PDF"
    db.commit()

    login(client, "agent.one@demo.local")
    response = client.get(f"/api/v1/cases/{case.id}")

    assert response.status_code == 200
    stored = next(item for item in response.json()["evidence"] if item["id"] == evidence.id)
    assert stored["source_type"] == "PDF"
    assert stored["attachment_filename"] == attachment.filename
    assert "page" not in stored


def test_agents_connected_inbox_count_excludes_disconnected_history(
    client: TestClient, db: Session, login
) -> None:
    agent = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert agent is not None
    db.add_all(
        [
            GmailConnection(
                agency_id=agent.agency_id,
                user_id=agent.id,
                gmail_address="active-count@gmail.test",
                status=GmailConnectionStatus.CONNECTED,
            ),
            GmailConnection(
                agency_id=agent.agency_id,
                user_id=agent.id,
                gmail_address="historical-count@gmail.test",
                status=GmailConnectionStatus.DISCONNECTED,
            ),
        ]
    )
    db.commit()
    login(client, "manager@demo.local")

    response = client.get("/api/v1/manager/agents")

    listed = next(item for item in response.json() if item["id"] == agent.id)
    assert listed["gmail_connections"] == 1


def test_review_history_defaults_to_actionable_and_terminal_detail_is_scoped(
    client: TestClient, db: Session, login
) -> None:
    review = db.scalar(select(ReviewItem).where(ReviewItem.status == "OPEN"))
    assert review is not None and review.assigned_reviewer is not None
    owner_email = review.assigned_reviewer.email
    login(client, owner_email)
    actionable = client.get("/api/v1/reviews?page_size=100")
    assert review.id in {item["id"] for item in actionable.json()["items"]}

    review.status = ReviewStatus.RESOLVED
    review.resolved_at = utc_now()
    db.commit()
    assert review.id not in {
        item["id"] for item in client.get("/api/v1/reviews?page_size=100").json()["items"]
    }
    history = client.get("/api/v1/reviews?view=RESOLVED&page_size=100")
    assert review.id in {item["id"] for item in history.json()["items"]}
    assert client.get(f"/api/v1/reviews/{review.id}/analysis").status_code == 200

    login(client, "agent.two@demo.local")
    assert client.get(f"/api/v1/reviews/{review.id}/analysis").status_code == 404
    login(client, "manager@demo.local")
    assert client.get(f"/api/v1/reviews/{review.id}/analysis").status_code == 200


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
    task = db.scalar(select(Task).where(Task.status == TaskStatus.OPEN))
    original_agent = (
        db.scalar(select(User).where(User.id == task.assigned_agent_id)) if task else None
    )
    assert task is not None and original_agent is not None
    manager = login(client, "manager@demo.local")
    manager_headers = {"X-CSRF-Token": manager["csrf_token"]}

    assert (
        client.patch(f"/api/v1/tasks/{task.id}", json={}, headers=manager_headers).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/tasks/{task.id}",
            json={"status": None},
            headers=manager_headers,
        ).status_code
        == 422
    )
    manager_status = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"status": "COMPLETED"},
        headers=manager_headers,
    )
    assert manager_status.status_code == 403
    reassigned = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"assigned_agent_id": original_agent.id},
        headers=manager_headers,
    )
    assert reassigned.status_code == 422

    agent_auth = login(client, original_agent.email)
    agent_headers = {"X-CSRF-Token": agent_auth["csrf_token"]}
    agent_reassign = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"assigned_agent_id": original_agent.id},
        headers=agent_headers,
    )
    assert agent_reassign.status_code == 422
    completed = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"status": "COMPLETED"},
        headers=agent_headers,
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


def test_manager_assigns_case_and_active_work_to_an_active_agent(
    client: TestClient, db: Session, login
) -> None:
    case = db.scalar(select(PolicyCase).where(PolicyCase.client_name == "Mary Smith"))
    target = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    original = db.get(User, case.assigned_agent_id) if case else None
    message = (
        db.scalar(select(CarrierMessage).where(CarrierMessage.case_id == case.id)) if case else None
    )
    assert case is not None and target is not None and original is not None and message is not None
    active_review = ReviewItem(
        agency_id=case.agency_id,
        case_id=case.id,
        carrier_message_id=message.id,
        assigned_reviewer_id=original.id,
        status=ReviewStatus.IN_REVIEW,
        reason_code="ASSIGNMENT_TEST",
        reason="Synthetic active review",
    )
    terminal_task = Task(
        agency_id=case.agency_id,
        case_id=case.id,
        assigned_agent_id=original.id,
        title="Historical completed task",
        priority=case.priority,
        status=TaskStatus.COMPLETED,
        completed_at=utc_now(),
    )
    terminal_review = ReviewItem(
        agency_id=case.agency_id,
        case_id=case.id,
        carrier_message_id=message.id,
        assigned_reviewer_id=original.id,
        status=ReviewStatus.RESOLVED,
        reason_code="HISTORICAL_TEST",
        reason="Synthetic resolved review",
        resolved_at=utc_now(),
    )
    db.add_all([active_review, terminal_task, terminal_review])
    db.commit()

    manager = login(client, "manager@demo.local")
    headers = {"X-CSRF-Token": manager["csrf_token"]}
    assert (
        client.patch(
            f"/api/v1/cases/{case.id}/assignment",
            json={"assigned_agent_id": manager["user"]["id"]},
            headers=headers,
        ).status_code
        == 422
    )

    target.is_active = False
    db.commit()
    assert (
        client.patch(
            f"/api/v1/cases/{case.id}/assignment",
            json={"assigned_agent_id": target.id},
            headers=headers,
        ).status_code
        == 422
    )
    target.is_active = True
    other_agency = Agency(name="Other Agency", timezone="UTC", is_active=True)
    db.add(other_agency)
    db.flush()
    outsider = User(
        agency_id=other_agency.id,
        email="outside.agent@example.test",
        full_name="Outside Agent",
        role=UserRole.AGENT,
        password_hash="synthetic-not-a-password",
        is_active=True,
    )
    db.add(outsider)
    db.commit()
    assert (
        client.patch(
            f"/api/v1/cases/{case.id}/assignment",
            json={"assigned_agent_id": outsider.id},
            headers=headers,
        ).status_code
        == 422
    )

    response = client.patch(
        f"/api/v1/cases/{case.id}/assignment",
        json={"assigned_agent_id": target.id},
        headers=headers,
    )
    assert response.status_code == 200
    db.refresh(case)
    db.refresh(active_review)
    db.refresh(terminal_task)
    db.refresh(terminal_review)
    assert case.assigned_agent_id == target.id
    assert case.assignment_source is CaseAssignmentSource.MANAGER
    assert all(
        task.assigned_agent_id == target.id
        for task in db.scalars(
            select(Task).where(
                Task.case_id == case.id,
                Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
            )
        )
    )
    assert active_review.assigned_reviewer_id == target.id
    assert terminal_task.assigned_agent_id == original.id
    assert terminal_review.assigned_reviewer_id == original.id
    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "CASE_REASSIGNED",
        )
    )
    assert event is not None
    assert event.event_metadata["new_assignee_id"] == target.id

    reassigned_back = client.patch(
        f"/api/v1/cases/{case.id}/assignment",
        json={"assigned_agent_id": original.id},
        headers=headers,
    )
    assert reassigned_back.status_code == 200
    db.refresh(case)
    db.refresh(active_review)
    db.refresh(terminal_task)
    db.refresh(terminal_review)
    assert case.assigned_agent_id == original.id
    assert active_review.assigned_reviewer_id == original.id
    assert terminal_task.assigned_agent_id == original.id
    assert terminal_review.assigned_reviewer_id == original.id

    agent_auth = login(client, "agent.one@demo.local")
    forbidden = client.patch(
        f"/api/v1/cases/{case.id}/assignment",
        json={"assigned_agent_id": target.id},
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
