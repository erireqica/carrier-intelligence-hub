from copy import deepcopy
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.carriers import Carrier
from app.models.enums import PolicyStatus, Priority, TaskStatus, UserRole
from app.models.operations import MessageAnalysis, PolicyCase, ReviewItem, Task
from app.models.organization import Agency, User


def test_profile_photo_is_normalized_agency_visible_and_removable(
    client: TestClient, db: Session, login
) -> None:
    agent = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert agent is not None
    auth = login(client, agent.email)
    headers = {"X-CSRF-Token": auth["csrf_token"], "Content-Type": "image/png"}
    source = BytesIO()
    Image.new("RGB", (900, 600), color=(31, 91, 180)).save(source, format="PNG")

    invalid = client.put(
        "/api/v1/auth/profile/avatar",
        content=b"not-an-image",
        headers=headers,
    )
    assert invalid.status_code == 422
    uploaded = client.put(
        "/api/v1/auth/profile/avatar",
        content=source.getvalue(),
        headers=headers,
    )

    assert uploaded.status_code == 200
    avatar_url = uploaded.json()["user"]["avatar_url"]
    assert avatar_url.startswith(f"/auth/users/{agent.id}/avatar?v=")
    image_response = client.get(f"/api/v1{avatar_url.split('?')[0]}")
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(image_response.content)) as normalized:
        assert normalized.size == (512, 512)
        assert normalized.format == "WEBP"

    login(client, "manager@demo.local")
    assert client.get(f"/api/v1{avatar_url.split('?')[0]}").status_code == 200
    other_agency = Agency(name="Other Agency", timezone="UTC")
    db.add(other_agency)
    db.flush()
    other_user = User(
        agency_id=other_agency.id,
        email="other.agent@demo.local",
        full_name="Other Agent",
        role=UserRole.AGENT,
        password_hash=agent.password_hash,
        avatar_image=b"private-avatar",
        avatar_content_type="image/webp",
        avatar_updated_at=agent.avatar_updated_at,
    )
    db.add(other_user)
    db.flush()
    assert client.get(f"/api/v1/auth/users/{other_user.id}/avatar").status_code == 404

    auth = login(client, agent.email)
    removed = client.delete(
        "/api/v1/auth/profile/avatar",
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert removed.status_code == 200
    assert removed.json()["user"]["avatar_url"] is None
    assert client.get(f"/api/v1{avatar_url.split('?')[0]}").status_code == 404
    assert {"PROFILE_PHOTO_UPDATED", "PROFILE_PHOTO_REMOVED"} <= set(
        db.scalars(select(AuditEvent.event_type)).all()
    )


def test_profile_update_duplicate_email_wrong_password_and_password_change(
    client: TestClient, db: Session, login
) -> None:
    auth = login(client, "agent.one@demo.local")
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    wrong = client.patch(
        "/api/v1/auth/profile",
        json={
            "full_name": "Elena Torres",
            "email": "elena.updated@demo.local",
            "current_password": "wrong-password",
        },
        headers=headers,
    )
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "Current password is incorrect."
    assert client.get("/api/v1/auth/me").status_code == 200
    too_short_profile_password = client.patch(
        "/api/v1/auth/profile",
        json={
            "full_name": "Elena Torres",
            "email": "elena.updated@demo.local",
            "current_password": "x",
        },
        headers=headers,
    )
    assert too_short_profile_password.status_code == 422
    assert too_short_profile_password.json()["detail"][0]["ctx"]["min_length"] == 8
    invalid_email = client.patch(
        "/api/v1/auth/profile",
        json={
            "full_name": "Elena Torres",
            "email": "not-an-email",
            "current_password": "demo-test-password",
        },
        headers=headers,
    )
    assert invalid_email.status_code == 422
    assert "Enter a valid internal email address" in invalid_email.json()["detail"][0]["msg"]
    duplicate = client.patch(
        "/api/v1/auth/profile",
        json={
            "full_name": "Elena Torres",
            "email": "agent.two@demo.local",
            "current_password": "demo-test-password",
        },
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "That login email is already in use."
    updated = client.patch(
        "/api/v1/auth/profile",
        json={
            "full_name": "Elena Updated",
            "email": "elena.updated@demo.local",
            "current_password": "demo-test-password",
        },
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["user"]["full_name"] == "Elena Updated"
    assert updated.json()["user"]["email"] == "elena.updated@demo.local"
    wrong_password_change = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "wrong-password",
            "new_password": "new-secure-demo-password",
            "confirm_new_password": "new-secure-demo-password",
        },
        headers=headers,
    )
    assert wrong_password_change.status_code == 400
    assert wrong_password_change.json()["detail"] == "Current password is incorrect."
    assert client.get("/api/v1/auth/me").status_code == 200
    short_new_password = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "demo-test-password",
            "new_password": "short",
            "confirm_new_password": "short",
        },
        headers=headers,
    )
    assert short_new_password.status_code == 422
    assert short_new_password.json()["detail"][0]["ctx"]["min_length"] == 12
    mismatched_passwords = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "demo-test-password",
            "new_password": "new-secure-demo-password",
            "confirm_new_password": "different-secure-password",
        },
        headers=headers,
    )
    assert mismatched_passwords.status_code == 422
    assert (
        "New password and confirmation do not match."
        in mismatched_passwords.json()["detail"][0]["msg"]
    )
    changed = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "demo-test-password",
            "new_password": "new-secure-demo-password",
            "confirm_new_password": "new-secure-demo-password",
        },
        headers=headers,
    )
    assert changed.status_code == 200
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "elena.updated@demo.local", "password": "new-secure-demo-password"},
        ).status_code
        == 200
    )
    event_types = set(
        db.scalars(
            select(AuditEvent.event_type).where(
                AuditEvent.event_type.in_(["PROFILE_UPDATED", "PASSWORD_CHANGED"])
            )
        ).all()
    )
    assert event_types == {"PROFILE_UPDATED", "PASSWORD_CHANGED"}


