"""Custom (free-text) roles and trades: normalization, defaults, enforcement."""

from app.api.mom import trade_agenda_label
from tests.conftest import TEST_PASSWORD, login


def test_trade_agenda_label_fallback():
    assert trade_agenda_label("civil_arch") == "Civil/Architectural"
    assert trade_agenda_label("fire_alarm") == "Fire Alarm"
    assert trade_agenda_label("macc") == "MACC"
    assert trade_agenda_label("bms_controls") == "BMS Controls"


def _create_user(client, admin_headers, **overrides):
    payload = {
        "username": "custom.user",
        "full_name": "Custom User",
        "email": "",
        "password": TEST_PASSWORD,
        "role": "team_member",
    }
    payload.update(overrides)
    resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_custom_role_normalized_and_empty_defaults(client, admin_headers):
    user = _create_user(client, admin_headers, username="qa.eng", role="QA Engineer")
    assert user["role"] == "qa_engineer"
    assert user["permissions"] == []  # unknown role: no default capabilities

    headers = {"Authorization": f"Bearer {login(client, 'qa.eng', TEST_PASSWORD)}"}
    assert client.get("/api/projects", headers=headers).status_code == 200  # read-only
    assert client.post(
        "/api/projects", json={"pr_number": "PR-72001", "title": "X"}, headers=headers
    ).status_code == 403


def test_custom_role_with_checklist_permissions(client, admin_headers):
    user = _create_user(
        client,
        admin_headers,
        username="doc.controller",
        role="Document Controller",
        permissions=["projects.create", "projects.edit"],
    )
    assert user["role"] == "document_controller"
    assert sorted(user["permissions"]) == ["projects.create", "projects.edit"]

    headers = {"Authorization": f"Bearer {login(client, 'doc.controller', TEST_PASSWORD)}"}
    resp = client.post(
        "/api/projects",
        json={"pr_number": "PR-72002", "title": "Custom role PR"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    assert client.put(
        f"/api/projects/{pid}", json={"title": "Renamed"}, headers=headers
    ).status_code == 200
    assert client.delete(f"/api/projects/{pid}", headers=headers).status_code == 403


def test_custom_trade_agenda_flow(client, admin_headers):
    _create_user(
        client,
        admin_headers,
        username="fa.tech",
        role="trade",
        trade="Fire Alarm",
    )
    resp = client.post(
        "/api/projects",
        json={"pr_number": "PR-72003", "title": "Fire alarm PR"},
        headers=admin_headers,
    )
    pid = resp.json()["id"]
    client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)

    headers = {"Authorization": f"Bearer {login(client, 'fa.tech', TEST_PASSWORD)}"}
    resp = client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "Extend fire alarm coverage to the new lab", "action": "Info", "etc": ""},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    agenda = resp.json()["details"]["agenda"]
    assert agenda[-1]["trade"] == "Fire Alarm"  # title-cased custom trade

    # Own-trade edit works; a different trade's item is forbidden.
    assert client.put(
        f"/api/projects/{pid}/mom/agenda/0",
        json={"scope": "Extend fire alarm coverage (revised)", "action": "Info", "etc": ""},
        headers=headers,
    ).status_code == 200
    resp = client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "Electrical item", "action": "", "etc": "", "trade": "Electrical"},
        headers=admin_headers,
    )
    assert client.delete(f"/api/projects/{pid}/mom/agenda/1", headers=headers).status_code == 403
