"""MOM agenda item endpoint: trade users add items for their own trade only."""

from conftest import headers_for


def _project_with_mom(client, admin_headers, pr):
    resp = client.post(
        "/api/projects",
        json={"pr_number": pr, "title": "Agenda test project"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    return pid


def test_trade_user_adds_item_with_forced_trade_label(client, admin_headers, role_headers):
    pid = _project_with_mom(client, admin_headers, "PR-71001")
    resp = client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "Relocate existing partition wall", "action": "Info", "etc": "-",
              "trade": "Electrical"},  # ignored: server forces the user's own trade
        headers=role_headers["trader1"],  # civil_arch
    )
    assert resp.status_code == 200, resp.text
    agenda = resp.json()["details"]["agenda"]
    assert agenda[-1]["scope"] == "Relocate existing partition wall"
    assert agenda[-1]["trade"] == "Civil/Architectural"

    audit = client.get(f"/api/projects/{pid}/audit", headers=admin_headers).json()
    assert any(entry["action"] == "mom:agenda_add" for entry in audit)


def test_admin_adds_item_with_any_trade(client, admin_headers):
    pid = _project_with_mom(client, admin_headers, "PR-71002")
    resp = client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "Provide VESDA coverage", "action": "Info", "etc": "", "trade": "Low Current"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["details"]["agenda"][-1]["trade"] == "Low Current"


def test_non_trade_roles_cannot_add(client, admin_headers, role_headers):
    pid = _project_with_mom(client, admin_headers, "PR-71003")
    body = {"scope": "X", "action": "", "etc": ""}
    assert client.post(
        f"/api/projects/{pid}/mom/agenda", json=body, headers=role_headers["planner1"]
    ).status_code == 403
    assert client.post(
        f"/api/projects/{pid}/mom/agenda", json=body, headers=role_headers["member1"]
    ).status_code == 403


def test_empty_scope_rejected(client, admin_headers, role_headers):
    pid = _project_with_mom(client, admin_headers, "PR-71004")
    resp = client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "   ", "action": "", "etc": ""},
        headers=role_headers["trader1"],
    )
    assert resp.status_code == 422


def test_agenda_add_requires_existing_mom(client, admin_headers, role_headers):
    resp = client.post(
        "/api/projects",
        json={"pr_number": "PR-71005", "title": "No MOM yet"},
        headers=admin_headers,
    )
    pid = resp.json()["id"]
    resp = client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "X", "action": "", "etc": ""},
        headers=role_headers["trader1"],
    )
    assert resp.status_code == 404


# ---------- edit / delete ownership ----------

def _seed_two_trade_items(client, admin_headers, role_headers, pr):
    """Project + MOM with one civil_arch item (trader1) and one admin item."""
    pid = _project_with_mom(client, admin_headers, pr)
    client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "Civil scope item", "action": "Info", "etc": ""},
        headers=role_headers["trader1"],
    )
    client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "Admin scope item", "action": "Info", "etc": "", "trade": "Electrical"},
        headers=admin_headers,
    )
    return pid


def test_trade_user_edits_and_deletes_own_item(client, admin_headers, role_headers):
    pid = _seed_two_trade_items(client, admin_headers, role_headers, "PR-71006")
    # Index 0 = civil_arch item (trader1's own trade)
    resp = client.put(
        f"/api/projects/{pid}/mom/agenda/0",
        json={"scope": "Civil scope item (revised)", "action": "Info", "etc": "2026-09-15"},
        headers=role_headers["trader1"],
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["details"]["agenda"][0]
    assert item["scope"] == "Civil scope item (revised)"
    assert item["trade"] == "Civil/Architectural"  # trade preserved
    assert item["added_by_name"] == "Trade User"  # contributor preserved

    resp = client.delete(f"/api/projects/{pid}/mom/agenda/0", headers=role_headers["trader1"])
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["details"]["agenda"]) == 1


