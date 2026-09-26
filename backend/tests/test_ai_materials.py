"""AI-coordinated materials proposal tests (services/ai_materials.py + /mto endpoints).

The AI provider is monkeypatched in every test — offline for the keyword
fallback path, a stubbed chat for the AI-coordination path — so results are
hermetic regardless of whether Ollama runs on this machine.
"""

import itertools

import pytest
from sqlalchemy import select

from app.ai import provider
from app.db import SessionLocal
from app.models import AiMaterialsProposal, MasterPricing, Project
from app.services import ai_materials

_pr_seq = itertools.count()

MASTER_ROWS = [
    # (item_code, description, trade, unit, rate)
    ("T-101", "Supply 1-inch EMT conduit.( ITCC/Panasonic)", "electrical", "Lm", 10.94),
    ("T-102", "Supply 10x10 EMT junction box with cover", "electrical", "Pcs", 9.12),
    ("T-103", "PPR Tee ,DN 25mm,GF", "plumbing", "ea", 14.25),
    ("T-104", "Supply SS duct volume damper 100 mm", "hvac", "Nos", 273.60),
]


@pytest.fixture(autouse=True)
def _cleanup():
    """Shared session DB — remove everything this file creates."""
    _created_project_ids: list[int] = []

    db = SessionLocal()
    try:
        for row in db.scalars(select(MasterPricing).where(
                MasterPricing.item_code.like("T-1%"))).all():
            db.delete(row)
        db.commit()
    finally:
        db.close()

    yield _created_project_ids

    db = SessionLocal()
    try:
        for pid in _created_project_ids:
            for p in db.scalars(select(AiMaterialsProposal).where(
                    AiMaterialsProposal.project_id == pid)).all():
                db.delete(p)
            proj = db.get(Project, pid)
            if proj is not None:
                db.delete(proj)  # cascades boq items
        for row in db.scalars(select(MasterPricing).where(
                MasterPricing.item_code.like("T-1%"))).all():
            db.delete(row)
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def master_rows():
    db = SessionLocal()
    try:
        for code, desc, trade, unit, rate in MASTER_ROWS:
            db.add(MasterPricing(item_code=code, description=desc, trade=trade,
                                 unit=unit, base_unit_rate=rate, currency="SAR",
                                 notes="test-ai-mat:"))
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def project(client, admin_headers, _cleanup):
    resp = client.post("/api/projects", headers=admin_headers, json={
        "pr_number": f"PR-9100-{next(_pr_seq)}",
        "title": "Relocation of 3-phase sockets",
        "description": "Relocate three-phase socket outlets; supply 1-inch EMT "
                       "conduit and junction boxes; testing and commissioning.",
        "location": "Building 6, Level-1, Greenhouse",
    })
    assert resp.status_code in (200, 201), resp.text
    _cleanup.append(resp.json()["id"])
    return resp.json()["id"]


def _draft(client, headers, pid, **body):
    return client.post(f"/api/mto/project/{pid}/materials-proposal",
                       headers=headers, json=body)


class TestKeywordMode:
    def test_offline_provider_drafts_trade_wise(self, client, admin_headers,
                                                project, master_rows, monkeypatch):
        monkeypatch.setattr(provider, "available", lambda: (False, "tests"))
        resp = _draft(client, admin_headers, project, stage_target="EAR")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["mode"] == "keyword"
        assert body["status"] == "draft"
        codes = [i["item_code"] for i in body["items"]]
        assert "T-101" in codes and "T-102" in codes   # electrical matched scope
        assert "T-103" not in codes and "T-104" not in codes  # other trades
        item = next(i for i in body["items"] if i["item_code"] == "T-101")
        assert item["origin"] == "keyword" and item["qty"] == 1.0
        subtotal = sum(i["qty"] * i["unit_rate"] for i in body["items"])
        assert body["subtotal_sar"] == round(subtotal, 2)
        assert body["vat_sar"] == round(subtotal * 0.15, 2)

    def test_trades_filter_restricts_candidates(self, client, admin_headers,
                                                project, master_rows, monkeypatch,
                                                _cleanup):
        # a plumbing-scope project: only plumbing master rows can match
        resp = client.post("/api/projects", headers=admin_headers, json={
            "pr_number": f"PR-9110-{next(_pr_seq)}",
            "title": "Chilled water line modification",
            "description": "Replace PPR tee fittings and ball valves on the "
                           "existing chilled water line.",
        })
        assert resp.status_code in (200, 201), resp.text
        pid = resp.json()["id"]
        _cleanup.append(pid)

        monkeypatch.setattr(provider, "available", lambda: (False, "tests"))
        resp = _draft(client, admin_headers, pid, trades=["plumbing"])
        assert resp.status_code == 201
        assert [i["trade"] for i in resp.json()["items"]] == ["plumbing"]

    def test_bad_stage_target_422(self, client, admin_headers, project):
        resp = _draft(client, admin_headers, project, stage_target="X")
        assert resp.status_code == 422

    def test_member_cannot_draft(self, client, role_headers, project):
        resp = _draft(client, role_headers["member1"], project)
        assert resp.status_code == 403


