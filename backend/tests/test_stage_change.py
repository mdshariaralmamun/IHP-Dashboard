"""Moving a project between phases, with a reason that is kept.

A stage change is the one place a human overrules the tracker, so the rules
are: a justification is mandatory, a normal move walks the workflow, and a
move the workflow does not connect needs an admin and is recorded as an
override rather than passing as a routine transition.
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import AuditLog, Project
from app.services import workflow

_SEQ = iter(range(9900, 9999))


@pytest.fixture()
def new_project(client, admin_headers):
    pr = f"PR-{next(_SEQ)}"
    resp = client.post(
        "/api/projects", headers=admin_headers,
        json={"pr_number": pr, "title": f"Stage test {pr}"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _set_stage_directly(pr_number: str, stage: str) -> None:
    """Parking a project at a stage the API cannot reach (a terminal one)."""
    db = SessionLocal()
    try:
        project = db.query(Project).filter_by(pr_number=pr_number).one()
        project.stage = stage
        db.commit()
    finally:
        db.close()


def _audit(project_id: int) -> list[AuditLog]:
    db = SessionLocal()
    try:
        return (
            db.query(AuditLog)
            .filter(AuditLog.project_id == project_id)
            .order_by(AuditLog.id)
            .all()
        )
    finally:
        db.close()


class TestStageChange:
    def test_a_justification_is_required(
        self, client, admin_headers, new_project,
    ):
        resp = client.post(
            f"/api/projects/{new_project['id']}/stage",
            headers=admin_headers,
            json={"stage": "EAR_REVIEW"},
        )
        assert resp.status_code == 400
        assert "justification" in resp.text.lower()
        assert "EAR_REVIEW" not in resp.text or "justification" in resp.text.lower()

    def test_a_blank_justification_is_rejected(
        self, client, admin_headers, new_project,
    ):
        resp = client.post(
            f"/api/projects/{new_project['id']}/stage",
            headers=admin_headers,
            json={"stage": "EAR_REVIEW", "justification": "   "},
        )
        assert resp.status_code == 400

    def test_a_legal_move_walks_the_workflow_and_keeps_the_reason(
        self, client, admin_headers, new_project,
    ):
        reason = "Design phase per Planners tracker for PR-12649."
        resp = client.post(
            f"/api/projects/{new_project['id']}/stage",
            headers=admin_headers,
            json={"stage": "EAR_REVIEW", "justification": reason},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == "EAR_REVIEW"

        hops = [a for a in _audit(new_project["id"]) if a.action.startswith("stage:")]
        assert hops, "each hop of the walk is audited"
        assert all(a.detail.get("justification") == reason for a in hops), (
            "the reason travels onto every hop, otherwise the trail cannot be read"
        )
        assert [a.detail["to"] for a in hops][-1] == "EAR_REVIEW"

    def test_an_unconnected_move_is_refused_without_force(
        self, client, admin_headers, new_project,
    ):
        # ICR_DONE is terminal: the workflow has no path out of it.
        _set_stage_directly(new_project["pr_number"], "ICR_DONE")
        resp = client.post(
            f"/api/projects/{new_project['id']}/stage",
            headers=admin_headers,
            json={"stage": "EAR_DRAFT", "justification": "Reopened at PI request."},
        )
        assert resp.status_code == 409
        assert "force" in resp.text.lower()

    def test_an_admin_can_force_it_and_the_trail_says_so(
        self, client, admin_headers, new_project,
    ):
        _set_stage_directly(new_project["pr_number"], "ICR_DONE")
        reason = "Reopened: the equipment scope became a construction project."
        resp = client.post(
            f"/api/projects/{new_project['id']}/stage",
            headers=admin_headers,
            json={
                "stage": "EAR_DRAFT",
                "justification": reason,
                "force": True,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == "EAR_DRAFT"

        last = _audit(new_project["id"])[-1]
        assert last.action == "stage:override", (
            "a bypassed workflow must never be recorded as a normal transition"
        )
        assert last.detail["from"] == "ICR_DONE"
        assert last.detail["to"] == "EAR_DRAFT"
        assert last.detail["justification"] == reason


class TestCancelledStage:
    def test_cancelling_is_possible_from_every_live_stage(self):
        for stage, nxt in workflow.ALLOWED_TRANSITIONS.items():
            if stage in {workflow.PUNCH_LIST, workflow.ICR_DONE, workflow.CANCELLED}:
                continue
            assert workflow.CANCELLED in nxt, f"cannot cancel from {stage}"

    def test_cancelled_is_terminal(self):
        assert workflow.CANCELLED in workflow.STAGES
        assert workflow.ALLOWED_TRANSITIONS[workflow.CANCELLED] == set()

    def test_cancelling_a_project_records_the_reason(
        self, client, admin_headers, new_project,
    ):
        reason = "Budget pulled for now; the PI will re-initiate under a new PR."
        resp = client.post(
            f"/api/projects/{new_project['id']}/stage",
            headers=admin_headers,
            json={"stage": "CANCELLED", "justification": reason},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == "CANCELLED"
        assert _audit(new_project["id"])[-1].detail["justification"] == reason