def test_tasks_default_to_actionable_and_status_is_assignee_scoped(
    client: TestClient, db: Session, login
) -> None:
    agent = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert agent is not None
    task = db.scalar(select(Task).where(Task.assigned_agent_id == agent.id))
    assert task is not None
    task.status = TaskStatus.COMPLETED
    db.commit()
    login(client, agent.email)
    todo = client.get("/api/v1/tasks?page_size=100").json()["items"]
    assert all(item["status"] in {"OPEN", "IN_PROGRESS"} for item in todo)
    completed = client.get("/api/v1/tasks?view=COMPLETED&page_size=100").json()["items"]
    assert task.id in {item["id"] for item in completed}
    manager = login(client, "manager@demo.local")
    denied = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"status": "DISMISSED"},
        headers={"X-CSRF-Token": manager["csrf_token"]},
    )
    assert denied.status_code == 403
    manager_user = db.scalar(select(User).where(User.email == "manager@demo.local"))
    assert manager_user is not None
    task.assigned_agent_id = manager_user.id
    db.commit()
    own_update = client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"status": "DISMISSED"},
        headers={"X-CSRF-Token": manager["csrf_token"]},
    )
    assert own_update.status_code == 403


def test_agent_case_correction_is_audited_and_preserves_ai_history(
    client: TestClient, db: Session, login
) -> None:
    case = db.scalar(select(PolicyCase).where(PolicyCase.client_name == "John Doe"))
    assert case is not None
    other = db.scalar(
        select(PolicyCase).where(
            PolicyCase.carrier_id == case.carrier_id,
            PolicyCase.id != case.id,
        )
    )
    if other is None:
        other = PolicyCase(
            agency_id=case.agency_id,
            carrier_id=case.carrier_id,
            assigned_agent_id=case.assigned_agent_id,
            client_name="Conflict Client",
            policy_number="CONFLICT-CASE-1",
            current_policy_status=PolicyStatus.PENDING,
            priority=Priority.NORMAL,
            summary="Synthetic conflict case.",
        )
        db.add(other)
        db.commit()
    analysis = db.scalar(
        select(MessageAnalysis).where(MessageAnalysis.carrier_message.has(case_id=case.id))
    )
    original_analysis = deepcopy(analysis.final_result_json) if analysis else None
    agent = login(client, "agent.one@demo.local")
    payload = {
        "client_name": case.client_name,
        "policy_number": case.policy_number,
        "policy_status": "ACTIVE",
        "priority": case.priority.value,
        "summary": "Confirmed active after agent review.",
        "premium_amount": str(case.premium_amount) if case.premium_amount else None,
        "currency": case.currency,
        "effective_date": case.effective_date.isoformat() if case.effective_date else None,
        "deadline": None,
        "reason": "Carrier confirmed the current policy state.",
    }
    corrected = client.patch(
        f"/api/v1/cases/{case.id}/correction",
        json=payload,
        headers={"X-CSRF-Token": agent["csrf_token"]},
    )
    assert corrected.status_code == 200
    assert corrected.json()["policy_status"] == "ACTIVE"
    if analysis:
        db.refresh(analysis)
        assert analysis.final_result_json == original_analysis
    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == "CASE_CORRECTED", AuditEvent.case_id == case.id
        )
    )
    assert event is not None
    assert "policy_status" in event.event_metadata["changed_fields"]
    assert "client_name" not in event.event_metadata

    conflict = client.patch(
        f"/api/v1/cases/{case.id}/correction",
        json={**payload, "policy_number": other.policy_number, "reason": "Test conflict."},
        headers={"X-CSRF-Token": agent["csrf_token"]},
    )
    assert conflict.status_code == 409
    manager = login(client, "manager@demo.local")
    assert (
        client.patch(
            f"/api/v1/cases/{case.id}/correction",
            json=payload,
            headers={"X-CSRF-Token": manager["csrf_token"]},
        ).status_code
        == 200
    )
    outside_agency = Agency(name="Outside Case Agency", timezone="UTC", is_active=True)
    db.add(outside_agency)
    db.flush()
    outside_carrier = Carrier(
        agency_id=outside_agency.id, name="Outside Case Carrier", is_enabled=True
    )
    db.add(outside_carrier)
    db.flush()
    outside_case = PolicyCase(
        agency_id=outside_agency.id,
        carrier_id=outside_carrier.id,
        client_name="Outside Client",
        policy_number="OUTSIDE-1",
        current_policy_status=PolicyStatus.PENDING,
        priority=Priority.NORMAL,
        summary="Outside agency case.",
    )
    db.add(outside_case)
    db.commit()
    assert (
        client.patch(
            f"/api/v1/cases/{outside_case.id}/correction",
            json=payload,
            headers={"X-CSRF-Token": manager["csrf_token"]},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/cases/{outside_case.id}/dismiss",
            headers={"X-CSRF-Token": manager["csrf_token"]},
        ).status_code
        == 404
    )
    other_agent = login(client, "agent.two@demo.local")
    assert (
        client.patch(
            f"/api/v1/cases/{case.id}/correction",
            json=payload,
            headers={"X-CSRF-Token": other_agent["csrf_token"]},
        ).status_code
        == 404
    )


