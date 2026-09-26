"""Auth endpoint tests: login, /me, token validation."""


def test_health_no_auth(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_login_ok(client):
    resp = client.post(
        "/api/auth/login", data={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]


def test_login_bad_password(client):
    resp = client.post(
        "/api/auth/login", data={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code == 401


def test_login_unknown_user(client):
    resp = client.post(
        "/api/auth/login", data={"username": "ghost", "password": "whatever"}
    )
    assert resp.status_code == 401


def test_me(client, role_headers):
    resp = client.get("/api/auth/me", headers=role_headers["trader1"])
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "id": body["id"],
        "username": "trader1",
        "full_name": "Trade User",
        "email": "trader1@example.com",
        "role": "trade",
        "trade": "civil_arch",
        "title": "",
        "is_active": True,
        "permissions": ["ai.proposal.accept", "ear.input", "mom.agenda", "mto.manage"],
    }
    assert "password" not in body and "hashed_password" not in body


ALL_CAPS_SORTED = [
    "ai.proposal.accept",
    "attachments.delete",
    "attachments.upload",
    "boq.manage",
    "closeout.manage",
    "construction.manage",
    "data.confirm",
    "data.manage",
    "disposition.manage",
    "ear.input",
    "ear.manage",
    "icr.handoff",
    "mom.agenda",
    "mom.manage",
    "mto.manage",
    "procurement.manage",
    "projects.create",
    "projects.delete",
    "projects.edit",
    "sow.manage",
    "users.manage",
    "work_permit.manage",
]


def test_me_returns_effective_permissions(client, admin_headers, role_headers):
    resp = client.get("/api/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["permissions"] == ALL_CAPS_SORTED  # admin: every capability, sorted
    assert resp.json()["is_active"] is True

    resp = client.get("/api/auth/me", headers=role_headers["trader1"])
    assert resp.json()["permissions"] == [
        "ai.proposal.accept", "ear.input", "mom.agenda", "mto.manage",
    ]  # trade role default (per ROLE_DEFAULT_PERMISSIONS in rbac.py)

    resp = client.get("/api/auth/me", headers=role_headers["member1"])
    assert resp.json()["permissions"] == ["mom.agenda"]  # team_member role default (read-only MOM access)


def test_login_disabled_account_401(client, admin_headers):
    resp = client.post(
        "/api/admin/users",
        json={
            "username": "disabled.user",
            "full_name": "Disabled User",
            "email": "disabled@example.com",
            "password": "secret123",
            "role": "team_member",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    user_id = resp.json()["id"]

    # Active account logs in fine.
    resp = client.post(
        "/api/auth/login",
        data={"username": "disabled.user", "password": "secret123"},
    )
    assert resp.status_code == 200

    # Deactivate via the admin PUT endpoint, then login is refused.
    resp = client.put(
        f"/api/admin/users/{user_id}",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp = client.post(
        "/api/auth/login",
        data={"username": "disabled.user", "password": "secret123"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Account disabled"


def test_me_without_token_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_invalid_token_401(client):
    resp = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401


def test_login_each_seeded_role(client, role_headers):
    # role_headers fixture already performs a login per role; assert /me works.
    for username, expected_role in [
        ("trader1", "trade"),
        ("planner1", "planning"),
        ("cm1", "construction_manager"),
        ("member1", "team_member"),
    ]:
        resp = client.get("/api/auth/me", headers=role_headers[username])
        assert resp.status_code == 200
        assert resp.json()["role"] == expected_role
