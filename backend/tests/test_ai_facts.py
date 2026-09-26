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
