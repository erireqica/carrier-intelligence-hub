from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError
from httplib2 import Response
from oauthlib.oauth2 import InvalidClientError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes import gmail as gmail_routes
from app.core.security import token_hash
from app.core.time import utc_now
from app.integrations.gmail import oauth as oauth_module
from app.integrations.gmail.crypto import TokenCipher
from app.integrations.gmail.errors import (
    GmailProfileRequestError,
    GmailProfileValidationError,
    GmailTokenExchangeError,
)
from app.integrations.gmail.oauth import (
    GMAIL_MODIFY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GoogleOAuthClient,
    OAuthTokenSet,
)
from app.models.carriers import Carrier
from app.models.enums import (
    CaseAssignmentSource,
    GmailConnectionStatus,
    PolicyStatus,
    Priority,
    ProcessingStatus,
    ReviewStatus,
    TaskStatus,
)
from app.models.operations import CarrierMessage, PolicyCase, ReviewItem, Task
from app.models.organization import (
    GmailConnection,
    GmailOAuthCredential,
    GmailOAuthState,
    User,
)


class FakeOAuthClient:
    def __init__(self, *, gmail_address: str = "authorized@gmail.test") -> None:
        self.states: list[str] = []
        self.tokens = OAuthTokenSet(
            access_token="synthetic-access-token",
            refresh_token="synthetic-refresh-token",
            expires_at=utc_now() + timedelta(hours=1),
            granted_scopes=[GMAIL_MODIFY_SCOPE],
            gmail_address=gmail_address,
        )
        self.revoked: list[str] = []

    def authorization_url(self, state: str) -> str:
        self.states.append(state)
        return f"https://accounts.google.test/consent?state={state}"

    def exchange_code(self, code: str) -> OAuthTokenSet:
        assert code == "synthetic-code"
        return self.tokens

    def revoke_token(self, token: str) -> None:
        self.revoked.append(token)


def patch_oauth(monkeypatch, fake: FakeOAuthClient) -> None:
    monkeypatch.setattr(gmail_routes, "GoogleOAuthClient", lambda: fake)


def test_google_authorization_url_uses_web_offline_modify_flow(configured_google) -> None:
    raw_state = "synthetic-strong-oauth-state"
    authorization_url = GoogleOAuthClient().authorization_url(raw_state)
    query = parse_qs(urlparse(authorization_url).query)
    assert query["response_type"] == ["code"]
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["state"] == [raw_state]
    assert query["scope"] == [GMAIL_MODIFY_SCOPE]
    assert set(query["prompt"][0].split()) == {"consent", "select_account"}
    assert "code_challenge" not in query
    assert "code_challenge_method" not in query


def test_exchange_rejects_missing_actual_scope_even_when_it_was_requested(monkeypatch) -> None:
    class Credentials:
        token = "synthetic-access"
        refresh_token = "synthetic-refresh"
        expiry = None
        scopes = [GMAIL_READONLY_SCOPE]
        granted_scopes = []

    class Flow:
        credentials = Credentials()

        def fetch_token(self, *, code: str) -> None:
            assert code == "synthetic-code"

    class ProfileRequest:
        @staticmethod
        def execute() -> dict[str, str]:
            return {"emailAddress": "provider-profile@gmail.com"}

    class Profile:
        @staticmethod
        def getProfile(*, userId: str) -> ProfileRequest:
            assert userId == "me"
            return ProfileRequest()

    class Service:
        @staticmethod
        def users() -> Profile:
            return Profile()

    client = object.__new__(GoogleOAuthClient)
    monkeypatch.setattr(GoogleOAuthClient, "_flow", lambda self: Flow())
    monkeypatch.setattr(oauth_module, "build", lambda *args, **kwargs: Service())
    with pytest.raises(PermissionError, match="workflow-label scope"):
        client.exchange_code("synthetic-code")


