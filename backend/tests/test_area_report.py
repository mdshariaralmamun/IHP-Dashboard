"""Area-wise tracking: a location's PIs and its finished vs active work."""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import PlanMarker, Project

_SEQ = iter(range(75010, 75100))

#: Stage pairs that decide the split under test.
_ACTIVE, _FINISHED = "CONSTRUCTION", "CLOSEOUT"


def _make(client, headers, *, location, pi, stage=_ACTIVE, pr=None):
    resp = client.post(
        "/api/projects",
        headers=headers,
        json={
            "pr_number": pr or f"PR-{next(_SEQ)}",
            "title": f"Work in {location}",
            "location": location,
            "pi_name": pi,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    pid = resp.json()["id"]
    if stage != "INTAKE":
        client.post(
            f"/api/projects/{pid}/stage",
            headers=headers,
            json={"stage": stage, "justification": "test setup"},
        )
    return pid


def _report(client, headers, where):
    resp = client.get(
        "/api/areas/report",
        params={"location": where},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestAreaReport:
    def test_who_is_there_now_who_was_there_before(
        self, client, admin_headers
    ):
        _make(client, admin_headers, location="B5 L3 A1", pi="Current PI")
        _make(client, admin_headers, location="5-3610", pi="Old PI", stage=_FINISHED)

        report = _report(client, admin_headers, "5-3610")
        assert report["ok"] is True
        assert report["decoded"]["building"] == 5
        assert "Building 5" in report["described"]
        # The finished row's PI is history; the active one is current.
        assert "Current PI" in report["current_pis"]
        assert "Old PI" in report["previous_pis"]
        assert "Old PI" not in report["current_pis"]
        assert report["active_count"] == 1
        assert report["finished_count"] == 1
        assert report["finished_projects"][0]["stage"] == _FINISHED

    def test_other_floors_do_not_leak_in(self, client, admin_headers):
        # Its own building: the shared test database already holds other
        # tests' projects, and an area report is not scoped to a fixture.
        _make(client, admin_headers, location="B9 L4 A2", pi="Right")
        _make(client, admin_headers, location="B9 L3 A2", pi="Wrong")

        report = _report(client, admin_headers, "B9 L4 A2")
        assert report["active_count"] == 1
        assert report["current_pis"] == ["Right"]
        assert "Wrong" not in report["current_pis"]

    def test_a_pin_labels_the_area_even_when_the_register_is_loose(
        self, client, admin_headers
    ):
        pid = _make(client, admin_headers, location="B7", pi="Register PI")
        resp = client.post(
            f"/api/projects/{pid}/markers",
            headers=admin_headers,
            json={"label": "7-2105", "pi_name": "Pin PI", "x": 10, "y": 10},
        )
        assert resp.status_code == 201

        report = _report(client, admin_headers, "7-2105")
        assert report["active_count"] == 1
        assert "Pin PI" in report["previous_pis"] + report["current_pis"]

    def test_free_text_is_rejected_clearly(self, client, admin_headers):
        report = _report(client, admin_headers, "somewhere")
        assert report["ok"] is False
        assert "Could not decode" in report["error"]
