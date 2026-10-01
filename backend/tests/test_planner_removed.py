"""A PR that drops out of the newest Planner must leave the live views.

Regression: PR-12725 ("High Pressure Permeation Equipment (ASEPC)") was in an
older Planner export, is absent from the newest one, and its only O&M record
sits in the "Closed Eqpt & Project Asmnt PRs" tab. It still appeared as a live
project because the register listed every row and the dashboard's
"All / Unbucketed" card counted exactly those dropped rows.

The dates here are RELATIVE on purpose. "Newest snapshot" is global across
every project in the database, and another test publishing a tracker upload
stamps it with today's date - so a hard-coded date silently stopped being the
newest one the moment the calendar moved on.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

_SEQ = iter(range(9700, 9800))

#: What a tracker import run today would stamp.
TODAY = date.today().isoformat()
#: An older export: anything not equal to the newest snapshot is "removed".
OLDER = (date.today() - timedelta(days=7)).isoformat()


@pytest.fixture()
def make_project(client, admin_headers):
    def _make(pr_number: str | None = None, sync: str | None = None, **extra):
        pr = pr_number or f"PR-{next(_SEQ)}"
        description = f"Planner Sync: {sync}\n" if sync else ""
        description += extra.pop("description", "")
        resp = client.post(
            "/api/projects",
            headers=admin_headers,
            json={"pr_number": pr, "title": f"Project {pr}",
                  "description": description, **extra},
        )
        assert resp.status_code in (200, 201), resp.text
        return resp.json()
    return _make


def _by_pr(client, admin_headers) -> dict[str, dict]:
    resp = client.get("/api/projects", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    return {row["pr_number"]: row for row in resp.json()}


class TestPlannerRemoved:
    def test_the_newest_snapshot_decides_who_is_removed(
        self, client, admin_headers, make_project,
    ):
        keep = make_project(sync=TODAY)
        dropped = make_project(sync=OLDER)

        rows = _by_pr(client, admin_headers)
        assert rows[keep["pr_number"]]["in_latest_planner"] is True
        assert rows[keep["pr_number"]]["planner_removed"] is False

        assert rows[dropped["pr_number"]]["in_latest_planner"] is False
        assert rows[dropped["pr_number"]]["planner_removed"] is True, (
            "a PR seen in an older snapshot but missing from the newest one "
            "is removed, not merely stale"
        )

    def test_a_project_that_was_never_tracker_managed_is_not_removed(
        self, client, admin_headers, make_project,
    ):
        """Intake/manual projects have no sync date and must never be treated
        as cancelled - they are simply not tracker rows."""
        manual = make_project(sync=None)
        make_project(sync=TODAY)

        row = _by_pr(client, admin_headers)[manual["pr_number"]]
        assert row["in_latest_planner"] is False
        assert row["planner_removed"] is False

    def test_the_newest_row_is_not_a_removal(
        self, client, admin_headers, make_project,
    ):
        """The flag must not simply mirror in_latest_planner."""
        a = make_project(sync=TODAY)
        rows = _by_pr(client, admin_headers)
        assert rows[a["pr_number"]]["planner_removed"] is False

    def test_removed_prs_are_still_returned_for_audit(
        self, client, admin_headers, make_project,
    ):
        """The API keeps them (the register shows them behind a toggle); it is
        the UI that hides them from the live views."""
        dropped = make_project(sync=OLDER)
        make_project(sync=TODAY)
        assert dropped["pr_number"] in _by_pr(client, admin_headers)