def test_agent_activity_is_self_scoped_and_manager_review_mutations_are_forbidden(
    client: TestClient, db: Session, login
) -> None:
    agent = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    review = db.scalar(select(ReviewItem).where(ReviewItem.status == "OPEN"))
    assert agent is not None and review is not None
    manager = login(client, "manager@demo.local")
    headers = {"X-CSRF-Token": manager["csrf_token"]}
    dismissed = client.post(
        f"/api/v1/reviews/{review.id}/dismiss-analysis",
        json={"resolution_notes": "Manager bypass attempt"},
        headers=headers,
    )
    assert dismissed.status_code == 403
    proposal = {
        "classification": "PENDING_REQUIREMENTS",
        "summary": "Synthetic valid proposal.",
        "priority": "HIGH",
        "client_name": "John Doe",
        "policy_number": "AMR-98765432",
        "policy_status": "PENDING",
        "premium_amount": None,
        "currency": None,
        "effective_date": None,
        "deadline": {
            "raw_text": None,
            "explicit_date": None,
            "relative_count": None,
            "relative_unit": None,
        },
        "requirements": [],
        "action_items": [],
    }
    applied = client.post(
        f"/api/v1/reviews/{review.id}/apply-analysis", json=proposal, headers=headers
    )
    assert applied.status_code == 403
    assert client.get("/api/v1/manager/activity").status_code == 404
    assert client.get("/api/v1/activity").status_code == 403
    login(client, agent.email)
    activity = client.get("/api/v1/activity?actor_user_id=999999")
    assert activity.status_code == 200
    assert all(item["actor_user_id"] == agent.id for item in activity.json()["items"])
