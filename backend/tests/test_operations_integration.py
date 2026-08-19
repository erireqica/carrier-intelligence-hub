from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.carriers import Carrier, CarrierDomain, CarrierSender
from app.models.enums import TaskStatus
from app.models.operations import PolicyCase, ReviewItem, Task
from app.models.organization import Agency, User


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
    resolved = client.patch(
        f"/api/v1/reviews/{review.id}",
        json={
            "status": "RESOLVED",
            "resolution_notes": "Reviewed against the source email.",
        },
        headers=headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None
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
