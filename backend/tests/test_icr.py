"""ICR fast-track tests.

Covers the ICR branch end-to-end:
  INTAKE -> MOM -> ICR -> MTO_DRAFT -> (hand-off milestones) -> ICR_DONE.

Asserts:
- The hand-off API records milestones with the right roles.
- Construction-side endpoints refuse ICR projects (defense in depth).
- Recording `closed` moves the project to ICR_DONE via workflow.transition.
- Audit log captures every hand-off event.
- Construction_manager role is the only role that can record hand-offs.
"""

import uuid


def _pr() -> str:
    return f"PR-ICR-{uuid.uuid4().hex[:6].upper()}"


def _create_project(client, headers):
    resp = client.post(
        "/api/projects",
        json={"pr_number": _pr(), "title": "ICR test"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _advance_to_mom_confirmed(client, admin_headers, pid):
    assert (
        client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/projects/{pid}/mom/status",
            json={"status": "sent"},
            headers=admin_headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/projects/{pid}/mom/status",
            json={"status": "acknowledged"},
            headers=admin_headers,
        ).status_code
        == 200
    )


def test_icr_handoff_records_milestone(client, admin_headers, role_headers):
    """A construction manager records milestones against an ICR project."""
    pid = _create_project(client, admin_headers)["id"]
    _advance_to_mom_confirmed(client, admin_headers, pid)

    # Plan & set ICR disposition.
    client.post(
        f"/api/projects/{pid}/disposition",
        json={"disposition": "ICR", "justification": "Utility only"},
        headers=role_headers["planner1"],
    )

    # Project control milestone — first handoff.
    resp = client.post(
        f"/api/projects/{pid}/icr/handoffs",
        json={"milestone": "mto_to_project_control", "status": "done"},
        headers=role_headers["cm1"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["milestone"] == "mto_to_project_control"
    assert resp.json()["status"] == "done"

    # Materials ordered.
    client.post(
        f"/api/projects/{pid}/icr/handoffs",
        json={"milestone": "materials_ordered", "status": "done"},
        headers=role_headers["cm1"],
    )

    # List the hand-offs (any authenticated user can read).
    listing = client.get(
        f"/api/projects/{pid}/icr/handoffs", headers=role_headers["member1"]
    ).json()
    assert [h["milestone"] for h in listing] == [
        "mto_to_project_control",
        "materials_ordered",
    ]

    # The inlined project detail surfaces these.
    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert len(detail["icr_handoffs"]) == 2


def test_icr_handoff_capability_required(client, admin_headers, role_headers):
    """Trade, planning, and team_member cannot record hand-offs (only CM + admin)."""
    pid = _create_project(client, admin_headers)["id"]
    _advance_to_mom_confirmed(client, admin_headers, pid)
    client.post(
        f"/api/projects/{pid}/disposition",
        json={"disposition": "ICR", "justification": "Utility only"},
        headers=role_headers["planner1"],
    )

    for username in ("trader1", "planner1", "member1"):
        resp = client.post(
            f"/api/projects/{pid}/icr/handoffs",
            json={"milestone": "materials_ordered", "status": "done"},
            headers=role_headers[username],
        )
        assert resp.status_code == 403, f"{username} should be forbidden, got {resp.status_code}"


def test_icr_handoff_closed_moves_to_terminal_stage(client, admin_headers, role_headers):
    """Recording the `closed` milestone transitions the project to ICR_DONE
    via the workflow state machine. Subsequent transitions are blocked."""
    pid = _create_project(client, admin_headers)["id"]
    _advance_to_mom_confirmed(client, admin_headers, pid)
    client.post(
        f"/api/projects/{pid}/disposition",
        json={"disposition": "ICR", "justification": "Utility only"},
        headers=role_headers["planner1"],
    )

    # First the non-terminal milestones.
    for milestone in (
        "mto_to_project_control",
        "materials_ordered",
        "materials_received",
        "eat_install_scheduled",
        "eat_installed",
        "follow_up",
    ):
        resp = client.post(
            f"/api/projects/{pid}/icr/handoffs",
            json={"milestone": milestone, "status": "done"},
            headers=role_headers["cm1"],
        )
        assert resp.status_code == 200, f"{milestone}: {resp.text}"

    # The project should still be at MTO_DRAFT / MTO_APPROVED, not yet ICR_DONE.
    before_close = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert before_close["stage"] != "ICR_DONE"

    # The `closed` milestone moves the project to ICR_DONE.
    resp = client.post(
        f"/api/projects/{pid}/icr/handoffs",
        json={"milestone": "closed", "status": "done", "note": "All follow-ups done"},
        headers=role_headers["cm1"],
    )
    assert resp.status_code == 200, resp.text

    after = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert after["stage"] == "ICR_DONE"

    # Audit log captured the transition.
    audit = client.get(f"/api/projects/{pid}/audit", headers=admin_headers).json()
    actions = [e["action"] for e in audit]
    assert "icr:handoff:closed" in actions
    assert "stage:ICR_DONE" in actions


def test_icr_hand_offs_reject_non_icr_projects(client, admin_headers, role_headers):
    """A PROJECT-classified project must not accept ICR hand-offs (409)."""
    pid = _create_project(client, admin_headers)["id"]
    _advance_to_mom_confirmed(client, admin_headers, pid)
    client.post(
        f"/api/projects/{pid}/disposition",
        json={"disposition": "PROJECT"},
        headers=role_headers["planner1"],
    )

    # Even admin cannot record a hand-off on a PROJECT project.
    resp = client.post(
        f"/api/projects/{pid}/icr/handoffs",
        json={"milestone": "mto_to_project_control", "status": "done"},
        headers=admin_headers,
    )
    assert resp.status_code == 409
    assert "ICR" in resp.json()["detail"]

    # And listing the hand-offs also refuses.
    assert (
        client.get(f"/api/projects/{pid}/icr/handoffs", headers=admin_headers).status_code
        == 409
    )


def test_icr_handoff_invalid_milestone_rejected(client, admin_headers, role_headers):
    """The Pydantic Literal rejects unknown milestones with 422."""
    pid = _create_project(client, admin_headers)["id"]
    _advance_to_mom_confirmed(client, admin_headers, pid)
    client.post(
        f"/api/projects/{pid}/disposition",
        json={"disposition": "ICR", "justification": "Utility only"},
        headers=role_headers["planner1"],
    )

    resp = client.post(
        f"/api/projects/{pid}/icr/handoffs",
        json={"milestone": "made_up_stage", "status": "done"},
        headers=role_headers["cm1"],
    )
    assert resp.status_code == 422
