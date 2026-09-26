"""Tests for the assistant's live fact pack (app.ai.facts).

These cover the bug report "the AI answer is not correct": the assistant used
to answer portfolio questions with an unrelated project list. Counting and
listing questions are now answered deterministically from the database.
"""

from datetime import date, timedelta

import pytest

from app.ai import facts as facts_mod
from app.db import SessionLocal
from app.models import Project, User

TEST_PRS = ["PR-99001", "PR-99002", "PR-99003"]


def _tracker(
    *,
    division: str,
    start: str,
    finish: str,
    completion: int,
    priority: str = "Medium",
    flags: str = "",
) -> str:
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


@pytest.fixture()
def live_projects():
    """Three tracker-shaped projects, removed again on teardown."""
    today = date.today()
    db = SessionLocal()
    admin = db.query(User).filter(User.username == "admin").first()
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
            created_by_id=admin.id if admin else 1,
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
            created_by_id=admin.id if admin else 1,
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
            created_by_id=admin.id if admin else 1,
        ),
    ]
    for row in rows:
        db.add(row)
    db.commit()
    try:
        yield db
    finally:
        for pr in TEST_PRS:
            row = db.query(Project).filter(Project.pr_number == pr).first()
            if row is not None:
                db.delete(row)
        db.commit()
        db.close()


def test_collect_finds_overdue_and_on_hold(live_projects):
    pack = facts_mod.collect(live_projects)
    assert "PR-99001" in {i.pr_number for i in pack["overdue"]}
    assert "PR-99003" not in {i.pr_number for i in pack["overdue"]}
    assert {i.pr_number for i in pack["on_hold"]} == {"PR-99003"}
    assert "PR-99002" in {i.pr_number for i in pack["this_week"]}
    assert pack["by_division"]["Construction"] >= 2
    assert pack["total"] >= 3


def test_render_carries_quick_answers_and_rows(live_projects):
    pack = facts_mod.collect(live_projects)
    text = facts_mod.render(pack)
    assert "QUICK ANSWERS" in text
    assert f"Total projects: {pack['total']}" in text
    assert "PR-99001" in text
    assert "days late" in text


def test_overdue_question_is_answered_from_the_database(live_projects):
    pack = facts_mod.collect(live_projects)
    text = facts_mod.answer("Which projects are overdue?", pack)
    assert text is not None
    assert "PR-99001" in text
    assert "PR-99002" not in text


def test_total_question_counts_every_project(live_projects):
    pack = facts_mod.collect(live_projects)
    text = facts_mod.answer("How many projects are there in total?", pack)
    assert text is not None
    assert f"**{pack['total']}**" in text


def test_compound_question_answers_every_metric(live_projects):
    """The reported question: total projects + ICR + active construction."""
    pack = facts_mod.collect(live_projects)
    text = facts_mod.answer(
        "check The Total Project 262 and ICR 0 Active Construction?", pack
    )
    assert text is not None
    assert f"Total projects: **{pack['total']}**" in text
    assert f"ICR / approval stage: **{pack['icr']}**" in text
    assert "Construction division" in text


def test_division_question_counts_that_division(live_projects):
    pack = facts_mod.collect(live_projects)
    text = facts_mod.answer("How many design projects are there?", pack)
    assert text is not None
    assert f"**{pack['by_division']['Design']}**" in text
    assert "Design division" in text


def test_open_ended_questions_stay_with_the_model(live_projects):
    pack = facts_mod.collect(live_projects)
    assert facts_mod.answer("Summarise the overdue work for the client", pack) is None
    assert facts_mod.answer("Draft a weekly report on construction", pack) is None


def test_project_question_answers_from_the_record(client, admin_headers, live_projects):
    project = (
        live_projects.query(Project).filter(Project.pr_number == "PR-99001").first()
    )
    resp = client.post(
        "/api/ai/ask",
        json={"question": "when is this project due?", "project_id": project.id},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "live"
    assert "PR-99001" in body["answer"]
    assert "days late" in body["answer"]
    assert "Planner finish" in body["answer"]


def test_portfolio_question_on_a_project_page_is_not_hijacked(
    client, admin_headers, live_projects
):
    """"which projects are overdue?" on a project page is still portfolio-wide."""
    project = (
        live_projects.query(Project).filter(Project.pr_number == "PR-99001").first()
    )
    resp = client.post(
        "/api/ai/ask",
        json={"question": "which projects are overdue?", "project_id": project.id},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "live"
    assert "overdue project" in body["answer"]
    assert "PR-99002" not in body["answer"]


def test_unknown_pr_numbers_are_detected():
    known = {"PR-99001"}
    assert facts_mod.unknown_pr_numbers("PR-99001 is late", known) == []
    assert facts_mod.unknown_pr_numbers("PR-99001 and PR-12345", known) == ["PR-12345"]


def test_ask_endpoint_answers_counts_without_a_model(client, admin_headers, live_projects):
    """The API returns the live answer even when no AI provider is reachable."""
    resp = client.post(
        "/api/ai/ask",
        json={"question": "Which projects are overdue?"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "live"
    assert "PR-99001" in body["answer"]
    assert any(s["filename"] == "Planner schedule" for s in body["sources"])
