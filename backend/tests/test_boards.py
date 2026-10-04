"""The EAR / Design / Procore boards and whose court a project is in."""

from __future__ import annotations

import pytest

from app.services.court import project_court


class _P:
    """Just the fields the court logic reads."""
    def __init__(self, summary_status=None):
        self.summary_status = summary_status


class TestCourt:
    def test_nothing_started_is_our_move(self):
        state = project_court(_P(), None)
        assert state["my_court"] is True
        assert "Generate the MOM" in state["our_moves"]
        assert "Generate the Project Summary" in state["our_moves"]

    def test_drafts_are_ours_sent_is_their_move(self):
        state = project_court(_P("draft"), "draft")
        assert "Send the MOM" in state["our_moves"]
        assert "Send the Project Summary" in state["our_moves"]
        assert state["my_court"] is True

        state = project_court(_P("sent"), "sent")
        assert state["my_court"] is False
        assert state["waiting_on"] == "PI"
        assert all("Follow up" in m for m in state["their_moves"])

    def test_everything_acknowledged_is_done(self):
        state = project_court(_P("acknowledged"), "acknowledged")
        assert state["my_court"] is False
        assert state["waiting_on"] is None
        assert state["our_moves"] == [] and state["their_moves"] == []

    def test_a_dispute_comes_back_to_us(self):
        state = project_court(_P("acknowledged"), "disputed")
        assert state["my_court"] is True
        assert "Resolve the dispute" in state["our_moves"][0]


_SEQ = iter(range(76010, 76100))


def _make(client, headers, *, bucket, stage="INTAKE", pi="PI One", summary=None):
    resp = client.post(
        "/api/projects",
        headers=headers,
        json={"pr_number": f"PR-{next(_SEQ)}", "title": "Board test",
              "pi_name": pi, "pi_email": "pi@example.com"},
    )
    assert resp.status_code in (200, 201), resp.text
    pid = resp.json()["id"]
    if bucket:
        client.put(f"/api/projects/{pid}", headers=headers,
                   json={"planner_bucket": bucket})
    if stage != "INTAKE":
        client.post(f"/api/projects/{pid}/stage", headers=headers,
                    json={"stage": stage, "justification": "board test setup"})
    if summary:
        client.post(f"/api/projects/{pid}/summary-status", headers=headers,
                    json={"status": summary})
    if stage == "MOM_SENT":
        client.post(f"/api/projects/{pid}/mom/generate", headers=headers, json={})
        client.post(f"/api/projects/{pid}/mom/status",
                    headers=headers, json={"status": "sent"})
    return pid


class TestBoard:
    def test_counts_and_courts(self, client, admin_headers):
        _make(client, admin_headers, bucket="EAR", pi="Pending PI")
        _make(client, admin_headers, bucket="EAR", pi="Sent PI",
              stage="MOM_SENT", summary="sent")

        resp = client.get("/api/boards/ear", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        board = resp.json()
        # Other suites share the DB, so assert on OUR rows only.
        ours = [r for r in board["rows"] if r["pi_name"] in ("Pending PI", "Sent PI")]
        assert len(ours) == 2
        pending = next(r for r in ours if r["pi_name"] == "Pending PI")
        assert pending["my_court"] is True
        assert "Generate the MOM" in pending["our_moves"][0]
        sent = next(r for r in ours if r["pi_name"] == "Sent PI")
        assert sent["mom"]["status"] == "sent"
        assert sent["my_court"] is False and sent["waiting_on"] == "PI"
        assert board["counts"]["my_court"] >= 1

    def test_each_board_holds_its_own_phase(self, client, admin_headers):
        pid = _make(client, admin_headers, bucket="DESIGN", stage="SOW_DRAFT")
        for phase in ("ear", "procore"):
            rows = client.get(f"/api/boards/{phase}",
                              headers=admin_headers).json()["rows"]
            assert all(r["id"] != pid for r in rows)
        rows = client.get("/api/boards/design", headers=admin_headers).json()["rows"]
        assert any(r["id"] == pid for r in rows)

    def test_unknown_board_is_404(self, client, admin_headers):
        assert client.get("/api/boards/nope", headers=admin_headers).status_code == 404

    def test_owner_and_followup_note_persist(self, client, admin_headers):
        pid = _make(client, admin_headers, bucket="PROCORE")
        resp = client.put(
            f"/api/projects/{pid}", headers=admin_headers,
            json={"owner_username": "engineer.a", "followup_note": "Chase PO"},
        )
        assert resp.status_code == 200
        rows = client.get("/api/boards/procore", headers=admin_headers).json()["rows"]
        row = next(r for r in rows if r["id"] == pid)
        assert row["owner_username"] == "engineer.a"
        assert row["followup_note"] == "Chase PO"

    def test_summary_status_is_validated(self, client, admin_headers):
        pid = _make(client, admin_headers, bucket="EAR")
        resp = client.post(f"/api/projects/{pid}/summary-status",
                           headers=admin_headers, json={"status": "banana"})
        assert resp.status_code == 400