def test_exchange_accepts_incremental_authorization_scope_superset(monkeypatch) -> None:
    class Credentials:
        token = "synthetic-access"
        refresh_token = "synthetic-new-refresh"
        expiry = None
        scopes = [GMAIL_MODIFY_SCOPE]
        granted_scopes = [GMAIL_READONLY_SCOPE, GMAIL_MODIFY_SCOPE]

    class Session:
        token = {}

    class Flow:
        credentials = Credentials()
        oauth2session = Session()

        @staticmethod
        def fetch_token(*, code: str) -> None:
            assert code == "synthetic-code"
            scope_warning = Warning("synthetic scope-set expansion")
            scope_warning.token = {
                "access_token": "synthetic-access",
                "refresh_token": "synthetic-new-refresh",
                "scope": [GMAIL_READONLY_SCOPE, GMAIL_MODIFY_SCOPE],
            }
            scope_warning.old_scope = [GMAIL_MODIFY_SCOPE]
            scope_warning.new_scope = [GMAIL_READONLY_SCOPE, GMAIL_MODIFY_SCOPE]
            raise scope_warning

    class ProfileRequest:
        @staticmethod
        def execute() -> dict[str, str]:
            return {"emailAddress": "incremental@gmail.com"}

    class Profile:
        @staticmethod
        def getProfile(*, userId: str) -> ProfileRequest:
            assert userId == "me"
            return ProfileRequest()

    class Service:
        @staticmethod
        def users() -> Profile:
            return Profile()

    flow = Flow()
    client = object.__new__(GoogleOAuthClient)
    monkeypatch.setattr(GoogleOAuthClient, "_flow", lambda self: flow)
    monkeypatch.setattr(oauth_module, "build", lambda *args, **kwargs: Service())

    tokens = client.exchange_code("synthetic-code")

    assert tokens.granted_scopes == [GMAIL_MODIFY_SCOPE, GMAIL_READONLY_SCOPE]
    assert flow.oauth2session.token["access_token"] == "synthetic-access"
    assert tokens.refresh_token == "synthetic-new-refresh"


def test_incremental_scope_change_still_rejects_missing_modify(monkeypatch) -> None:
    class Flow:
        oauth2session = type("Session", (), {"token": {}})()

        @staticmethod
        def fetch_token(*, code: str) -> None:
            assert code == "synthetic-code"
            scope_warning = Warning("synthetic scope mismatch")
            scope_warning.token = {
                "access_token": "synthetic-access",
                "scope": [GMAIL_READONLY_SCOPE],
            }
            scope_warning.old_scope = [GMAIL_MODIFY_SCOPE]
            scope_warning.new_scope = [GMAIL_READONLY_SCOPE]
            raise scope_warning

    client = object.__new__(GoogleOAuthClient)
    monkeypatch.setattr(GoogleOAuthClient, "_flow", lambda self: Flow())

    with pytest.raises(PermissionError, match="workflow-label scope"):
        client.exchange_code("synthetic-code")


def test_exchange_classifies_token_failure_without_exposing_provider_detail(monkeypatch) -> None:
    class Flow:
        @staticmethod
        def fetch_token(*, code: str) -> None:
            assert code == "synthetic-code"
            raise InvalidClientError(description="synthetic-sensitive-provider-detail")

    client = object.__new__(GoogleOAuthClient)
    monkeypatch.setattr(GoogleOAuthClient, "_flow", lambda self: Flow())
    with pytest.raises(GmailTokenExchangeError) as captured:
        client.exchange_code("synthetic-code")
    assert captured.value.reason == "invalid_client"
    assert "synthetic-sensitive" not in str(captured.value)


