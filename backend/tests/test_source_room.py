"""The PR data room: upload any format, extract the text, build the brief."""

import io
import uuid


def _pr() -> str:
    return f"PR-{uuid.uuid4().hex[:8].upper()}"


def _project(client, headers) -> dict:
    resp = client.post(
        "/api/projects",
        json={"pr_number": _pr(), "title": "Data room check", "pi_name": "Dr. Data"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_taxonomy_lists_the_archive_folders(client, admin_headers):
    resp = client.get("/api/sources/taxonomy", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    keys = [entry["key"] for entry in body["taxonomy"]]
    assert "01_Initiation" in keys
    assert "03_Specifications" in keys
    assert "11_Reports" in keys
    assert "utility_matrix" in body["doc_types"]
    assert "raw_data" in body["doc_types"]


def test_upload_extracts_text_and_lists_by_folder(client, admin_headers):
    project = _project(client, admin_headers)
    pid = project["id"]

    payload = (
        "REF,DESCRIPTION,UNIT,QTY\n"
        "1.1,1/2 inch copper N2 pipe,L.M.,18\n"
        "1.2,Ball valve 1/2 inch,EA,1\n"
    )
    resp = client.post(
        f"/api/projects/{pid}/sources",
        files=[("files", ("row-data.csv", io.BytesIO(payload.encode()), "text/csv"))],
        data={"category": "99_Unsorted", "doc_type": "raw_data"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["readable_documents"] == 1
    doc = body["documents"][0]
    assert doc["doc_type"] == "raw_data"
    assert doc["text_chars"] > 0
    assert "copper N2 pipe" in (doc["text_excerpt"] or "")

    text = client.get(f"/api/sources/{doc['id']}/text", headers=admin_headers)
    assert text.status_code == 200, text.text
    assert "Ball valve" in text.json()["text"]

    room = client.get(f"/api/projects/{pid}/sources", headers=admin_headers).json()
    assert room["total_bytes"] == len(payload.encode())

    bad = client.post(
        f"/api/projects/{pid}/sources",
        files=[("files", ("x.txt", io.BytesIO(b"x"), "text/plain"))],
        data={"category": "12_Nonsense", "doc_type": "other"},
        headers=admin_headers,
    )
    assert bad.status_code == 422


def test_analyze_builds_a_brief(client, admin_headers, monkeypatch):
    from app.ai import brief as brief_ai

    project = _project(client, admin_headers)
    pid = project["id"]
    client.post(
        f"/api/projects/{pid}/sources",
        files=[("files", ("spec.txt", io.BytesIO(b"Supply and install N2 piping."), "text/plain"))],
        data={"category": "03_Specifications", "doc_type": "technical_specification"},
        headers=admin_headers,
    )

    captured = {}

    def fake_run(project_obj, sources, texts, **kwargs):
        captured["files"] = [s.filename for s in sources]
        captured["text"] = texts[sources[0].id]
        return {
            "summary": "N2 piping to a fume hood.",
            "scope_by_trade": [{"trade": "Plumbing", "requirement": "N2 line"}],
            "utilities": [
                {"name": "Nitrogen", "available_at_site": "no", "action": "provide"}
            ],
            "line_items": [
                {"ref": "1.1", "description": "Copper pipe", "unit": "L.M.", "qty": "18"}
            ],
            "open_questions": [{"question": "Tie-in point?", "blocking": True}],
        }

    monkeypatch.setattr(brief_ai, "run_brief", fake_run)

    started = client.post(f"/api/projects/{pid}/sources/analyze", headers=admin_headers)
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "running"

    # TestClient runs the background task before returning, so the brief is ready.
    brief = client.get(f"/api/projects/{pid}/sources/brief", headers=admin_headers)
    assert brief.status_code == 200, brief.text
    body = brief.json()
    assert body["status"] == "ready", body
    assert body["version"] == 1
    assert body["payload"]["utilities"][0]["name"] == "Nitrogen"
    assert body["payload"]["line_items"][0]["qty"] == "18"
    assert captured["files"] == ["spec.txt"]
    assert "N2 piping" in captured["text"]

    empty = _project(client, admin_headers)
    refused = client.post(
        f"/api/projects/{empty['id']}/sources/analyze", headers=admin_headers
    )
    assert refused.status_code == 409


def test_generate_deliverables_from_the_brief(client, admin_headers, monkeypatch):
    """The four documents are rendered from the templates and attached."""
    from app.ai import brief as brief_ai

    project = _project(client, admin_headers)
    pid = project["id"]
    client.post(
        f"/api/projects/{pid}/sources",
        files=[("files", ("row-data.csv", io.BytesIO(b"1.1,Copper pipe,L.M.,18\n"), "text/csv"))],
        data={"category": "99_Unsorted", "doc_type": "raw_data"},
        headers=admin_headers,
    )

    monkeypatch.setattr(
        brief_ai,
        "run_brief",
        lambda project_obj, sources, texts, **kwargs: {
            "summary": "N2 piping to the fume hood.",
            "scope_by_trade": [
                {
                    "trade": "Plumbing",
                    "requirement": "Supply and install the 1/2 inch copper N2 line\nPressure test",
                },
                {"trade": "Electrical", "requirement": "Supply and install one 13 A socket."},
            ],
            "utilities": [{"name": "Nitrogen", "available_at_site": "no"}],
            "line_items": [
                {
                    "ref": "1.1",
                    "trade": "Plumbing",
                    "description": "Copper N2 pipe 1/2 inch",
                    "spec": "Mueller or equal",
                    "unit": "L.M.",
                    "qty": "18",
                },
                {
                    "ref": "2.1",
                    "trade": "Electrical",
                    "description": "13 A duplex socket",
                    "unit": "EA",
                    "qty": "1",
                },
            ],
            "open_questions": [{"question": "Tie-in point?", "blocking": True}],
        },
    )
    started = client.post(f"/api/projects/{pid}/sources/analyze", headers=admin_headers)
    assert started.status_code == 202, started.text

    generated = client.post(
        f"/api/projects/{pid}/sources/generate", headers=admin_headers
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    kinds = [doc["kind"] for doc in body["documents"]]
    assert kinds == ["Project Summary", "Scope of Work", "BOQ", "MTO"], body
    for doc in body["documents"]:
        assert doc["size_bytes"] > 5000, doc

    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    names = [a["filename"] for a in detail["attachments"]]
    assert any(n.endswith(".docx") for n in names)
    assert any(n.endswith(".xlsx") for n in names)

    # Without a ready brief there is nothing to build from.
    empty = _project(client, admin_headers)
    refused = client.post(
        f"/api/projects/{empty['id']}/sources/generate", headers=admin_headers
    )
    assert refused.status_code == 409


def test_delete_source_removes_the_file(client, admin_headers):
    project = _project(client, admin_headers)
    pid = project["id"]
    client.post(
        f"/api/projects/{pid}/sources",
        files=[("files", ("note.txt", io.BytesIO(b"site note"), "text/plain"))],
        data={"category": "99_Unsorted", "doc_type": "raw_data"},
        headers=admin_headers,
    )
    doc = client.get(f"/api/projects/{pid}/sources", headers=admin_headers).json()["documents"][0]
    removed = client.delete(f"/api/sources/{doc['id']}", headers=admin_headers)
    assert removed.status_code == 204
    room = client.get(f"/api/projects/{pid}/sources", headers=admin_headers).json()
    assert room["documents"] == []
