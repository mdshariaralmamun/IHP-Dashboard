"""The endpoints that read tracker files, and the resolver behind them.

Regression cover for two production faults:

1. `/api/projects/om-active` answered 500 because the local `status`
   variable was replaced while a later `status.get(...)` stayed behind —
   and `projects.py` imports `status` from starlette at module level, so
   the leftover read hit a module instead of the tracker state.
2. The four O&M lookups read `settings.TRACKERS_DIR` directly, bypassing
   the admin override. Production has no `TRACKERS_DIR` env var, so they
   read the Windows default `E:\\ENGINEERING_DATA\\trackers`, which does
   not exist on Linux, and silently returned nothing.
"""

from __future__ import annotations

from pathlib import Path

from app.services import runtime_settings, tracker_import, tracker_sources


def test_configured_dir_honours_the_admin_override(tmp_path, monkeypatch):
    """The override is what makes /trackers resolve in production."""
    monkeypatch.setattr(
        runtime_settings, "_overrides_path", lambda: tmp_path / "settings.json"
    )
    runtime_settings.write_overrides({"TRACKERS_DIR": str(tmp_path / "custom")})
    assert tracker_sources.configured_dir() == tmp_path / "custom"
    assert tracker_sources.search_dirs()[1] == tmp_path / "custom"

    runtime_settings.write_overrides({"PR_REQUEST_DIR": str(tmp_path / "pr")})
    assert tracker_sources.pr_request_dir() == tmp_path / "pr"


def test_om_active_endpoint_reports_the_resolved_sheet(
    client, admin_headers, monkeypatch, tmp_path,
):
    om = tmp_path / "O&M Project Progress Tracking Sheet Sep 2025_30092026.xlsx"
    om.write_bytes(b"x")
    monkeypatch.setattr(tracker_sources, "om_path", lambda: om)
    monkeypatch.setattr(tracker_import, "parse_om_active_prs", lambda path: [])

    resp = client.get("/api/projects/om-active", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["source"] == om.name
    assert body["source_date"] == "2026-09-30"


def test_om_active_endpoint_handles_a_missing_sheet(client, admin_headers, monkeypatch):
    monkeypatch.setattr(tracker_sources, "om_path", lambda: None)
    resp = client.get("/api/projects/om-active", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_tracker_files_status_exposes_the_upload_store(
    client, admin_headers, monkeypatch, tmp_path,
):
    monkeypatch.setattr(tracker_sources, "upload_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(tracker_sources, "configured_dir", lambda: tmp_path / "drop")

    resp = client.get("/api/admin/settings/tracker-files", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["upload_dir"] == str(tmp_path / "store")
    assert body["configured_dir"] == str(tmp_path / "drop")
    assert body["trackers_dirs"] == [
        str(tmp_path / "store"),
        str(tmp_path / "drop"),
    ]

def _icr_row(**kw):
    """One O&M active-PR row with sensible ICR defaults."""
    base = dict(
        pr_key="PR-90001",
        source_tab="Active Equipment PRs",
        title="Pipe removal",
        division="O&M",
        requestor="PI X",
        location="5-3610",
        status="Awaiting site visit",
        classification_raw="Contruction Project",
        category="CONSTRUCTION",
        remarks="Approved by PI",
        request_date="2026-01-05",
    )
    base.update(kw)
    return tracker_import.ActivePrRow(**base)


def test_pull_icr_endpoint_creates_then_updates_in_place(
    client, admin_headers, monkeypatch, tmp_path,
):
    """Construction rows on the equipment tab become ICR, never duplicates."""
    om = tmp_path / "O&M Project Progress Tracking Sheet Sep 2025_30092026.xlsx"
    om.write_bytes(b"x")
    monkeypatch.setattr(tracker_sources, "om_path", lambda: om)
    rows = [
        _icr_row(),
        # Equipment installation is a separate stream: never pulled as ICR.
        _icr_row(
            pr_key="PR-90002",
            title="Install a chiller",
            classification_raw="Equipment installation",
            category="EQUIPMENT_INSTALLATION",
        ),
    ]
    monkeypatch.setattr(
        tracker_import, "parse_om_active_prs", lambda path, tabs=None: rows
    )

    first = client.post("/api/projects/om-active/pull-icr", headers=admin_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["ok"] is True
    assert body["created"] == 1
    assert body["updated"] == 0
    assert body["total"] == 1, "the equipment row must be filtered out"
    item = body["items"][0]
    assert item["pr_key"] == "PR-90001"
    assert item["action"] == "created"

    listed = client.get("/api/projects/om-active", headers=admin_headers).json()
    found = [i for i in listed["items"] if i["pr_key"] == "PR-90001"]
    assert len(found) == 1
    assert found[0]["in_app"] is True
    assert found[0]["app_disposition"] == "ICR"

    project_id = item["project_id"]
    detail = client.get("/api/projects/" + str(project_id), headers=admin_headers)
    assert detail.status_code == 200, detail.text
    project = detail.json()
    assert project["disposition"] == "ICR"
    assert project["stage"] == "MTO_DRAFT"
    assert project["followup_note"].startswith("O&M tracker: Awaiting site visit")
    assert "Approved by PI" in project["followup_note"]

    # Re-running is idempotent: the same PR is updated in place.
    second = client.post("/api/projects/om-active/pull-icr", headers=admin_headers)
    assert second.status_code == 200, second.text
    again = second.json()
    assert again["created"] == 0
    assert again["unchanged"] == 1
    assert again["items"][0]["project_id"] == project_id


def test_pull_icr_endpoint_404s_without_an_om_workbook(
    client, admin_headers, monkeypatch,
):
    monkeypatch.setattr(tracker_sources, "om_path", lambda: None)
    resp = client.post("/api/projects/om-active/pull-icr", headers=admin_headers)
    assert resp.status_code == 404


def test_pull_icr_endpoint_reports_no_construction_rows(
    client, admin_headers, monkeypatch, tmp_path,
):
    om = tmp_path / "O&M Project Progress Tracking Sheet Sep 2025_30092026.xlsx"
    om.write_bytes(b"x")
    monkeypatch.setattr(tracker_sources, "om_path", lambda: om)
    monkeypatch.setattr(
        tracker_import,
        "parse_om_active_prs",
        lambda path, tabs=None: [_icr_row(category="EQUIPMENT_ASSESSMENT")],
    )
    resp = client.post("/api/projects/om-active/pull-icr", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is False
    assert resp.json()["total"] == 0