def test_exchange_classifies_profile_http_failure_without_exposing_provider_detail(
    monkeypatch,
) -> None:
    class Credentials:
        token = "synthetic-access"
        refresh_token = "synthetic-refresh"
        expiry = None
        scopes = [GMAIL_MODIFY_SCOPE]
        granted_scopes = [GMAIL_MODIFY_SCOPE]

    class Flow:
        credentials = Credentials()

        @staticmethod
        def fetch_token(*, code: str) -> None:
            assert code == "synthetic-code"

    class ProfileRequest:
        @staticmethod
        def execute() -> dict[str, str]:
            raise HttpError(
                Response({"status": "403"}),
                b'{"error":{"status":"PERMISSION_DENIED",'
                b'"errors":[{"reason":"accessNotConfigured"}],'
                b'"message":"synthetic-sensitive-profile-detail"}}',
                uri="https://synthetic.invalid/profile",
            )

    class Profile:
        @staticmethod
        def getProfile(*, userId: str) -> ProfileRequest:
            assert userId == "me"
            return ProfileRequest()

    class Service:
        @staticmethod
        def users() -> Profile:
            return Profile()

    client = object.__new__(GoogleOAuthClient)
    captured_credentials = []
    monkeypatch.setattr(GoogleOAuthClient, "_flow", lambda self: Flow())
    monkeypatch.setattr(
        oauth_module,
        "build",
        lambda *args, **kwargs: captured_credentials.append(kwargs["credentials"]) or Service(),
    )
    with pytest.raises(GmailProfileRequestError) as captured:
        client.exchange_code("synthetic-code")
    assert captured_credentials == [Flow.credentials]
    assert captured.value.status_code == 403
    assert captured.value.reason == "SERVICE_DISABLED"
    assert captured.value.during_execute is True
    assert "synthetic-sensitive" not in str(captured.value)


@pytest.mark.parametrize(
    ("profile", "mapping", "present", "nonempty", "valid"),
    [
        ([], False, False, False, False),
        ({}, True, False, False, False),
        ({"emailAddress": ""}, True, True, False, False),
        ({"emailAddress": "not-an-email"}, True, True, True, False),
    ],
)
def test_exchange_reports_only_profile_validation_booleans(
    monkeypatch, profile, mapping, present, nonempty, valid
) -> None:
    class Credentials:
        token = "synthetic-access"
        refresh_token = "synthetic-refresh"
        expiry = None
        scopes = [GMAIL_MODIFY_SCOPE]
        granted_scopes = [GMAIL_MODIFY_SCOPE]

    class Flow:
        credentials = Credentials()

        @staticmethod
        def fetch_token(*, code: str) -> None:
            assert code == "synthetic-code"

    class ProfileRequest:
        @staticmethod
        def execute():
            return profile

    class Profile:
        @staticmethod
        def getProfile(*, userId: str) -> ProfileRequest:
            assert userId == "me"
            return ProfileRequest()

    class Service:
        @staticmethod
        def users() -> Profile:
            return Profile()

    client = object.__new__(GoogleOAuthClient)
    monkeypatch.setattr(GoogleOAuthClient, "_flow", lambda self: Flow())
    monkeypatch.setattr(oauth_module, "build", lambda *args, **kwargs: Service())
    with pytest.raises(GmailProfileValidationError) as captured:
        client.exchange_code("synthetic-code")
    assert captured.value.response_is_mapping is mapping
    assert captured.value.email_present is present
    assert captured.value.email_is_nonempty_string is nonempty
    assert captured.value.normalized_email_valid is valid


def start_oauth(client: TestClient, auth: dict, fake: FakeOAuthClient, reconnect_id=None) -> str:
    response = client.post(
        "/api/v1/gmail/oauth/start",
        json={"reconnect_connection_id": reconnect_id},
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert response.status_code == 200
    raw_state = parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]
    assert raw_state == fake.states[-1]
    return raw_state


