"""Stage 2 Disposition tests: ICR vs PROJECT branching and RBAC."""

import uuid


def _pr_number() -> str:
    return f"PR-DISP-{uuid.uuid4().hex[:6].upper()}"


def _create_project(client, headers):
    resp = client.post(
        "/api/projects",
        json={
            "pr_number": _pr_number(),
            "title": "Disposition Test PR",
            "location": "Lab 101",
            "pi_name": "Prof. Test",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


def test_set_disposition_icr_branches_to_mto(client, admin_headers):
    proj = _create_project(client, admin_headers)
    resp = client.post(
        f"/api/projects/{proj['id']}/disposition",
        json={"disposition": "ICR", "justification": "Small equipment utility connection only."},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["disposition"] == "ICR"
    assert data["stage"] == "MTO_DRAFT"


def test_set_disposition_project_branches_to_ear(client, admin_headers):
    proj = _create_project(client, admin_headers)
    resp = client.post(
        f"/api/projects/{proj['id']}/disposition",
        json={"disposition": "PROJECT", "justification": "Full lab modification requiring engineering assessment."},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["disposition"] == "PROJECT"
    assert data["stage"] == "EAR_DRAFT"


def test_disposition_rbac(client, admin_headers, role_headers):
    proj = _create_project(client, admin_headers)

    # Team member cannot set disposition (403)
    resp = client.post(
        f"/api/projects/{proj['id']}/disposition",
        json={"disposition": "ICR"},
        headers=role_headers["member1"],
    )
    assert resp.status_code == 403

    # Planning user CAN set disposition (200)
    resp = client.post(
        f"/api/projects/{proj['id']}/disposition",
        json={"disposition": "PROJECT", "justification": "Planning decision"},
        headers=role_headers["planner1"],
    )
    assert resp.status_code == 200
    assert resp.json()["disposition"] == "PROJECT"


def test_icr_skips_ear_and_sow(client, admin_headers, role_headers):
    """ICR-classified projects must reject EAR and SOW endpoints with 409."""
    proj = _create_project(client, admin_headers)
    resp = client.post(
        f"/api/projects/{proj['id']}/disposition",
        json={"disposition": "ICR", "justification": "Fast-track utility connection."},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["disposition"] == "ICR"
    assert resp.json()["stage"] == "MTO_DRAFT"

    # EAR endpoint must refuse to create an EAR record for an ICR project.
    resp = client.get(
        f"/api/projects/{proj['id']}/ear",
        headers=admin_headers,
    )
    assert resp.status_code == 409
    assert "ICR" in resp.json()["detail"]

    # SOW create must also refuse.
    resp = client.post(
        f"/api/projects/{proj['id']}/sow",
        json={"revision_name": "Rev-0"},
        headers=role_headers["planner1"],
    )
    assert resp.status_code == 409
    assert "ICR" in resp.json()["detail"]
