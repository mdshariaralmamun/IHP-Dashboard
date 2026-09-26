"""Test fixtures: TestClient backed by an in-memory SQLite database.

Environment variables are set BEFORE importing the app so the app's own
engine binds to a process-wide in-memory SQLite database (StaticPool in
app.db keeps the single in-memory connection alive). DATA_DIR is an
isolated temp dir; TEMPLATES_DIR points at the real backend/templates.
"""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
_TMP_DIR = tempfile.mkdtemp(prefix="ihp_test_")

os.environ["DATABASE_URL"] = "sqlite://"  # in-memory (StaticPool keeps it alive)
os.environ["DATA_DIR"] = _TMP_DIR
os.environ["TEMPLATES_DIR"] = str(BACKEND_DIR / "templates")
os.environ["SECRET_KEY"] = "test-secret-key-with-at-least-32-bytes"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ.pop("SMTP_HOST", None)  # draft-only email mode

from app.core.security import hash_password  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402

TEST_PASSWORD = "password123"

#: One non-admin user per role: (username, full_name, role, trade)
ROLE_USERS = [
    ("trader1", "Trade User", "trade", "civil_arch"),
    ("planner1", "Planning User", "planning", None),
    ("cm1", "Construction Manager", "construction_manager", None),
    ("member1", "Team Member", "team_member", None),
]


def _seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add(
                User(
                    username="admin",
                    full_name="Platform Administrator",
                    email="admin@example.com",
                    hashed_password=hash_password("admin123"),
                    role="admin",
                    is_active=True,
                )
            )
            for username, full_name, role, trade in ROLE_USERS:
                db.add(
                    User(
                        username=username,
                        full_name=full_name,
                        email=f"{username}@example.com",
                        hashed_password=hash_password(TEST_PASSWORD),
                        role=role,
                        trade=trade,
                        is_active=True,
                    )
                )
            db.commit()
    finally:
        db.close()


_seed()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return Path(_TMP_DIR)


def login(client: TestClient, username: str, password: str) -> str:
    resp = client.post(
        "/api/auth/login", data={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def headers_for(client: TestClient, username: str, password: str = TEST_PASSWORD):
    return {"Authorization": f"Bearer {login(client, username, password)}"}


@pytest.fixture(scope="session")
def admin_headers(client):
    return headers_for(client, "admin", "admin123")


@pytest.fixture(scope="session")
def role_headers(client):
    """Mapping of username -> auth headers for each seeded non-admin user."""
    return {u[0]: headers_for(client, u[0]) for u in ROLE_USERS}
