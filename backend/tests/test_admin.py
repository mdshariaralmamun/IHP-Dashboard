"""Admin user CRUD: PUT /admin/users/{id} and DELETE /admin/users/{id}."""

import uuid

from conftest import headers_for


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_user(client, admin_headers, **overrides):
    payload = {
        "username": _unique("user"),
        "full_name": "Test User",
        "email": "test@example.com",
        "password": "secret123",
        "role": "team_member",
    }
    payload.update(overrides)
    resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- PUT ----------


def test_update_user_changes_only_provided_fields(client, admin_headers):
    user = _create_user(
        client, admin_headers, role="trade", trade="hvac", full_name="Before"
    )
    resp = client.put(
        f"/api/admin/users/{user['id']}",
        json={"full_name": "After", "title": "Engineer", "trade": "plumbing"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "After"
    assert body["title"] == "Engineer"
    assert body["trade"] == "plumbing"
    assert body["email"] == "test@example.com"  # untouched
    assert body["role"] == "trade"  # untouched


def test_update_role_away_from_trade_clears_trade_unless_provided(
    client, admin_headers
):
    user = _create_user(client, admin_headers, role="trade", trade="hvac")

    # Role change without an explicit trade -> trade cleared.
    resp = client.put(
        f"/api/admin/users/{user['id']}",
        json={"role": "planning"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "planning"
    assert resp.json()["trade"] is None

    # Role change with an explicit trade -> trade kept as provided.
    resp = client.put(
        f"/api/admin/users/{user['id']}",
        json={"role": "team_member", "trade": "electrical"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["trade"] == "electrical"


def test_update_user_password_reset_then_login(client, admin_headers):
    user = _create_user(client, admin_headers)
    resp = client.put(
        f"/api/admin/users/{user['id']}",
        json={"password": "newpass456"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        "/api/auth/login",
        data={"username": user["username"], "password": "newpass456"},
    )
    assert resp.status_code == 200
    resp = client.post(
        "/api/auth/login",
        data={"username": user["username"], "password": "secret123"},
    )
    assert resp.status_code == 401


def test_update_unknown_user_404(client, admin_headers):
    resp = client.put(
        "/api/admin/users/999999", json={"full_name": "Ghost"}, headers=admin_headers
    )
    assert resp.status_code == 404


# ---------- DELETE ----------


def test_delete_self_400(client, admin_headers):
    resp = client.get("/api/auth/me", headers=admin_headers)
    admin_id = resp.json()["id"]
    resp = client.delete(f"/api/admin/users/{admin_id}", headers=admin_headers)
    assert resp.status_code == 400


def test_delete_last_active_admin_409(client, admin_headers):
    """A non-admin manager (users.manage via custom permissions) cannot delete
    the only active admin account."""
    manager = _create_user(
        client, admin_headers, permissions=["users.manage"]
    )
    manager_headers = headers_for(client, manager["username"], "secret123")

    resp = client.get("/api/auth/me", headers=admin_headers)
    admin_id = resp.json()["id"]
    resp = client.delete(f"/api/admin/users/{admin_id}", headers=manager_headers)
    assert resp.status_code == 409


def test_delete_user_with_records_409(client, admin_headers, role_headers):
    """trader1 has audit rows after adding an agenda item -> cannot hard-delete."""
    resp = client.post(
        "/api/projects",
        json={"pr_number": _unique("PR-DEL"), "title": "Delete guard"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "Guard probe", "action": "", "etc": ""},
        headers=role_headers["trader1"],
    )
    assert resp.status_code == 200, resp.text

    resp = client.get("/api/admin/users", headers=admin_headers)
    trader_id = next(u["id"] for u in resp.json() if u["username"] == "trader1")
    resp = client.delete(f"/api/admin/users/{trader_id}", headers=admin_headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "User has records; deactivate instead"


def test_delete_clean_user_204_then_login_401(client, admin_headers):
    user = _create_user(client, admin_headers)
    resp = client.delete(f"/api/admin/users/{user['id']}", headers=admin_headers)
    assert resp.status_code == 204

    resp = client.get("/api/admin/users", headers=admin_headers)
    assert user["username"] not in {u["username"] for u in resp.json()}

    resp = client.post(
        "/api/auth/login",
        data={"username": user["username"], "password": "secret123"},
    )
    assert resp.status_code == 401