def test_oauth_start_requires_authentication_and_csrf(
    client: TestClient, login, configured_google, monkeypatch
) -> None:
    fake = FakeOAuthClient()
    patch_oauth(monkeypatch, fake)
    assert client.post("/api/v1/gmail/oauth/start", json={}).status_code == 401
    login(client, "agent.one@demo.local")
    assert client.post("/api/v1/gmail/oauth/start", json={}).status_code == 403
    manager = login(client, "manager@demo.local")
    forbidden = client.post(
        "/api/v1/gmail/oauth/start",
        json={},
        headers={"X-CSRF-Token": manager["csrf_token"]},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Agent access required"


def test_oauth_state_is_strong_unique_hashed_and_session_bound(
    client: TestClient, db: Session, login, configured_google, monkeypatch
) -> None:
    fake = FakeOAuthClient()
    patch_oauth(monkeypatch, fake)
    auth = login(client, "agent.one@demo.local")
    first = start_oauth(client, auth, fake)
    second = start_oauth(client, auth, fake)
    assert first != second
    assert len(first) >= 64
    states = db.scalars(select(GmailOAuthState).order_by(GmailOAuthState.id)).all()
    assert {item.state_hash for item in states[-2:]} == {token_hash(first), token_hash(second)}
    assert all(first != item.state_hash and second != item.state_hash for item in states)

    login(client, "agent.two@demo.local")
    wrong_session = client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": first, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert wrong_session.status_code == 303
    assert wrong_session.headers["location"].endswith("oauth=invalid_state")


def test_expired_unknown_and_consumed_oauth_states_are_rejected(
    client: TestClient, db: Session, login, configured_google, monkeypatch
) -> None:
    fake = FakeOAuthClient()
    patch_oauth(monkeypatch, fake)
    auth = login(client, "agent.one@demo.local")
    expired_raw = start_oauth(client, auth, fake)
    expired = db.scalar(
        select(GmailOAuthState).where(GmailOAuthState.state_hash == token_hash(expired_raw))
    )
    assert expired is not None
    expired.expires_at = utc_now() - timedelta(seconds=1)
    db.commit()
    expired_response = client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": expired_raw, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert expired_response.headers["location"].endswith("oauth=invalid_state")
    unknown = client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": "unknown-state", "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert unknown.headers["location"].endswith("oauth=invalid_state")

    denied_raw = start_oauth(client, auth, fake)
    denied = client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": denied_raw, "error": "access_denied"},
        follow_redirects=False,
    )
    assert denied.headers["location"].endswith("oauth=denied")
    reused = client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": denied_raw, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert reused.headers["location"].endswith("oauth=invalid_state")


def test_successful_callback_uses_provider_identity_and_encrypts_tokens(
    client: TestClient, db: Session, login, configured_google, monkeypatch
) -> None:
    fake = FakeOAuthClient(gmail_address="Real.Profile@Gmail.com")
    patch_oauth(monkeypatch, fake)
    auth = login(client, "agent.one@demo.local")
    raw_state = start_oauth(client, auth, fake)
    callback = client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": raw_state, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"].endswith("oauth=success")
    connection = db.scalar(
        select(GmailConnection).where(GmailConnection.gmail_address == "real.profile@gmail.com")
    )
    assert connection is not None
    assert connection.status is GmailConnectionStatus.CONNECTED
    credential = db.scalar(
        select(GmailOAuthCredential).where(
            GmailOAuthCredential.gmail_connection_id == connection.id
        )
    )
    assert credential is not None
    assert "synthetic-access-token" not in (credential.encrypted_access_token or "")
    assert "synthetic-refresh-token" not in credential.encrypted_refresh_token
    cipher = TokenCipher.from_settings()
    assert cipher.decrypt(credential.encrypted_access_token or "") == "synthetic-access-token"
    assert cipher.decrypt(credential.encrypted_refresh_token) == "synthetic-refresh-token"
    assert db.scalar(select(func.count()).where(GmailOAuthState.state_hash == raw_state)) == 0
    capability = client.get("/api/v1/gmail-connections")
    assert capability.status_code == 200
    assert capability.json()["connections"][0]["can_apply_workflow_labels"] is True
    credential.granted_scopes = [GMAIL_READONLY_SCOPE]
    db.commit()
    legacy = client.get("/api/v1/gmail-connections")
    assert legacy.status_code == 200
    assert legacy.json()["connections"][0]["status"] == "CONNECTED"
    assert legacy.json()["connections"][0]["can_apply_workflow_labels"] is False


