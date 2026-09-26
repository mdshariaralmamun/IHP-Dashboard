"""RBAC matrix: every role x privileged endpoint, plus admin success paths."""

import uuid

import pytest

from conftest import ROLE_USERS, headers_for

NON_ADMIN_USERNAMES = [u[0] for u in ROLE_USERS]


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def rbac_project(client, admin_headers):
    """A project with a generated MOM, so every privileged endpoint is reachable."""
    resp = client.post(
        "/api/projects",
        json={"pr_number": _unique("PR-RBAC"), "title": "RBAC probe"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    project = resp.json()
    resp = client.post(
        f"/api/projects/{project['id']}/mom/generate", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    return project


@pytest.mark.parametrize("username", NON_ADMIN_USERNAMES)
def test_non_admin_forbidden_everywhere(client, role_headers, rbac_project, username):
    headers = role_headers[username]
    pid = rbac_project["id"]

    resp = client.post(
        "/api/projects",
        json={"pr_number": _unique("PR-X"), "title": "nope"},
        headers=headers,
    )
    assert resp.status_code == 403, username

    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files=[("files", ("x.txt", b"x", "text/plain"))],
        headers=headers,
    )
    assert resp.status_code == 403, username

    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=headers)
    assert resp.status_code == 403, username

    resp = client.post(
        f"/api/projects/{pid}/mom/status", json={"status": "sent"}, headers=headers
    )
    assert resp.status_code == 403, username

    resp = client.post(
        "/api/admin/users",
        json={
            "username": _unique("user"),
            "full_name": "Nope",
            "email": "nope@example.com",
            "password": "x",
            "role": "team_member",
        },
        headers=headers,
    )
    assert resp.status_code == 403, username

    resp = client.get("/api/admin/users", headers=headers)
    assert resp.status_code == 403, username


@pytest.mark.parametrize("username", NON_ADMIN_USERNAMES)
def test_non_admin_read_endpoints_allowed(client, role_headers, rbac_project, username):
    headers = role_headers[username]
    pid = rbac_project["id"]
    assert client.get("/api/projects", headers=headers).status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=headers).status_code == 200
    assert client.get(f"/api/projects/{pid}/audit", headers=headers).status_code == 200
    assert (
        client.get(
            f"/api/projects/{pid}/mom/download", params={"fmt": "docx"}, headers=headers
        ).status_code
        == 200
    )


def test_unauthenticated_write_is_401(client, rbac_project):
    resp = client.post(
        "/api/projects", json={"pr_number": _unique("PR-U"), "title": "anon"}
    )
    assert resp.status_code == 401


def test_admin_can_create_users(client, admin_headers):
    username = _unique("newuser")
    resp = client.post(
        "/api/admin/users",
        json={
            "username": username,
            "full_name": "New User",
            "email": "new@example.com",
            "password": "secret123",
            "role": "trade",
            "trade": "hvac",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == username
    assert body["role"] == "trade"
    assert body["trade"] == "hvac"
    assert "password" not in body and "hashed_password" not in body

    # Duplicate username -> 409
    resp = client.post(
        "/api/admin/users",
        json={
            "username": username,
            "full_name": "Dup",
            "email": "dup@example.com",
            "password": "secret123",
            "role": "team_member",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 409

    # New user can log in.
    resp = client.post(
        "/api/auth/login", data={"username": username, "password": "secret123"}
    )
    assert resp.status_code == 200


def test_admin_user_list_contains_seed_roles(client, admin_headers):
    resp = client.get("/api/admin/users", headers=admin_headers)
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()}
    assert {"admin", "trader1", "planner1", "cm1", "member1"} <= usernames


def test_admin_full_write_path(client, admin_headers):
    """Admin succeeds on: create project, upload, generate MOM, mark sent."""
    resp = client.post(
        "/api/projects",
        json={"pr_number": _unique("PR-ADM"), "title": "Admin path"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    pid = resp.json()["id"]

    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files=[("files", ("a.txt", b"a", "text/plain"))],
        headers=admin_headers,
    )
    assert resp.status_code == 200

    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"

    resp = client.post(
        f"/api/projects/{pid}/mom/status",
        json={"status": "sent"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"


# ---------- custom per-user permissions ----------


def _create_user_with_permissions(client, admin_headers, role, permissions, **extra):
    payload = {
        "username": _unique("user"),
        "full_name": "Custom Perms",
        "email": "custom@example.com",
        "password": "secret123",
        "role": role,
        "permissions": permissions,
    }
    payload.update(extra)
    resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["permissions"] == sorted(permissions)
    return body


def test_custom_permissions_grant_exact_set(client, admin_headers):
    """team_member + ['projects.create']: can create, nothing else."""
    user = _create_user_with_permissions(
        client, admin_headers, "team_member", ["projects.create"]
    )
    headers = headers_for(client, user["username"], "secret123")

    resp = client.post(
        "/api/projects",
        json={"pr_number": _unique("PR-CUST"), "title": "Custom perms"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]

    # Granted exactly one capability: edit/delete/admin stay forbidden.
    resp = client.put(
        f"/api/projects/{pid}", json={"title": "nope"}, headers=headers
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: projects.edit"

    resp = client.delete(f"/api/projects/{pid}", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: projects.delete"

    assert client.get("/api/admin/users", headers=headers).status_code == 403


def test_explicit_empty_permissions_override_role_default(
    client, admin_headers, role_headers
):
    """A trade user with permissions=[] (explicit, not NULL) loses mom.agenda."""
    user = _create_user_with_permissions(
        client, admin_headers, "trade", [], trade="electrical"
    )
    headers = headers_for(client, user["username"], "secret123")

    resp = client.post(
        "/api/projects",
        json={"pr_number": _unique("PR-EMPTY"), "title": "Empty override"},
        headers=admin_headers,
    )
    pid = resp.json()["id"]
    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "X", "action": "", "etc": ""},
        headers=headers,
    )
    assert resp.status_code == 403
