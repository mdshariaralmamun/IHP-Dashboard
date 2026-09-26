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


@pytest.fixture()
def live_projects():
    """Three tracker-shaped test projects, removed again on teardown.

    Shared by the AI fact-pack and app-document tests: they assert behaviour
    that depends on real Planner fields (division, dates, flags).
    """
    from datetime import date, timedelta

    from app.db import SessionLocal
    from app.models import Project, User

    def _tracker(*, division, start, finish, completion, priority="Medium", flags=""):
        lines = [
            "Type: BASELINE",
            f"Division: {division}",
            f"Priority: {priority}",
            f"Start: {start}",
            f"Finish: {finish}",
            "Effort: 100 hours",
            "Duration: 10 days",
            f"Completion: {completion}%",
            "Planner Sync: 2026-01-01",
        ]
        if flags:
            lines.append(f"Flags: {flags}")
        return "\n".join(lines)

    today = date.today()
    db = SessionLocal()
    admin = db.query(User).filter(User.username == "admin").first()
    created_by = admin.id if admin else 1
    rows = [
        Project(
            pr_number="PR-99001",
            title="Test overdue chiller replacement",
            description=_tracker(
                division="Construction",
                priority="Urgent",
                start=(today - timedelta(days=30)).isoformat(),
                finish=(today - timedelta(days=9)).isoformat(),
                completion=40,
            ),
            planner_bucket="CONSTRUCTION",
            stage="CONSTRUCTION",
            location="B4",
            pi_name="Test PI",
            created_by_id=created_by,
        ),
        Project(
            pr_number="PR-99002",
            title="Test design package",
            description=_tracker(
                division="Design",
                start=(today - timedelta(days=2)).isoformat(),
                finish=(today + timedelta(days=3)).isoformat(),
                completion=10,
            ),
            planner_bucket="DESIGN",
            stage="SOW_DRAFT",
            created_by_id=created_by,
        ),
        Project(
            pr_number="PR-99003",
            title="Test on-hold works",
            description=_tracker(
                division="Construction",
                start=(today - timedelta(days=5)).isoformat(),
                finish=(today + timedelta(days=25)).isoformat(),
                completion=50,
                flags="ON HOLD",
            ),
            planner_bucket="CONSTRUCTION",
            stage="CONSTRUCTION",
            created_by_id=created_by,
        ),
    ]
    for row in rows:
        existing = db.query(Project).filter(Project.pr_number == row.pr_number).first()
        if existing is None:
            db.add(row)
    db.commit()
    try:
        yield db
    finally:
        for pr in ["PR-99001", "PR-99002", "PR-99003"]:
            row = db.query(Project).filter(Project.pr_number == pr).first()
            if row is not None:
                db.delete(row)
        db.commit()
        db.close()


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
