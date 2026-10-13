"""The Project Delivery Assistant: the gate, the writes and the labour rule.

The AI is monkeypatched (no network in CI), so these tests assert two things:
what the assistant does with a well-formed model answer, and that the gates hold
whatever the model asks for.
"""

import uuid

import pytest

from app.ai import provider
from app.db import SessionLocal
from app.models import (
    AssistantMessage,
    BoqMtoItem,
    EarRecord,
    EarTradeInput,
    MomRecord,
    PipelineStage,
    Project,
    SowRecord,
)
from app.services import assistant_orchestrator as assistant

#: One payload that satisfies every writer (each writer picks the keys it needs).
PLAN = {
    "meeting_title": "New gas line for the plasma etcher",
    "location": "B5 - Room 5-3201",
    "date": "2026-10-13",
    "time": "10:00-11:30",
    "attendees": [{"name": "Dr. Example", "title": "PI", "email": "pi@example.kaust.edu.sa"}],
    "agenda": [{"scope": "New gas line", "action": "Issue the SOW", "responsible": "IHP"}],
    "summary": "Install a new gas line for the plasma etcher, all works by IHP.",
    "scope": "Supply and install the gas line, piping and tie-in.",
    "trades": [{"group": "C", "assessment": "Gas piping tie-in to the manifold",
                "materials_sar": 12000, "equipment_sar": 0, "consumables_sar": 300}],
    "recommendations": "Proceed with the gas piping tie-in after the isolation test.",
    "trade_budgets": {"C": {"proposal": "Tie in to the existing manifold", "materials": 12000}},
    "scope_text": "Scope of work for the new gas line.",
    "trade_sections": [{
        "group": "C",
        "scope": "Gas piping",
        "items": [{"description": "Gas line to the etcher", "unit": "Lot", "qty": 1}],
        "mto_items": [{"description": "Gas line", "unit": "Lot", "qty": 1,
                       "computation": "Supply & Install by IHP"}],
    }],
    "drawings": [{"drawing_no": "M-101", "rev": "0", "title": "Gas routing",
                  "date": "2026-10-13", "status": "IFC"}],
    "items": [{"group": "C", "item_code": "C.1", "description": "Gas piping",
               "unit": "Lot", "quantity": 1}],
}


def _fake_ai(system, prompt, *, model=None, provider_id=None):
    if "choosing the next step" in system:
        return {"action": "mom.draft", "reason": "meeting notes received",
                "reply": "I will draft the MOM from these notes."}
    return {"data": dict(PLAN)}


@pytest.fixture(autouse=True)
def ai_ready(monkeypatch):
    """A reachable provider and a deterministic model answer."""
    monkeypatch.setattr(provider, "available", lambda: (True, None))
    monkeypatch.setattr(assistant, "_ai_json", _fake_ai)