class TestAiMode:
    def test_stubbed_llm_coordinates_selection(self, client, admin_headers,
                                                project, master_rows, monkeypatch):
        monkeypatch.setattr(provider, "available", lambda: (True, None))
        monkeypatch.setattr(provider, "chat", lambda *a, **k: (
            '```json\n[{"item_code": "T-101", "qty": 20,'
            ' "reason": "20m relocation run"}]\n```'
        ))
        resp = _draft(client, admin_headers, project, stage_target="MTO")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["mode"] == "ai"
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["item_code"] == "T-101" and item["qty"] == 20.0
        assert item["origin"] == "ai"
        assert "20m relocation run" in item["reason"]
        assert body["subtotal_sar"] == round(20 * 10.94, 2)
        assert body["model"]  # the configured chat model is recorded

    def test_invalid_llm_json_degrades_to_keyword(self, client, admin_headers,
                                                  project, master_rows, monkeypatch):
        monkeypatch.setattr(provider, "available", lambda: (True, None))
        monkeypatch.setattr(provider, "chat", lambda *a, **k: "I cannot answer that.")
        resp = _draft(client, admin_headers, project)
        assert resp.status_code == 201
        assert resp.json()["mode"] == "keyword"

    def test_ai_cannot_invent_item_codes(self, client, admin_headers,
                                         project, master_rows, monkeypatch):
        monkeypatch.setattr(provider, "available", lambda: (True, None))
        monkeypatch.setattr(provider, "chat", lambda *a, **k: (
            '[{"item_code": "HACK-1", "qty": 5, "reason": "x"},'
            ' {"item_code": "T-102", "qty": 2, "reason": "y"}]'
        ))
        resp = _draft(client, admin_headers, project)
        body = resp.json()
        codes = [i["item_code"] for i in body["items"]]
        assert "HACK-1" not in codes and "T-102" in codes


class TestAcceptFlow:
    def test_accept_creates_design_boq_rows(self, client, admin_headers,
                                            project, master_rows, monkeypatch):
        monkeypatch.setattr(provider, "available", lambda: (False, "tests"))
        draft = _draft(client, admin_headers, project).json()

        resp = client.post(
            f"/api/mto/project/{project}/materials-proposals/{draft['id']}/accept",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["boq_items_created"] == len(draft["items"])

        boq = client.get(f"/api/projects/{project}/boq",
                         headers=admin_headers).json()
        codes = {b["item_code"] for b in boq}
        assert codes == {i["item_code"] for i in draft["items"]}
        emt = next(b for b in boq if b["item_code"] == "T-101")
        assert emt["unit_rate"] == 10.94 and emt["mto_kind"] == "design"

        # double-accept is a conflict
        resp = client.post(
            f"/api/mto/project/{project}/materials-proposals/{draft['id']}/accept",
            headers=admin_headers,
        )
        assert resp.status_code == 409

    def test_reject_keeps_history(self, client, admin_headers, project,
                                  master_rows, monkeypatch):
        monkeypatch.setattr(provider, "available", lambda: (False, "tests"))
        draft = _draft(client, admin_headers, project).json()
        resp = client.post(
            f"/api/mto/project/{project}/materials-proposals/{draft['id']}/reject",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        listing = client.get(f"/api/mto/project/{project}/materials-proposals",
                             headers=admin_headers).json()
        assert any(p["id"] == draft["id"] and p["status"] == "rejected"
                   for p in listing)

    def test_member_cannot_accept(self, client, admin_headers, role_headers,
                                  project, master_rows, monkeypatch):
        monkeypatch.setattr(provider, "available", lambda: (False, "tests"))
        draft = _draft(client, admin_headers, project).json()
        resp = client.post(
            f"/api/mto/project/{project}/materials-proposals/{draft['id']}/accept",
            headers=role_headers["member1"],
        )
        assert resp.status_code == 403


def test_unit_scope_tokenizer():
    tokens = ai_materials._scope_tokens(
        "Supply and install 1-inch EMT conduit with junction boxes")
    assert "conduit" in tokens and "supply" not in tokens
