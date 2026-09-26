"""Ownership data ("EAR assigned to") must reach the assistant."""

from datetime import date, timedelta

from app.ai import facts as facts_mod
from app.api.projects import _derive_tracker_fields

DESCRIPTION = "\n".join([
    "Type: BASELINE",
    "Division: EAR",
    "Priority: Medium",
    "Assigned To: Assam Hmshw",
    "Execution Lead: Varun Kizhakkoot",
    "Requestor: Muhammad Seraj",
    "Start: 2026-09-14",
    "Finish: 2026-09-24",
    "Planner Sync: 2026-01-01",
])


class _Stub:
    description = DESCRIPTION
    planner_bucket = "EAR"
    stage = "EAR_REVIEW"


def test_planner_ownership_columns_are_parsed():
    derived = _derive_tracker_fields(_Stub())
    assert derived["assigned_to"] == "Assam Hmshw"
    assert derived["execution_lead"] == "Varun Kizhakkoot"
    assert derived["requestor"] == "Muhammad Seraj"


def _add_owner(db, pr_number: str = "PR-99001") -> None:
    from app.models import Project

    project = db.query(Project).filter(Project.pr_number == pr_number).first()
    project.description = (
        project.description + "\nAssigned To: Test Engineer\nExecution Lead: Test Lead"
    )
    db.commit()


def test_assignment_is_in_the_fact_pack(live_projects):
    db = live_projects
    _add_owner(db)

    pack = facts_mod.collect(db)
    row = next((a for a in pack["assignments"] if a["pr_number"] == "PR-99001"), None)
    assert row is not None
    assert row["assigned_to"] == "Test Engineer"

    text = facts_mod.render(pack)
    assert "ASSIGNMENTS" in text
    assert "assigned to Test Engineer" in text

    # Scheduled rows carry the owner too, so lists show who holds the work.
    overdue = next((i for i in pack["overdue"] if i.pr_number == "PR-99001"), None)
    assert overdue is not None and overdue.assigned_to == "Test Engineer"


def test_who_is_assigned_is_answered_deterministically(live_projects):
    db = live_projects
    _add_owner(db)
    pack = facts_mod.collect(db)

    answer = facts_mod.answer("Who is assigned to these projects?", pack)
    assert answer is not None
    assert "Test Engineer" in answer

    # Division scope is honoured ("PR-99001" is a Construction-division row).
    scoped = facts_mod.answer("who is assigned in the construction division?", pack)
    assert scoped is not None and "Test Engineer" in scoped
    empty = facts_mod.answer("who is the EAR assigned to?", pack)
    assert empty is not None and "None" in empty

    # The same question for a specific project is answered from its record.
    from app.models import Project

    project = db.query(Project).filter(Project.pr_number == "PR-99001").first()
    direct = facts_mod.project_answer(
        "who is this assigned to?", project, _derive_tracker_fields(project)
    )
    assert direct is not None and "Test Engineer" in direct


def test_typo_and_multi_name_cells_are_handled(live_projects):
    """"EAR asign To" (typo) must work, and MS Project joins owners with commas."""
    from app.models import Project

    db = live_projects
    project = db.query(Project).filter(Project.pr_number == "PR-99001").first()
    # Move the row into the EAR division so the EAR-scoped question applies.
    project.planner_bucket = "EAR"
    project.description = (
        project.description.replace("Division: Construction", "Division: EAR")
        + "\nAssigned To: Test Engineer, Second Engineer\nExecution Lead: Test Lead"
    )
    db.commit()
    pack = facts_mod.collect(db)

    typo = facts_mod.answer("EAR asign To", pack)
    assert typo is not None
    assert "Test Engineer" in typo and "Second Engineer" in typo

    mine = facts_mod.answer("what is Second Engineer working on?", pack)
    assert mine is not None and "PR-99001" in mine and "Second Engineer" in mine


def test_unknown_owner_does_not_crash(live_projects):
    """No ownership column at all: the assistant must say so, not invent one."""
    from app.db import SessionLocal
    from app.models import Project

    db = SessionLocal()
    pack = facts_mod.collect(db)
    # PR-99002 has no Assigned To line.
    assert all(a["pr_number"] != "PR-99002" for a in pack["assignments"])
    answer = facts_mod.answer("who is assigned to PR-99002?", pack)
    assert answer is None or "PR-99002" not in answer
