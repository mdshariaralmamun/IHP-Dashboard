"""Source-tagged data points (§3 traceability engine) — CRUD + CONFIRM flow."""

import uuid


def _pr_number(prefix="PR") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _create_project(client, headers):
    resp = client.post(
        "/api/projects",
        json={"pr_number": _pr_number(), "title": "Nanofabricator Lite install"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _point_payload(**overrides):
    payload = {
        "category": "utility",
        "field_key": f"utility.{uuid.uuid4().hex[:6]}.voltage",
        "label": "Voltage",
        "value": "208-240 VAC",
        "unit": "VAC",
        "source_tag": "TBC",
    }
    payload.update(overrides)
    return payload


def _create_point(client, headers, project_id, **overrides):
    resp = client.post(
        f"/api/projects/{project_id}/data-points",
        json=_point_payload(**overrides),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _audit_actions(client, headers, project_id):
    resp = client.get(f"/api/projects/{project_id}/audit", headers=headers)
    assert resp.status_code == 200, resp.text
    return [entry["action"] for entry in resp.json()]


def test_planner_creates_and_lists_points(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    planner = role_headers["planner1"]

    first = _create_point(client, planner, project["id"])
    assert first["source_tag"] == "TBC"
    assert first["created_by"] == "planner1"
    assert first["confirmed_by"] is None

    second = _create_point(
        client,
        planner,
        project["id"],
        field_key="utility.power.voltage",
        source_tag="DOC",
        source_file="ATLANT3D_Specs.pdf",
        source_location="p. 12",
    )
    assert second["source_tag"] == "DOC"
    assert second["source_file"] == "ATLANT3D_Specs.pdf"

    resp = client.get(f"/api/projects/{project['id']}/data-points", headers=planner)
    assert resp.status_code == 200
    listed = resp.json()
    assert {p["field_key"] for p in listed} == {first["field_key"], second["field_key"]}


def test_create_rejects_invalid_tag(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    resp = client.post(
        f"/api/projects/{project['id']}/data-points",
        json=_point_payload(source_tag="GUESS"),
        headers=role_headers["planner1"],
    )
    assert resp.status_code == 422


def test_doc_tag_requires_source_file(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    resp = client.post(
        f"/api/projects/{project['id']}/data-points",
        json=_point_payload(source_tag="DOC"),
        headers=role_headers["planner1"],
    )
    assert resp.status_code == 422


def test_team_member_cannot_create(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    resp = client.post(
        f"/api/projects/{project['id']}/data-points",
        json=_point_payload(),
        headers=role_headers["member1"],
    )
    assert resp.status_code == 403


def test_confirm_stamps_planner_and_audits(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    planner = role_headers["planner1"]
    point = _create_point(client, planner, project["id"])

    # Non-planner cannot confirm (data.confirm is planning-only).
    resp = client.post(
        f"/api/projects/{project['id']}/data-points/{point['id']}/confirm",
        headers=role_headers["trader1"],
    )
    assert resp.status_code == 403

    resp = client.post(
        f"/api/projects/{project['id']}/data-points/{point['id']}/confirm",
        headers=planner,
    )
    assert resp.status_code == 200, resp.text
    confirmed = resp.json()
    assert confirmed["source_tag"] == "PLANNER"
    assert confirmed["confirmed_by"] == "planner1"
    assert confirmed["confirmed_at"] is not None

    assert "datapoint:confirm" in _audit_actions(client, planner, project["id"])


def test_confirm_twice_conflicts(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    planner = role_headers["planner1"]
    point = _create_point(client, planner, project["id"])

    first = client.post(
        f"/api/projects/{project['id']}/data-points/{point['id']}/confirm",
        headers=planner,
    )
    assert first.status_code == 200
    second = client.post(
        f"/api/projects/{project['id']}/data-points/{point['id']}/confirm",
        headers=planner,
    )
    assert second.status_code == 409


def test_confirm_rejects_non_pending_tag(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    planner = role_headers["planner1"]
    point = _create_point(
        client,
        planner,
        project["id"],
        source_tag="DOC",
        source_file="ATLANT3D_Specs.pdf",
    )

    resp = client.post(
        f"/api/projects/{project['id']}/data-points/{point['id']}/confirm",
        headers=planner,
    )
    assert resp.status_code == 409


def test_editing_value_reverts_to_pending(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    planner = role_headers["planner1"]
    point = _create_point(client, planner, project["id"])

    confirmed = client.post(
        f"/api/projects/{project['id']}/data-points/{point['id']}/confirm",
        headers=planner,
    ).json()
    assert confirmed["source_tag"] == "PLANNER"

    resp = client.patch(
        f"/api/projects/{project['id']}/data-points/{point['id']}",
        json={"value": "220 VAC"},
        headers=planner,
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["value"] == "220 VAC"
    assert updated["source_tag"] == "TBC"
    assert updated["confirmed_by"] is None
    assert updated["confirmed_at"] is None


def test_filter_by_source_tag(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    planner = role_headers["planner1"]
    _create_point(client, planner, project["id"])
    _create_point(
        client,
        planner,
        project["id"],
        source_tag="DOC",
        source_file="Vendor_Quote.pdf",
    )

    resp = client.get(
        f"/api/projects/{project['id']}/data-points?source_tag=DOC", headers=planner
    )
    assert resp.status_code == 200
    listed = resp.json()
    assert len(listed) == 1
    assert listed[0]["source_tag"] == "DOC"

    resp = client.get(
        f"/api/projects/{project['id']}/data-points?source_tag=NOPE", headers=planner
    )
    assert resp.status_code == 422


def test_points_are_project_scoped(client, admin_headers, role_headers):
    project_a = _create_project(client, admin_headers)
    project_b = _create_project(client, admin_headers)
    planner = role_headers["planner1"]
    point = _create_point(client, planner, project_a["id"])

    resp = client.get(f"/api/projects/{project_b['id']}/data-points", headers=planner)
    assert resp.status_code == 200
    assert resp.json() == []

    # Cross-project access to the point id is a 404, not a leak.
    resp = client.patch(
        f"/api/projects/{project_b['id']}/data-points/{point['id']}",
        json={"value": "hijack"},
        headers=planner,
    )
    assert resp.status_code == 404


def test_delete_point_audits(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    planner = role_headers["planner1"]
    point = _create_point(client, planner, project["id"])

    resp = client.delete(
        f"/api/projects/{project['id']}/data-points/{point['id']}",
        headers=planner,
    )
    assert resp.status_code == 204

    resp = client.get(f"/api/projects/{project['id']}/data-points", headers=planner)
    assert resp.json() == []

    assert "datapoint:delete" in _audit_actions(client, planner, project["id"])