def test_missing_scope_is_rejected_without_persisting_credentials(
    client: TestClient, db: Session, login, configured_google, monkeypatch
) -> None:
    fake = FakeOAuthClient()
    fake.tokens = OAuthTokenSet(
        access_token="access",
        refresh_token="refresh",
        expires_at=utc_now() + timedelta(hours=1),
        granted_scopes=[],
        gmail_address="missing.scope@gmail.test",
    )
    patch_oauth(monkeypatch, fake)
    auth = login(client, "agent.one@demo.local")
    raw_state = start_oauth(client, auth, fake)
    callback = client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": raw_state, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert callback.headers["location"].endswith("oauth=scope_missing")
    assert db.scalar(select(func.count()).select_from(GmailOAuthCredential)) == 0


def test_reconnect_preserves_refresh_token_and_disconnected_mailbox_is_transferred(
    client: TestClient, db: Session, login, configured_google, monkeypatch
) -> None:
    fake = FakeOAuthClient(gmail_address="reconnect@gmail.test")
    patch_oauth(monkeypatch, fake)
    auth = login(client, "agent.one@demo.local")
    raw_state = start_oauth(client, auth, fake)
    client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": raw_state, "code": "synthetic-code"},
        follow_redirects=False,
    )
    connection = db.scalar(
        select(GmailConnection).where(GmailConnection.gmail_address == "reconnect@gmail.test")
    )
    assert connection is not None
    fake.tokens = OAuthTokenSet(
        access_token="replacement-access-token",
        refresh_token=None,
        expires_at=utc_now() + timedelta(hours=2),
        granted_scopes=[GMAIL_MODIFY_SCOPE],
        gmail_address="reconnect@gmail.test",
    )
    reconnect_state = start_oauth(client, auth, fake, connection.id)
    reconnect = client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": reconnect_state, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert reconnect.headers["location"].endswith("oauth=success")
    credential = db.scalar(
        select(GmailOAuthCredential).where(
            GmailOAuthCredential.gmail_connection_id == connection.id
        )
    )
    assert credential is not None
    assert TokenCipher.from_settings().decrypt(credential.encrypted_refresh_token) == (
        "synthetic-refresh-token"
    )

    other_owner = db.scalar(select(User).where(User.email == "agent.two@demo.local"))
    assert other_owner is not None
    historical_connection = GmailConnection(
        agency_id=other_owner.agency_id,
        user_id=other_owner.id,
        gmail_address="owned@gmail.test",
        status=GmailConnectionStatus.DISCONNECTED,
    )
    db.add(historical_connection)
    db.flush()
    db.add(
        GmailOAuthCredential(
            gmail_connection_id=historical_connection.id,
            encrypted_refresh_token=TokenCipher.from_settings().encrypt(
                "former-owner-refresh-token"
            ),
            granted_scopes=[GMAIL_MODIFY_SCOPE],
        )
    )
    db.commit()
    carrier = db.scalar(select(Carrier).where(Carrier.name == "Americo"))
    manager = db.scalar(select(User).where(User.email == "manager@demo.local"))
    assert historical_connection is not None and carrier is not None and manager is not None
    case = PolicyCase(
        agency_id=other_owner.agency_id,
        carrier_id=carrier.id,
        assigned_agent_id=manager.id,
        assignment_source=CaseAssignmentSource.MANAGER,
        client_name="Mailbox Handoff",
        policy_number="HANDOFF-001",
        current_policy_status=PolicyStatus.ISSUED,
        priority=Priority.NORMAL,
        summary="Synthetic handoff case.",
    )
    message = CarrierMessage(
        agency_id=other_owner.agency_id,
        carrier_id=carrier.id,
        gmail_connection_id=historical_connection.id,
        gmail_message_id="historical-owned-message",
        sender="alerts@americo.com",
        subject="Historical mailbox message",
        received_at=utc_now(),
        processing_status=ProcessingStatus.RECEIVED,
        raw_content="Historical synthetic content.",
        cleaned_content="Historical synthetic content.",
        case=case,
    )
    db.add_all([case, message])
    db.flush()
    open_task = Task(
        agency_id=other_owner.agency_id,
        case_id=case.id,
        source_carrier_message_id=message.id,
        source_action_index=0,
        assigned_agent_id=manager.id,
        title="Active mailbox work",
        priority=Priority.NORMAL,
        status=TaskStatus.OPEN,
    )
    completed_task = Task(
        agency_id=other_owner.agency_id,
        case_id=case.id,
        assigned_agent_id=manager.id,
        title="Historical mailbox work",
        priority=Priority.NORMAL,
        status=TaskStatus.COMPLETED,
        completed_at=utc_now(),
    )
    open_review = ReviewItem(
        agency_id=other_owner.agency_id,
        case_id=case.id,
        carrier_message_id=message.id,
        assigned_reviewer_id=manager.id,
        status=ReviewStatus.OPEN,
        reason_code="HANDOFF_TEST",
        reason="Synthetic active review.",
    )
    resolved_review = ReviewItem(
        agency_id=other_owner.agency_id,
        case_id=case.id,
        carrier_message_id=message.id,
        assigned_reviewer_id=manager.id,
        status=ReviewStatus.RESOLVED,
        reason_code="HANDOFF_HISTORY_TEST",
        reason="Synthetic historical review.",
        resolved_at=utc_now(),
    )
    db.add_all([open_task, completed_task, open_review, resolved_review])
    db.commit()
    fake.tokens = OAuthTokenSet(
        access_token="access",
        refresh_token="refresh",
        expires_at=utc_now() + timedelta(hours=1),
        granted_scopes=[GMAIL_MODIFY_SCOPE],
        gmail_address="owned@gmail.test",
    )
    reuse_state = start_oauth(client, auth, fake)
    reuse = client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": reuse_state, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert reuse.headers["location"].endswith("oauth=success")
    reused_connections = db.scalars(
        select(GmailConnection)
        .where(GmailConnection.gmail_address == "owned@gmail.test")
        .order_by(GmailConnection.id)
    ).all()
    assert len(reused_connections) == 1
    reused = reused_connections[0]
    assert reused.id == historical_connection.id
    assert reused.status is GmailConnectionStatus.CONNECTED
    assert reused.user_id == auth["user"]["id"]
    replacement_credential = db.scalar(
        select(GmailOAuthCredential).where(GmailOAuthCredential.gmail_connection_id == reused.id)
    )
    assert replacement_credential is not None
    assert (
        TokenCipher.from_settings().decrypt(replacement_credential.encrypted_refresh_token)
        == "refresh"
    )
    recent = client.get(f"/api/v1/gmail-connections/{reused.id}/messages").json()
    assert recent["page"]["total"] == 1
    assert recent["items"][0]["subject"] == "Historical mailbox message"
    assert (
        db.scalar(
            select(func.count())
            .select_from(CarrierMessage)
            .where(CarrierMessage.gmail_message_id == "historical-owned-message")
        )
        == 1
    )
    db.refresh(case)
    db.refresh(open_task)
    db.refresh(completed_task)
    db.refresh(open_review)
    db.refresh(resolved_review)
    assert case.assigned_agent_id == auth["user"]["id"]
    assert case.assignment_source is CaseAssignmentSource.GMAIL_HANDOFF
    assert open_task.assigned_agent_id == auth["user"]["id"]
    assert open_review.assigned_reviewer_id == auth["user"]["id"]
    assert completed_task.assigned_agent_id == manager.id
    assert resolved_review.assigned_reviewer_id == manager.id


def test_active_duplicate_oauth_returns_safe_dedicated_result(
    client: TestClient, db: Session, login, configured_google, monkeypatch
) -> None:
    owner = db.scalar(select(User).where(User.email == "agent.one@demo.local"))
    assert owner is not None
    db.add(
        GmailConnection(
            agency_id=owner.agency_id,
            user_id=owner.id,
            gmail_address="active-owned@gmail.test",
            status=GmailConnectionStatus.CONNECTED,
        )
    )
    db.commit()
    fake = FakeOAuthClient(gmail_address="active-owned@gmail.test")
    patch_oauth(monkeypatch, fake)
    auth = login(client, "agent.two@demo.local")
    raw_state = start_oauth(client, auth, fake)
    response = client.get(
        "/api/v1/gmail/oauth/callback",
        params={"state": raw_state, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert response.headers["location"].endswith("oauth=already_connected")
