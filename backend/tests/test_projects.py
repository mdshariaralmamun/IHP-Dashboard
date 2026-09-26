"""Project intake + attachments tests (admin paths and read paths)."""

import uuid


def _pr_number(prefix="PR") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _create_project(client, headers, pr_number=None, title="Lab modification"):
    payload = {
        "pr_number": pr_number or _pr_number(),
        "title": title,
        "description": "Modify bench layout",
        "location": "Building 4, Level 2",
        "pi_name": "Dr. Example",
        "pi_email": "pi@example.kaust.edu.sa",
        "funding_source": "PI grant",
    }
    resp = client.post("/api/projects", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_project_admin(client, admin_headers):
    body = _create_project(client, admin_headers)
    assert body["stage"] == "INTAKE"
    assert body["disposition"] is None
    assert body["attachments"] == []
    assert body["mom"] is None
    assert body["pi_email"] == "pi@example.kaust.edu.sa"


def test_create_project_duplicate_pr_409(client, admin_headers):
    pr = _pr_number()
    _create_project(client, admin_headers, pr_number=pr)
    resp = client.post(
        "/api/projects",
        json={"pr_number": pr, "title": "Duplicate"},
        headers=admin_headers,
    )
    assert resp.status_code == 409


def test_list_and_get_project_any_role(client, admin_headers, role_headers):
    created = _create_project(client, admin_headers)

    resp = client.get("/api/projects", headers=role_headers["member1"])
    assert resp.status_code == 200
    listing = resp.json()
    match = [p for p in listing if p["id"] == created["id"]]
    assert len(match) == 1
    item = match[0]
    for field in (
        "id",
        "pr_number",
        "title",
        "pi_name",
        "location",
        "funding_source",
        "stage",
        "disposition",
        "created_at",
    ):
        assert field in item

    resp = client.get(f"/api/projects/{created['id']}", headers=role_headers["planner1"])
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["pr_number"] == created["pr_number"]
    assert detail["description"] == "Modify bench layout"
    assert detail["attachments"] == []
    assert detail["mom"] is None


def test_get_unknown_project_404(client, admin_headers):
    assert client.get("/api/projects/999999", headers=admin_headers).status_code == 404


def test_upload_and_download_attachments(client, admin_headers, data_dir):
    project = _create_project(client, admin_headers)
    url = f"/api/projects/{project['id']}/attachments"

    resp = client.post(
        url,
        files=[
            ("files", ("scope.txt", b"scope contents", "text/plain")),
            ("files", ("photos.txt", b"photo list", "text/plain")),
        ],
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert len(created) == 2
    by_name = {a["filename"]: a for a in created}
    assert by_name["scope.txt"]["version"] == 1
    assert by_name["scope.txt"]["stage"] == "INTAKE"  # defaults to current stage
    assert by_name["scope.txt"]["size_bytes"] == len(b"scope contents")

    # Versioned on disk under {DATA_DIR}/projects/{pr}/{stage}/v{n}_{filename}
    stored = (
        data_dir / "projects" / project["pr_number"] / "INTAKE" / "v1_scope.txt"
    )
    assert stored.exists()
    assert stored.read_bytes() == b"scope contents"

    # Re-uploading the same filename bumps the version.
    resp = client.post(
        url,
        files=[("files", ("scope.txt", b"scope v2", "text/plain"))],
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()[0]["version"] == 2

    # Download returns original bytes with original filename.
    att_id = by_name["scope.txt"]["id"]
    resp = client.get(
        f"/api/projects/{project['id']}/attachments/{att_id}/download",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.content == b"scope contents"
    assert "scope.txt" in resp.headers.get("content-disposition", "")


def test_download_unknown_attachment_404(client, admin_headers):
    project = _create_project(client, admin_headers)
    resp = client.get(
        f"/api/projects/{project['id']}/attachments/999999/download",
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_audit_trail_records_actions(client, admin_headers):
    project = _create_project(client, admin_headers)
    client.post(
        f"/api/projects/{project['id']}/attachments",
        files=[("files", ("note.txt", b"hi", "text/plain"))],
        headers=admin_headers,
    )
    resp = client.get(f"/api/projects/{project['id']}/audit", headers=admin_headers)
    assert resp.status_code == 200
    trail = resp.json()
    assert [e["action"] for e in trail] == ["project:create", "attachment:upload"]
    assert all(e["user"] == "admin" for e in trail)
    assert trail[0]["detail"]["pr_number"] == project["pr_number"]
    assert trail[1]["detail"]["filename"] == "note.txt"


# ---------- edit / delete ----------


def test_update_project_fields_and_audit(client, admin_headers):
    project = _create_project(client, admin_headers)
    pid = project["id"]

    resp = client.put(
        f"/api/projects/{pid}",
        json={"title": "Bench layout v2", "location": "Building 5"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Bench layout v2"
    assert body["location"] == "Building 5"
    assert body["description"] == "Modify bench layout"  # untouched
    assert body["pi_name"] == "Dr. Example"  # untouched

    trail = client.get(f"/api/projects/{pid}/audit", headers=admin_headers).json()
    edit = [e for e in trail if e["action"] == "project:edit"]
    assert len(edit) == 1
    assert sorted(edit[0]["detail"]["fields"]) == ["location", "title"]


def test_update_project_requires_capability(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    resp = client.put(
        f"/api/projects/{project['id']}",
        json={"title": "nope"},
        headers=role_headers["member1"],
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: projects.edit"


def test_delete_project_removes_rows_and_files(client, admin_headers, data_dir):
    project = _create_project(client, admin_headers)
    pid = project["id"]
    pr = project["pr_number"]

    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files=[("files", ("scope.txt", b"scope", "text/plain"))],
        headers=admin_headers,
    )
    assert resp.status_code == 200
    stored = data_dir / "projects" / pr / "INTAKE" / "v1_scope.txt"
    assert stored.exists()

    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200, resp.text

    resp = client.delete(f"/api/projects/{pid}", headers=admin_headers)
    assert resp.status_code == 204

    assert client.get(f"/api/projects/{pid}", headers=admin_headers).status_code == 404
    assert not stored.exists()  # attachment file removed from disk


def test_delete_project_requires_capability(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    resp = client.delete(
        f"/api/projects/{project['id']}", headers=role_headers["member1"]
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: projects.delete"


def test_delete_attachment_removes_row_and_file(client, admin_headers, data_dir):
    project = _create_project(client, admin_headers)
    pid = project["id"]
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files=[("files", ("note.txt", b"hi", "text/plain"))],
        headers=admin_headers,
    )
    assert resp.status_code == 200
    att_id = resp.json()[0]["id"]
    stored = data_dir / "projects" / project["pr_number"] / "INTAKE" / "v1_note.txt"
    assert stored.exists()

    resp = client.delete(
        f"/api/projects/{pid}/attachments/{att_id}", headers=admin_headers
    )
    assert resp.status_code == 204
    assert not stored.exists()

    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["attachments"] == []

    trail = client.get(f"/api/projects/{pid}/audit", headers=admin_headers).json()
    delete = [e for e in trail if e["action"] == "attachment:delete"]
    assert len(delete) == 1
    assert delete[0]["detail"]["filename"] == "note.txt"


def test_delete_attachment_requires_capability(client, admin_headers, role_headers):
    project = _create_project(client, admin_headers)
    pid = project["id"]
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files=[("files", ("note.txt", b"hi", "text/plain"))],
        headers=admin_headers,
    )
    att_id = resp.json()[0]["id"]
    resp = client.delete(
        f"/api/projects/{pid}/attachments/{att_id}", headers=role_headers["member1"]
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: attachments.delete"


def test_public_track_by_token(client, admin_headers):
    """The public tracking link: /api/projects/track/{token} needs no auth."""
    project = _create_project(client, admin_headers)
    token = project["tracking_token"]
    assert token  # created via the API -> always has one

    resp = client.get(f"/api/projects/track/{token}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pr_number"] == project["pr_number"]
    assert body["title"] == project["title"]
    assert body["stage"] == "INTAKE"

    # Unknown token -> 404, no auth needed to learn that
    resp = client.get("/api/projects/track/no-such-token")
    assert resp.status_code == 404