def _cleanup(project_id: int) -> None:
    db = SessionLocal()
    try:
        ear_ids = [e.id for e in db.query(EarRecord).filter(EarRecord.project_id == project_id)]
        if ear_ids:
            db.query(EarTradeInput).filter(
                EarTradeInput.ear_id.in_(ear_ids)
            ).delete(synchronize_session=False)
        db.query(EarRecord).filter(EarRecord.project_id == project_id).delete()
        db.query(SowRecord).filter(SowRecord.project_id == project_id).delete()
        db.query(BoqMtoItem).filter(BoqMtoItem.project_id == project_id).delete()
        db.query(MomRecord).filter(MomRecord.project_id == project_id).delete()
        db.query(PipelineStage).filter(PipelineStage.project_id == project_id).delete()
        db.query(AssistantMessage).filter(AssistantMessage.project_id == project_id).delete()
        db.query(Project).filter(Project.id == project_id).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def project(client, admin_headers):
    pr = "PR-AS-" + uuid.uuid4().hex[:8].upper()
    resp = client.post(
        "/api/projects",
        json={
            "pr_number": pr,
            "title": "Assistant gas line",
            "description": "Type: BASELINE\nDivision: PSE",
            "pi_name": "Dr. Example",
            "pi_email": "pi@example.kaust.edu.sa",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    _cleanup(data["id"])


def _run(client, headers, project_id: int, action: str):
    return client.post(
        f"/api/projects/{project_id}/assistant/run", json={"action": action}, headers=headers
    )


def _set_stages(project_id: int, statuses: dict) -> None:
    db = SessionLocal()
    try:
        for stage, state in statuses.items():
            row = (
                db.query(PipelineStage)
                .filter(PipelineStage.project_id == project_id, PipelineStage.stage == stage)
                .first()
            )
            if row is None:
                db.add(PipelineStage(project_id=project_id, stage=stage, status=state))
            else:
                row.status = state
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
def test_state_lists_allowed_and_blocked_actions(client, admin_headers, project):
    resp = client.get(f"/api/projects/{project['id']}/assistant", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "mom.draft" in data["gate"]["allowed"]
    assert "mom.confirm" in data["gate"]["allowed"]
    assert "sow.draft" in data["gate"]["blocked"]
    assert "mto.draft" in data["gate"]["blocked"]
    assert data["ear"]["parallel"] is True
    assert data["ai"]["provider"]
    assert len(data["actions"]) == 13


def test_gate_refuses_sow_before_mom_confirmed(client, admin_headers, project):
    resp = _run(client, admin_headers, project["id"], "sow.draft")
    assert resp.status_code == 409, resp.text
    assert "Stage 2" in resp.json()["detail"] or "MOM" in resp.json()["detail"]


def test_gate_refuses_mto_until_procore_approved(client, admin_headers, project):
    _set_stages(project["id"], {1: "confirmed", 2: "approved", 3: "approved"})
    resp = _run(client, admin_headers, project["id"], "mto.draft")
    assert resp.status_code == 409, resp.text
    assert "MTO" in resp.json()["detail"]


def test_mom_draft_writes_record_and_audit(client, admin_headers, project):
    pid = project["id"]
    resp = _run(client, admin_headers, pid, "mom.draft")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["artifacts"][0]["kind"] == "docx"
    assert body["artifacts"][0]["panel"] == "MomPanel"

    db = SessionLocal()
    mom = db.query(MomRecord).filter(MomRecord.project_id == pid).first()
    assert mom is not None and mom.version == 1
    assert mom.details["meeting_title"] == PLAN["meeting_title"]
    assert mom.email_subject
    db.close()

    audit = client.get(f"/api/projects/{pid}/audit", headers=admin_headers)
    assert audit.status_code == 200
    assert "assistant:mom" in str(audit.json())


def test_ear_track_runs_parallel_to_the_spine(client, admin_headers, project):
    pid = project["id"]
    assert _run(client, admin_headers, pid, "mom.confirm").status_code == 200
    resp = _run(client, admin_headers, pid, "ear.draft")
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    ear = db.query(EarRecord).filter(EarRecord.project_id == pid).first()
    assert ear is not None
    assert len(ear.trade_inputs) == 6
    assert all(t.estimated_manpower_cost == 0.0 for t in ear.trade_inputs)
    db.close()

    pipeline = client.get(f"/api/projects/{pid}/pipeline", headers=admin_headers).json()
    stage_two = [s for s in pipeline["stages"] if s["stage"] == 2][0]
    assert stage_two["status"] == "not_started"  # the EAR ran beside the spine


def test_propose_writes_user_turn_and_proposes_one_action(client, admin_headers, project):
    pid = project["id"]
    resp = client.post(
        f"/api/projects/{pid}/assistant/message",
        json={"message": "Meeting notes: new gas line for the plasma etcher."},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["suggested_action"] == "mom.draft"
    assert body["needs_confirmation"] is True
    assert body["role"] == "assistant"

    turns = client.get(f"/api/projects/{pid}/assistant/messages", headers=admin_headers).json()
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["content"].startswith("Meeting notes")


def test_labour_never_enters_a_total(client, admin_headers, project):
    pid = project["id"]
    for action in (
        "mom.draft", "mom.confirm", "summary.draft", "summary.approve",
        "ear.draft", "sow.draft", "boq.draft",
    ):
        resp = _run(client, admin_headers, pid, action)
        assert resp.status_code == 200, action + ": " + resp.text

    db = SessionLocal()
    items = db.query(BoqMtoItem).filter(BoqMtoItem.project_id == pid).all()
    assert items
    assert all(i.unit_rate == 0.0 and i.total_rate == 0.0 for i in items)
    ear = db.query(EarRecord).filter(EarRecord.project_id == pid).first()
    assert all(t.estimated_manpower_cost == 0.0 for t in ear.trade_inputs)
    db.close()

    turns = client.get(f"/api/projects/{pid}/assistant/messages", headers=admin_headers).json()
    text = " ".join(t["content"] for t in turns)
    assert "Labor: IHP In-House Resources" in text
    assert "$0.00" in text


def test_provider_offline_returns_503(client, admin_headers, project, monkeypatch):
    monkeypatch.setattr(
        provider, "available", lambda: (False, "No API key configured for DeepSeek.")
    )
    resp = client.post(
        f"/api/projects/{project['id']}/assistant/message",
        json={"message": "notes"},
        headers=admin_headers,
    )
    assert resp.status_code == 503, resp.text
    assert "No API key" in resp.json()["detail"]


def test_unknown_action_is_404(client, admin_headers, project):
    resp = _run(client, admin_headers, project["id"], "do.magic")
    assert resp.status_code == 404
    assert "Valid" in resp.json()["detail"]


def test_transcript_order_and_limit(client, admin_headers, project):
    pid = project["id"]
    assert _run(client, admin_headers, pid, "mom.draft").status_code == 200
    for text in ("one", "two"):
        client.post(
            f"/api/projects/{pid}/assistant/message", json={"message": text}, headers=admin_headers
        )
    turns = client.get(
        f"/api/projects/{pid}/assistant/messages?limit=2", headers=admin_headers
    ).json()
    assert len(turns) == 2
    assert turns[0]["id"] < turns[1]["id"]
    everything = client.get(f"/api/projects/{pid}/assistant/messages", headers=admin_headers).json()
    assert turns == everything[-2:]


def test_reset_clears_the_transcript(client, admin_headers, project):
    pid = project["id"]
    client.post(
        f"/api/projects/{pid}/assistant/message", json={"message": "notes"}, headers=admin_headers
    )
    assert client.delete(
        f"/api/projects/{pid}/assistant/messages", headers=admin_headers
    ).status_code == 204
    assert client.get(
        f"/api/projects/{pid}/assistant/messages", headers=admin_headers
    ).json() == []

def test_sow_approve_issues_the_package(client, admin_headers, project):
    pid = project["id"]
    for action in ("mom.confirm", "summary.approve", "sow.draft", "sow.approve"):
        resp = _run(client, admin_headers, pid, action)
        assert resp.status_code == 200, action + ": " + resp.text
    pipeline = client.get(f"/api/projects/{pid}/pipeline", headers=admin_headers).json()
    stage_three = [s for s in pipeline["stages"] if s["stage"] == 3][0]
    assert stage_three["status"] == "approved"
    # the binder gate is open now (the PDF itself needs PyMuPDF + LibreOffice,
    # which the live container has and a bare dev venv may not, so the gate is
    # asserted from the state endpoint instead of by building the file)
    state = client.get(f"/api/projects/{pid}/assistant", headers=admin_headers).json()
    assert "package.binder" not in state["gate"]["blocked"]


def test_procore_status_set_by_hand_unlocks_the_mto(client, admin_headers, project):
    pid = project["id"]
    _set_stages(pid, {1: "confirmed", 2: "approved", 3: "approved"})
    assert _run(client, admin_headers, pid, "mto.draft").status_code == 409
    patched = client.patch(
        f"/api/projects/{pid}/procore",
        json={"procore_status": "Approved as Noted"},
        headers=admin_headers,
    )
    assert patched.status_code == 200, patched.text
    resp = _run(client, admin_headers, pid, "mto.draft")
    assert resp.status_code == 200, resp.text
    db = SessionLocal()
    items = db.query(BoqMtoItem).filter(BoqMtoItem.project_id == pid).all()
    assert items and all(i.unit_rate == 0.0 for i in items)
    db.close()


def test_boq_falls_back_to_the_sow_measurements(client, admin_headers, project, monkeypatch):
    """A useless model answer must not produce an empty BOQ."""

    def _no_boq(system, prompt, *, model=None, provider_id=None):
        if "choosing the next step" in system:
            return {"action": "mom.draft", "reason": "notes", "reply": "Drafting the MOM."}
        if "bill of quantities lines" in prompt:
            return {}
        return {"data": dict(PLAN)}

    monkeypatch.setattr(assistant, "_ai_json", _no_boq)
    pid = project["id"]
    for action in ("mom.draft", "mom.confirm", "summary.draft", "summary.approve", "sow.draft"):
        assert _run(client, admin_headers, pid, action).status_code == 200
    resp = _run(client, admin_headers, pid, "boq.draft")
    assert resp.status_code == 200, resp.text
    assert "from the SOW measurements" in resp.json()["content"]
    db = SessionLocal()
    items = db.query(BoqMtoItem).filter(BoqMtoItem.project_id == pid).all()
    assert items, "the BOQ fell back to nothing"
    assert all(i.unit_rate == 0.0 and i.total_rate == 0.0 for i in items)
    db.close()

PROSE = '''
- Replace the 2 air-handling units on the roof level (HVAC).
- New dedicated 60 A electrical supply with a new panel for the etcher.
- Gas piping tie-in to the existing manifold, including the isolation valve.
- Low current points for the new thermostats and gas detection.
- Leak test and purge before commissioning.
Action: IHP to issue the SOW, BOQ and the drawing list within two weeks.
'''


def test_mom_agenda_splits_prose_into_scope_points():
    rows = assistant._agenda_from_notes(PROSE)
    assert len(rows) >= 3, rows
    trades = {row['trade'] for row in rows}
    assert 'Plumbing' in trades
    assert 'Electrical' in trades
    assert all(row['scope'].strip() for row in rows)
    acting = [row for row in rows if row['responsible'] == 'IHP']
    assert acting, rows
    assert 'to issue' in acting[0]['action']


def test_mom_agenda_from_prose_notes(client, admin_headers, project, monkeypatch):
    """A model that returns no agenda must still leave a usable minute."""

    def _no_agenda(system, prompt, *, model=None, provider_id=None):
        if "choosing the next step" in system:
            return {"action": "mom.draft", "reason": "notes", "reply": "Drafting the MOM."}
        return {"data": {"meeting_title": "Gas line site meeting", "attendees": [
            {"name": "Atteq UrRehman", "title": "PI", "email": ""}], "agenda": []}}

    monkeypatch.setattr(assistant, "_ai_json", _no_agenda)
    pid = project["id"]
    resp = client.post(
        f"/api/projects/{pid}/assistant/run",
        json={"action": "mom.draft", "note": PROSE},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "from your notes" in body["content"]
    assert "0 agenda item" not in body["content"]
    table = [a for a in body['artifacts'] if a['kind'] == 'table'][0]
    agenda = table['meta']['agenda']
    assert len(agenda) >= 3
    db = SessionLocal()
    mom = db.query(MomRecord).filter(MomRecord.project_id == pid).first()
    assert len(mom.details['agenda']) >= 3
    assert all(row['scope'] for row in mom.details['agenda'])
    db.close()


def test_mom_detail_aliases_are_normalised(client, admin_headers, project, monkeypatch):
    def _aliases(system, prompt, *, model=None, provider_id=None):
        if "choosing the next step" in system:
            return {"action": "mom.draft", "reason": "notes", "reply": "Drafting the MOM."}
        return {"data": {
            "title": "Gas line kick-off",
            "date": "2026-10-14",
            "location": "B5 - Room 5-3201",
            "time": "10:00-11:30",
            "agenda": [{"scope": "Install the gas line", "action": "IHP to issue the SOW",
                        "responsible": "IHP"}],
        }}

    monkeypatch.setattr(assistant, "_ai_json", _aliases)
    pid = project["id"]
    resp = _run(client, admin_headers, pid, "mom.draft")
    assert resp.status_code == 200, resp.text
    db = SessionLocal()
    mom = db.query(MomRecord).filter(MomRecord.project_id == pid).first()
    assert mom.details['meeting_title'] == 'Gas line kick-off'
    assert mom.details['meeting_date'] == '2026-10-14'
    assert mom.details['meeting_location'] == 'B5 - Room 5-3201'
    assert mom.details['meeting_time'] == '10:00-11:30'
    db.close()


def test_actions_endpoint_lists_the_registry(client, admin_headers, project):
    resp = client.get(f"/api/projects/{project['id']}/assistant/actions", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 13
    ids = {row['id'] for row in rows}
    assert {'mom.draft', 'summary.draft', 'ear.draft', 'sow.draft', 'boq.draft',
            'drawings.list', 'sow.approve', 'package.binder', 'mto.draft'} <= ids
    assert all(row['capability'] and row['panel'] for row in rows)
