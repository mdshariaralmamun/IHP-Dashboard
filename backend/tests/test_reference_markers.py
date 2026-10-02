"""The site reference (buildings, lots, LFOs) and the plan markers."""

from __future__ import annotations

import pytest

from app.services import reference


_SEQ = iter(range(74010, 74100))


@pytest.fixture()
def project_id(client, admin_headers):
    resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={"pr_number": f"PR-{next(_SEQ)}", "title": "Reference test",
              "location": "B5 L3 A1"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


class TestReference:
    def test_the_lists_loaded(self):
        assert len(reference.buildings()) >= 20
        assert len(reference.lot_codes()) >= 250
        assert len(reference.lfos()) >= 70

    def test_a_room_code_decodes_against_the_master_list(self):
        decoded = reference.decode_location("Room 5-3610")
        assert decoded["building"] == 5 and decoded["level"] == 3
        assert decoded["room"] == "5-3610"
        assert decoded["area"] is None  # only the B-form states the area
        assert decoded["known_building"] is True
        assert "NORTH RESEARCH" in (decoded["building_title"] or "")

    def test_the_shorthand_form_decodes(self):
        decoded = reference.decode_location("B7 L2 A3")
        assert (decoded["building"], decoded["level"], decoded["area"]) == (7, 2, 3)

    def test_free_text_does_not_decode(self):
        assert reference.decode_location("somewhere near the café") is None
        assert reference.decode_location(None) is None

    def test_lot_lookup_matches_with_or_without_leading_zeros(self):
        assert reference.lot_by_code("275")["description"] == "Riyadh Stone Works"
        assert reference.lot_by_code("000")["description"] == "Architecture"

    def test_endpoints(self, client, admin_headers, project_id):
        resp = client.get("/api/reference", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["buildings"] >= 20 and body["lot_codes"] >= 250

        resp = client.get(
            "/api/reference/decode", params={"code": "5-3610"}, headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert "Building 5" in resp.json()["described"]

        resp = client.get(
            "/api/reference/lot-codes", params={"search": "marble"}, headers=admin_headers
        )
        assert resp.status_code == 200
        assert any("Marble" in row["description"] for row in resp.json())

    def test_the_reference_is_in_the_corpus_after_the_first_read(
        self, client, admin_headers, project_id
    ):
        client.get("/api/reference", headers=admin_headers)
        again = client.get("/api/reference", headers=admin_headers).json()
        assert again["buildings"] >= 20  # idempotent: no error the second time


class TestPlanMarkers:
    def _make(self, client, headers, pid, **over):
        payload = {"label": "5-3610", "x": 30.0, "y": 40.0, **over}
        resp = client.post(f"/api/projects/{pid}/markers", json=payload, headers=headers)
        assert resp.status_code == 201, resp.text
        return resp.json()

    def test_place_edit_and_divide(self, client, admin_headers, project_id):
        first = self._make(client, admin_headers, project_id,
                           pi_name="Adrian Ichim", pr_ref="PR-74001")
        assert first["pi_name"] == "Adrian Ichim"

        # The PI changes: the label is edited, not recreated.
        resp = client.patch(
            f"/api/projects/{project_id}/markers/{first['id']}",
            json={"pi_name": "Someone New"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["pi_name"] == "Someone New"

        # The location is divided: a second pin beside the first.
        second = self._make(client, admin_headers, project_id,
                            label="5-3611", pi_name="Another PI", x=34.0)
        listed = client.get(f"/api/projects/{project_id}/markers",
                            headers=admin_headers).json()
        assert len(listed) == 2
        assert listed[0]["updated_at"]  # edits are stamped

        resp = client.delete(
            f"/api/projects/{project_id}/markers/{second['id']}",
            headers=admin_headers,
        )
        assert resp.status_code == 204

    def test_positions_are_clamped_to_the_page(self, client, admin_headers, project_id):
        resp = client.post(
            f"/api/projects/{project_id}/markers",
            json={"label": "off-page", "x": 140.0, "y": 50.0},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_editing_needs_the_capability(self, client, role_headers, project_id):
        resp = client.post(
            f"/api/projects/{project_id}/markers",
            json={"label": "x", "x": 1, "y": 1},
            headers=role_headers["viewer"] if "viewer" in role_headers
            else role_headers["member1"],
        )
        assert resp.status_code == 403
