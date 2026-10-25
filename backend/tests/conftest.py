import os
import tempfile

# Tests run against a throwaway SQLite file unless TEST_DATABASE_URL points at PostgreSQL.
_db_file = os.path.join(tempfile.mkdtemp(prefix="bop-evolve-tests-"), "test.db")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_db_file}")
os.environ.setdefault("DEMO_PASSWORD", "Evolve#Demo2026")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.seed.seed_mock_data import Seeder  # noqa: E402

PASSWORD = os.environ["DEMO_PASSWORD"]


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        Seeder(db).run()
    yield


@pytest.fixture(scope="session")
def client():
    from app.main import app

    return TestClient(app)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture(scope="session")
def login(client):
    tokens: dict[str, dict] = {}

    def _login(username: str) -> dict:
        if username not in tokens:
            response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
            assert response.status_code == 200, response.text
            tokens[username] = {"Authorization": f"Bearer {response.json()['access_token']}"}
        return tokens[username]

    return _login