def test_trade_user_cannot_touch_other_trades_items(client, admin_headers, role_headers):
    pid = _seed_two_trade_items(client, admin_headers, role_headers, "PR-71007")
    # Index 1 = admin's Electrical item — off-limits for trader1 (civil_arch)
    resp = client.put(
        f"/api/projects/{pid}/mom/agenda/1",
        json={"scope": "Hijacked", "action": "", "etc": ""},
        headers=role_headers["trader1"],
    )
    assert resp.status_code == 403
    resp = client.delete(f"/api/projects/{pid}/mom/agenda/1", headers=role_headers["trader1"])
    assert resp.status_code == 403


def test_admin_edits_any_item_including_trade(client, admin_headers, role_headers):
    pid = _seed_two_trade_items(client, admin_headers, role_headers, "PR-71008")
    resp = client.put(
        f"/api/projects/{pid}/mom/agenda/0",
        json={"scope": "Admin-rewritten", "action": "Info", "etc": "", "trade": "HVAC"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["details"]["agenda"][0]
    assert item["scope"] == "Admin-rewritten"
    assert item["trade"] == "HVAC"


def test_edit_invalid_index_404(client, admin_headers, role_headers):
    pid = _seed_two_trade_items(client, admin_headers, role_headers, "PR-71009")
    resp = client.put(
        f"/api/projects/{pid}/mom/agenda/9",
        json={"scope": "X", "action": "", "etc": ""},
        headers=admin_headers,
    )
    assert resp.status_code == 404
    resp = client.delete(f"/api/projects/{pid}/mom/agenda/9", headers=admin_headers)
    assert resp.status_code == 404


def test_contributor_mark_in_document(client, admin_headers, role_headers, data_dir):
    from docx import Document

    pid = _seed_two_trade_items(client, admin_headers, role_headers, "PR-71010")
    resp = client.post(f"/api/projects/{pid}/mom/generate", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    path = data_dir / "projects" / "PR-71010" / "mom" / "MOM_PR-71010_v2.docx"
    text = "\n".join(
        cell.text
        for table in Document(str(path)).tables
        for row in table.rows
        for cell in row.cells
    )
    assert "By: Trade User" in text  # trader1's full_name on their item


def test_user_create_with_job_title(client, admin_headers):
    resp = client.post(
        "/api/admin/users",
        json={
            "username": "saju.thomas",
            "full_name": "Saju Thomas",
            "email": "saju.thomas@kaust.edu.sa",
            "password": "pass12345",
            "role": "trade",
            "trade": "electrical",
            "title": "Lab Equipment Technician",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Lab Equipment Technician"


# ---------- mom.manage capability ----------


def test_mom_manage_user_manages_any_agenda_item(client, admin_headers):
    """A planning-role user granted ['mom.manage'] can POST any trade and
    PUT/DELETE any item — same reach as an admin."""
    resp = client.post(
        "/api/admin/users",
        json={
            "username": "planner2",
            "full_name": "Mom Manager",
            "email": "planner2@example.com",
            "password": "secret123",
            "role": "planning",
            "permissions": ["mom.manage"],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    manager_headers = headers_for(client, "planner2", "secret123")

    pid = _project_with_mom(client, admin_headers, "PR-71011")
    # POST with an arbitrary trade (payload trade is honored).
    resp = client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "Manager item", "action": "Info", "etc": "", "trade": "HVAC"},
        headers=manager_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["details"]["agenda"][-1]["trade"] == "HVAC"

    # A civil_arch item from a trade user: manager can still edit + delete it.
    resp = client.post(
        f"/api/projects/{pid}/mom/agenda",
        json={"scope": "Civil item", "action": "", "etc": ""},
        headers=headers_for(client, "trader1"),
    )
    assert resp.status_code == 200, resp.text

    resp = client.put(
        f"/api/projects/{pid}/mom/agenda/1",
        json={"scope": "Civil item (managed)", "action": "Info", "etc": "", "trade": "Electrical"},
        headers=manager_headers,
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["details"]["agenda"][1]
    assert item["scope"] == "Civil item (managed)"
    assert item["trade"] == "Electrical"  # mom.manage may change the trade

    resp = client.delete(f"/api/projects/{pid}/mom/agenda/1", headers=manager_headers)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["details"]["agenda"]) == 1
