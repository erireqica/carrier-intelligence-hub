from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base
from app.db.seed import seed_demo_data
from app.db.session import get_db_session
from app.main import create_app

TEST_PASSWORD = "demo-test-password"


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine]:
    database_url = get_settings().test_database_url
    if database_url is None:
        pytest.fail("TEST_DATABASE_URL must point to the dedicated PostgreSQL test database")
    url = make_url(str(database_url))
    if url.get_backend_name() != "postgresql" or url.database != "carrier_intelligence_hub_test":
        pytest.fail("Tests refuse to run outside carrier_intelligence_hub_test on PostgreSQL")

    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as connection:
        Base.metadata.drop_all(connection)
        Base.metadata.create_all(connection)
    yield engine
    with engine.begin() as connection:
        Base.metadata.drop_all(connection)
    engine.dispose()


@pytest.fixture
def db(test_engine: Engine) -> Generator[Session]:
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def seeded_db(db: Session) -> Session:
    seed_demo_data(db, TEST_PASSWORD)
    return db


@pytest.fixture
def client(seeded_db: Session) -> Generator[TestClient]:
    application = create_app()

    def override_db() -> Generator[Session]:
        yield seeded_db

    application.dependency_overrides[get_db_session] = override_db
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def login() -> Callable[[TestClient, str], dict]:
    def sign_in(test_client: TestClient, email: str) -> dict:
        response = test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200
        return response.json()

    return sign_in
