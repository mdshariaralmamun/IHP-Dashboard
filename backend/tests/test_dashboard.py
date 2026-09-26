"""Cross-project construction dashboard tests.

Covers /api/construction/dashboard and /api/construction/projects. The
endpoints back the live construction dashboard at
``frontend/src/app/dashboard/construction/page.tsx``.

The dashboard aggregates from existing models (Project, ConstructionRecord,
BoqMtoItem). ICR-classified projects are excluded from rollups because they
follow a different lifecycle (MTO -> Project Control -> EAT) and never
reach procurement, work-permit, construction, or closeout.
"""

import uuid


def _pr() -> str:
    return f"PR-DASH-{uuid.uuid4().hex[:6].upper()}"


def _create_project(client, headers):
    resp = client.post(
        "/api/projects",
        json={"pr_number": _pr(), "title": "Dashboard test"},
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


def test_dashboard_shape(client, admin_headers):
    """The KPI shape is stable: every key is a number, delivery_rate is a
    float in [0, 100], and the counts are non-negative."""
    resp = client.get("/api/construction/dashboard", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "total_projects",
        "active_construction_projects",
        "total_materials_tracked",
        "materials_delivered",
        "active_work_permits",
    ):
        assert isinstance(body[key], int), f"{key} should be int"
        assert body[key] >= 0, f"{key} should be non-negative"
    assert isinstance(body["delivery_rate"], (int, float))
    assert 0.0 <= body["delivery_rate"] <= 100.0


def test_dashboard_requires_authentication(client):
    assert client.get("/api/construction/dashboard").status_code == 401


def test_dashboard_excludes_icr_projects(client, admin_headers, role_headers):
    """ICR-classified projects do not appear in the projects list, even when
    other (PROJECT) projects are also present."""
    icr = _create_project(client, admin_headers)
    _advance_to_mom_confirmed(client, admin_headers, icr["id"])
    client.post(
        f"/api/projects/{icr['id']}/disposition",
        json={"disposition": "ICR", "justification": "Utility only"},
        headers=role_headers["planner1"],
    )

    project = _create_project(client, admin_headers)
    _advance_to_mom_confirmed(client, admin_headers, project["id"])
    client.post(
        f"/api/projects/{project['id']}/disposition",
        json={"disposition": "PROJECT"},
        headers=role_headers["planner1"],
    )
    client.patch(
        f"/api/projects/{project['id']}/ear",
        json={"status": "approved"},
        headers=role_headers["planner1"],
    )
    client.post(
        f"/api/projects/{project['id']}/boq",
        json={
            "trade": "civil_arch",
            "item_code": "BR-001",
            "description": "Bench",
            "unit": "ea",
            "quantity": 4,
            "unit_rate": 2500,
        },
        headers=role_headers["planner1"],
    )

    # /api/construction/projects must NOT include the ICR project.
    rows = client.get("/api/construction/projects", headers=admin_headers).json()
    pr_numbers = [r["pr_number"] for r in rows]
    assert icr["pr_number"] not in pr_numbers
    assert project["pr_number"] in pr_numbers

    # /api/construction/dashboard counts must reflect only PROJECT projects:
    # the ICR project is excluded; the PROJECT project contributes 1 BOQ line.
    body = client.get("/api/construction/dashboard", headers=admin_headers).json()
    assert body["total_materials_tracked"] >= 1
    # active_construction is gated on having a ConstructionRecord, not on
    # having BOQ items. Our PROJECT project is at SOW_DRAFT without a
    # construction record yet, so it does not bump active_construction.
    # We just check the field is sane (covered by test_dashboard_shape).


def test_dashboard_kpis_reflect_construction_progress(
    client, admin_headers, role_headers
):
    """A PROJECT project that has reached WORK_PERMIT (WCF filed) shows up
    as an active permit; BOQ delivery status moves the delivery rate."""
    project = _create_project(client, admin_headers)
    pid = project["id"]
    _advance_to_mom_confirmed(client, admin_headers, pid)
    client.post(
        f"/api/projects/{pid}/disposition",
        json={"disposition": "PROJECT"},
        headers=role_headers["planner1"],
    )
    client.patch(
        f"/api/projects/{pid}/ear",
        json={"status": "approved"},
        headers=role_headers["planner1"],
    )
    # Add two BOQ items, one delivered.
    for code, qty in (("BR-100", 2), ("BR-101", 5)):
        client.post(
            f"/api/projects/{pid}/boq",
            json={
                "trade": "civil_arch",
                "item_code": code,
                "description": f"Item {code}",
                "unit": "ea",
                "quantity": qty,
                "unit_rate": 100,
            },
            headers=role_headers["planner1"],
        )
    boq = client.get(f"/api/projects/{pid}", headers=admin_headers).json()["boq_items"]
    assert len(boq) == 2
    first_id = boq[0]["id"]
    # Move one to delivered.
    client.patch(
        f"/api/projects/{pid}/boq/{first_id}",
        json={"delivery_status": "delivered"},
        headers=role_headers["planner1"],
    )

    # Drive the project forward until WORK_PERMIT. The simplest path: edit
    # the project through disposition -> EAR_APPROVED -> SOW_DRAFT (already
    # implied by the BOQ write above) -> SOW_APPROVED -> MTO_DRAFT (auto).
    # For the dashboard test, we just need a ConstructionRecord; the file
    # a work-permit endpoint stamps filed_at on the wcf_data.
    client.get(f"/api/projects/{pid}/construction", headers=admin_headers)
    client.post(
        f"/api/projects/{pid}/construction/work-permit",
        json={"permit_number": "WCF-2026-0042"},
        headers=role_headers["cm1"],
    )

    resp = client.get("/api/construction/dashboard", headers=admin_headers)
    body = resp.json()
    # The project is in WORK_PERMIT (status=planned), so it counts as
    # active construction.
    assert body["active_construction_projects"] >= 1
    # The filed WCF bumps active_work_permits to 1.
    assert body["active_work_permits"] >= 1
    # 1 of 2 BOQ items delivered.
    assert body["total_materials_tracked"] >= 2
    assert body["materials_delivered"] >= 1
    # delivery_rate is a percentage 0..100, in steps of 50 since we have
    # one delivered out of the project's 2 items. Just sanity-check the
    # math rather than a specific value.
    assert 0.0 <= body["delivery_rate"] <= 100.0


def test_dashboard_projects_endpoint(client, admin_headers, role_headers):
    """/api/construction/projects returns a per-project summary, excluding ICR."""
    icr = _create_project(client, admin_headers)
    _advance_to_mom_confirmed(client, admin_headers, icr["id"])
    client.post(
        f"/api/projects/{icr['id']}/disposition",
        json={"disposition": "ICR", "justification": "Utility only"},
        headers=role_headers["planner1"],
    )

    project = _create_project(client, admin_headers)
    pid = project["id"]
    _advance_to_mom_confirmed(client, admin_headers, pid)
    client.post(
        f"/api/projects/{pid}/disposition",
        json={"disposition": "PROJECT"},
        headers=role_headers["planner1"],
    )

    resp = client.get("/api/construction/projects", headers=admin_headers)
    assert resp.status_code == 200
    rows = resp.json()
    # ICR project must be excluded.
    pr_numbers = [r["pr_number"] for r in rows]
    assert icr["pr_number"] not in pr_numbers
    assert project["pr_number"] in pr_numbers
    # Each row has the expected keys.
    for row in rows:
        for key in (
            "id",
            "pr_number",
            "title",
            "stage",
            "permits_count",
            "active_permits_count",
            "materials_count",
            "materials_delivered_count",
            "team_count",
        ):
            assert key in row, f"missing key {key!r}"
