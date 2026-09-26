"""Public read-only dashboard + the request-access / invite flow."""

import pytest

from app.api import public as public_api
from app.db import SessionLocal
from app.models import AccessRequest, User


@pytest.fixture(autouse=True)
def _clear_throttle():
    """The public form throttles per IP; keep tests independent."""
    public_api._hits.clear()
    yield
    public_api._hits.clear()


def _cleanup_requests(db) -> None:
    for row in db.query(AccessRequest).all():
        db.delete(row)
    db.commit()


def test_public_dashboard_is_aggregate_only(client):
    resp = client.get("/api/public/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["totals"]["projects"] >= 0
    assert isinstance(body["by_division"], dict)
    assert isinstance(body["by_stage"], dict)
    assert set(body["windows"]) >= {"overdue", "this_week", "on_hold", "high_risk"}
    assert any(r["value"] == "viewer" for r in body["requestable_roles"])
    # No project identifiers, people or documents leak to anonymous visitors.
    flat = resp.text.lower()
    for forbidden in ("pr_number", "pi_name", "location", "assigned_to", "ear_number"):
        assert forbidden not in flat, forbidden


def test_access_request_requires_valid_input(client):
    bad_email = client.post(
        "/api/public/access-request",
        json={"full_name": "Visitor One", "email": "not-an-email"},
    )
    assert bad_email.status_code == 400
    bad_role = client.post(
        "/api/public/access-request",
        json={"full_name": "Visitor One", "email": "v1@example.com", "requested_role": "admin"},
    )
    assert bad_role.status_code == 400
    short_name = client.post(
        "/api/public/access-request",
        json={"full_name": "V", "email": "v1@example.com"},
    )
    assert short_name.status_code == 422


def test_visitor_can_request_access_and_admin_sees_it(client, admin_headers):
    db = SessionLocal()
    try:
        _cleanup_requests(db)
    finally:
        db.close()

    resp = client.post(
        "/api/public/access-request",
        json={
            "full_name": "Noura Visitor",
            "email": "Noura.Visitor@Example.com",
            "phone": "+966500000000",
            "company": "KAUST FM",
            "requested_role": "viewer",
            "message": "I need to follow the construction dashboard.",
        },
        headers={"cf-connecting-ip": "203.0.113.10"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    reference = resp.json()["reference"]
    assert reference.startswith("REQ-")

    # A second submission refreshes the pending row instead of duplicating it.
    again = client.post(
        "/api/public/access-request",
        json={"full_name": "Noura Visitor", "email": "noura.visitor@example.com"},
        headers={"cf-connecting-ip": "203.0.113.10"},
    )
    assert again.status_code == 200
    db = SessionLocal()
    try:
        rows = db.query(AccessRequest).all()
        assert len(rows) == 1
        assert rows[0].email == "noura.visitor@example.com"
        assert rows[0].status == "pending"
    finally:
        db.close()

    # The inbox (admin only) lists it and reports the badge count.
    assert client.get("/api/admin/access-requests").status_code == 401
    inbox = client.get("/api/admin/access-requests", headers=admin_headers)
    assert inbox.status_code == 200, inbox.text
    body = inbox.json()
    assert body["pending"] >= 1
    item = next(i for i in body["items"] if i["email"] == "noura.visitor@example.com")
    assert item["requested_role"] == "viewer"
    assert item["invite_token"] is None

    notifications = client.get(
        "/api/admin/access-requests/notifications", headers=admin_headers
    ).json()
    assert notifications["pending_access_requests"] >= 1


def test_approve_creates_the_account_and_the_invite_link(client, admin_headers):
    db = SessionLocal()
    try:
        _cleanup_requests(db)
    finally:
        db.close()
    client.post(
        "/api/public/access-request",
        json={
            "full_name": "Omar Invitee",
            "email": "omar.invitee@example.com",
            "requested_role": "team_member",
        },
        headers={"cf-connecting-ip": "203.0.113.11"},
    )
    db = SessionLocal()
    try:
        row = db.query(AccessRequest).filter(
            AccessRequest.email == "omar.invitee@example.com"
        ).one()
        request_id = row.id
    finally:
        db.close()

    approved = client.post(
        f"/api/admin/access-requests/{request_id}/approve",
        json={"role": "viewer"},
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    payload = approved.json()
    token = payload["request"]["invite_token"]
    assert token and len(token) > 20
    username = payload["username"]

    # The invitee opens the link, sets a password and is logged straight in.
    info = client.get(f"/api/auth/invite/{token}")
    assert info.status_code == 200, info.text
    assert info.json()["email"] == "omar.invitee@example.com"
    assert info.json()["role"] == "viewer"

    short = client.post(f"/api/auth/invite/{token}", json={"password": "short"})
    assert short.status_code == 422  # min_length=8

    setpw = client.post(
        f"/api/auth/invite/{token}", json={"password": "InviteePass123"}
    )
    assert setpw.status_code == 200, setpw.text
    access = setpw.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["username"] == username
    assert me.json()["role"] == "viewer"

    # They can log in normally afterwards, and the link cannot be reused.
    login = client.post(
        "/api/auth/login",
        data={"username": username, "password": "InviteePass123"},
    )
    assert login.status_code == 200
    reuse = client.get(f"/api/auth/invite/{token}")
    assert reuse.status_code == 410

    # A viewer has no write capability.
    from app.core.rbac import effective_permissions

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one()
        assert effective_permissions(user) == set()
        row = db.query(AccessRequest).filter(AccessRequest.id == request_id).one()
        assert row.status == "approved" and row.user_id == user.id
        # tidy up the account created by this test
        row.user_id = None
        db.delete(user)
        db.delete(row)
        db.commit()
    finally:
        db.close()


def test_reject_and_reissue(client, admin_headers):
    db = SessionLocal()
    try:
        _cleanup_requests(db)
    finally:
        db.close()
    client.post(
        "/api/public/access-request",
        json={"full_name": "Rejected Person", "email": "rejected@example.com"},
        headers={"cf-connecting-ip": "203.0.113.12"},
    )
    db = SessionLocal()
    try:
        request_id = db.query(AccessRequest).filter(
            AccessRequest.email == "rejected@example.com"
        ).one().id
    finally:
        db.close()

    rejected = client.post(
        f"/api/admin/access-requests/{request_id}/reject",
        json={"note": "Not part of the project team"},
        headers=admin_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["request"]["status"] == "rejected"
    assert rejected.json()["request"]["decision_note"] == "Not part of the project team"

    # Re-issuing before approval is a user error, not a crash.
    assert client.post(
        f"/api/admin/access-requests/{request_id}/reissue", headers=admin_headers
    ).status_code == 400

    # Approving later works and issues a fresh link.
    approved = client.post(
        f"/api/admin/access-requests/{request_id}/approve", headers=admin_headers
    )
    assert approved.status_code == 200
    first = approved.json()["request"]["invite_token"]
    reissued = client.post(
        f"/api/admin/access-requests/{request_id}/reissue", headers=admin_headers
    )
    assert reissued.status_code == 200
    assert reissued.json()["request"]["invite_token"] != first
    assert client.get(f"/api/auth/invite/{first}").status_code == 404


def test_public_form_is_rate_limited(client):
    for i in range(public_api._RATE_LIMIT):
        resp = client.post(
            "/api/public/access-request",
            json={"full_name": f"Visitor {i}", "email": f"visitor{i}@example.com"},
            headers={"cf-connecting-ip": "198.51.100.7"},
        )
        assert resp.status_code == 200, resp.text
    blocked = client.post(
        "/api/public/access-request",
        json={"full_name": "Visitor X", "email": "visitorx@example.com"},
        headers={"cf-connecting-ip": "198.51.100.7"},
    )
    assert blocked.status_code == 429
