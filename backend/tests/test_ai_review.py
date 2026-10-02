"""The per-project AI review of uploaded documents.

The value of this feature is the FINDINGS, so the tests concentrate on what
reaches the model (the project's own documents, or an honest "none indexed"),
what comes back (tolerant JSON parsing, severity normalisation) and what
happens when the model is unavailable or answers with prose.
"""

from __future__ import annotations

import json

import pytest

from app.ai import provider as ai_provider
from app.ai.review import guess_kind, parse_review
from app.db import SessionLocal
from app.models import CorpusChunk, CorpusDocument


def _project(client, admin_headers, pr="PR-73001"):
    resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "pr_number": pr,
            "title": "N2 upgrade investigation",
            "pi_name": "Adrian Ichim",
            "location": "B7 L2 A3",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _index_document(project_id: int, filename: str, text: str) -> None:
    """What services/app_documents writes when an attachment is ingested."""
    db = SessionLocal()
    try:
        document = CorpusDocument(
            filename=f"attachment/{filename}",
            source="attachment",
            project_id=project_id,
            chunk_count=1,
            uploaded_by_id=1,
        )
        db.add(document)
        db.flush()
        db.add(
            CorpusChunk(
                document_id=document.id,
                project_id=project_id,
                chunk_index=0,
                text=text,
            )
        )
        db.commit()
    finally:
        db.close()


REVIEW_JSON = {
    "summary": "Convert the compressed-air storage to nitrogen for the B7 rig.",
    "documents": [
        {"name": "spec.docx", "kind": "equipment_spec", "gist": "Vessel rating"}
    ],
    "scope_by_trade": [{"trade": "Plumbing", "items": ["Replace 16 cylinders"]}],
    "deliverables": ["Nitrogen storage skid"],
    "findings": [
        {
            "id": "F1",
            "severity": "CRITICAL",
            "kind": "conflict",
            "title": "Working pressure disagrees",
            "documents": ["spec.docx", "Utility Matrix B7.xlsx"],
            "detail": "The data sheet says 10 bar; the utility matrix says 6 bar.",
            "why": "The relief valve would be undersized.",
            "required_fix": "Confirm the design pressure with the PI and re-issue both.",
        }
    ],
    "questions": ["Is 10 bar the design or the test pressure?"],
    "confidence": "medium",
    "missing_documents": ["Utility matrix for level 3"],
}


class TestHelpers:
    def test_document_kinds_come_from_the_filename(self):
        assert guess_kind("PR-12592 request form.pdf") == "pr_form"
        assert guess_kind("Utility Matrix B7.xlsx") == "utility_matrix"
        assert guess_kind("Compressor spec rev2.docx") == "equipment_spec"
        assert guess_kind("Meeting invitation.eml") == "invitation"
        assert guess_kind("sizing calc.xlsx") == "calculation"
        assert guess_kind("P&ID level 2.pdf") == "drawing"
        assert guess_kind("someone's notes.txt") == "other"

    def test_parsing_survives_fences_and_padding(self):
        raw = "Here you go:\n\n```json\n" + json.dumps(REVIEW_JSON) + "\n```\n"
        parsed = parse_review(raw)
        assert parsed["summary"] == REVIEW_JSON["summary"]
        assert parsed["findings"][0]["title"] == "Working pressure disagrees"

    def test_severity_is_normalised_and_defaults_are_filled(self):
        parsed = parse_review(
            '{"findings": [{"severity": "CRITICAL"}, {"severity": "nonsense"}]}'
        )
        assert [f["severity"] for f in parsed["findings"]] == ["critical", "minor"]
        assert parsed["questions"] == []
        assert parsed["confidence"] == "low"

    def test_prose_is_not_a_review(self):
        with pytest.raises(ValueError):
            parse_review("I could not read the documents.")

    def test_raw_newlines_and_trailing_commas_are_repaired(self):
        """The two defects a long answer actually contains. Both used to fail
        the whole review with a 502."""
        raw = '{"summary": "line one\nline two", "findings": [{"severity": "major",}],}'
        parsed = parse_review(raw)
        assert parsed["summary"].startswith("line one")
        assert parsed["findings"][0]["severity"] == "major"

    def test_flat_scope_rows_are_grouped_back_into_trades(self):
        """One row per line is what the model is now asked for - nested arrays
        are where it produced unbalanced brackets - and the report shape is
        unchanged."""
        parsed = parse_review(
            '{"scope_by_trade": ['
            '{"trade": "Plumbing", "item": "a"},'
            '{"trade": "Plumbing", "item": "b"},'
            '{"trade": "HVAC", "item": "c"}]}'
        )
        assert parsed["scope_by_trade"] == [
            {"trade": "Plumbing", "items": ["a", "b"]},
            {"trade": "HVAC", "items": ["c"]},
        ]

    def test_the_nested_shape_still_parses(self):
        parsed = parse_review(
            '{"scope_by_trade": [{"trade": "HVAC", "items": ["a"]}]}'
        )
        assert parsed["scope_by_trade"] == [{"trade": "HVAC", "items": ["a"]}]


class TestReviewEndpoint:
    def test_a_review_is_stored_and_returned(self, client, admin_headers, monkeypatch):
        pid = _project(client, admin_headers)
        _index_document(pid, "spec.docx", "Design pressure 10 bar.")

        captured: dict = {}

        def fake_chat(messages, system=None, model=None, provider=None):
            captured["system"] = system
            captured["prompt"] = messages[-1]["content"]
            return "```json\n" + json.dumps(REVIEW_JSON) + "\n```"

        monkeypatch.setattr(ai_provider, "chat", fake_chat)

        resp = client.post(f"/api/projects/{pid}/ai-review", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["summary"] == REVIEW_JSON["summary"]
        assert body["critical_count"] == 1
        assert body["documents_indexed"] == 1
        assert body["documents_read"][0]["name"] == "spec.docx"
        assert body["documents_read"][0]["kind"] == "equipment_spec"
        assert body["generated_at"]

        # The reviewer really read the uploaded document, not just the register.
        assert "spec.docx" in captured["prompt"]
        assert "Design pressure 10 bar." in captured["prompt"]
        assert "PR-73001" in captured["prompt"]
        # ...and was told to find faults, not to agree.
        assert "WRONG or MISSING" in captured["system"]

        again = client.get(f"/api/projects/{pid}/ai-review", headers=admin_headers)
        assert again.status_code == 200
        assert again.json()["summary"] == REVIEW_JSON["summary"]

    def test_no_review_yet_is_not_an_error(self, client, admin_headers):
        pid = _project(client, admin_headers, pr="PR-73002")
        resp = client.get(f"/api/projects/{pid}/ai-review", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "none"

    def test_a_project_without_indexed_documents_says_so(
        self, client, admin_headers, monkeypatch,
    ):
        pid = _project(client, admin_headers, pr="PR-73003")
        captured: dict = {}

        def fake_chat(messages, system=None, model=None, provider=None):
            captured["prompt"] = messages[-1]["content"]
            return json.dumps({"summary": "nothing to read"})

        monkeypatch.setattr(ai_provider, "chat", fake_chat)
        resp = client.post(f"/api/projects/{pid}/ai-review", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["documents_indexed"] == 0
        assert "None have been indexed yet" in captured["prompt"]

    def test_an_unavailable_provider_is_reported(self, client, admin_headers, monkeypatch):
        pid = _project(client, admin_headers, pr="PR-73004")
        monkeypatch.setattr(
            ai_provider, "chat", lambda *a, **k: None
        )
        resp = client.post(f"/api/projects/{pid}/ai-review", headers=admin_headers)
        assert resp.status_code == 502
        assert "provider" in resp.text.lower()

    def test_an_unreadable_answer_is_reported(self, client, admin_headers, monkeypatch):
        pid = _project(client, admin_headers, pr="PR-73005")
        monkeypatch.setattr(
            ai_provider, "chat", lambda *a, **k: "Sure! Here is my review: it looks fine."
        )
        resp = client.post(f"/api/projects/{pid}/ai-review", headers=admin_headers)
        assert resp.status_code == 502
        assert "could not be read" in resp.text.lower()
    def test_an_unbalanced_answer_is_retried_once(
        self, client, admin_headers, monkeypatch,
    ):
        """Production: the model closed a nested array one bracket out and the
        whole review 502'd. One repair round fixes that instead."""
        pid = _project(client, admin_headers, pr="PR-73006")
        calls = {"n": 0}

        def flaky(messages, system=None, model=None, provider=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return '{"summary": "ok", "scope_by_trade": [[ ]]'
            assert "invalid" in messages[-1]["content"].lower()
            return json.dumps({"summary": "ok", "scope_by_trade": []})

        monkeypatch.setattr(ai_provider, "chat", flaky)
        resp = client.post(f"/api/projects/{pid}/ai-review", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["summary"] == "ok"
        assert calls["n"] == 2

    def test_a_hopeless_answer_still_fails_clearly(
        self, client, admin_headers, monkeypatch,
    ):
        pid = _project(client, admin_headers, pr="PR-73007")
        monkeypatch.setattr(
            ai_provider, "chat", lambda *a, **k: "still not json at all"
        )
        resp = client.post(f"/api/projects/{pid}/ai-review", headers=admin_headers)
        assert resp.status_code == 502
        assert "could not be read" in resp.text.lower()

    def test_a_citation_the_reviewer_never_read_is_flagged(
        self, client, admin_headers, monkeypatch,
    ):
        """An invented filename must not read as evidence."""
        pid = _project(client, admin_headers, pr="PR-73008")
        _index_document(pid, "spec.docx", "Design pressure 10 bar.")

        payload = {
            "summary": "s",
            "findings": [
                {
                    "id": "F1",
                    "severity": "critical",
                    "title": "Pressure disagrees",
                    "documents": ["spec.docx", "ghost-document.pdf"],
                }
            ],
        }
        monkeypatch.setattr(
            ai_provider, "chat", lambda *a, **k: json.dumps(payload)
        )
        resp = client.post(f"/api/projects/{pid}/ai-review", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        finding = resp.json()["findings"][0]
        assert finding["documents_unverified"] == ["ghost-document.pdf"]

    def test_attachments_that_could_not_be_read_are_named_not_called_missing(
        self, client, admin_headers, monkeypatch,
    ):
        """"Not attached" and "attached but not indexed" are different
        problems with different owners."""
        pid = _project(client, admin_headers, pr="PR-73009")
        uploaded = client.post(
            f"/api/projects/{pid}/attachments",
            files=[("files", ("Utility Matrix B7.xlsx", b"data", "application/vnd.ms-excel"))],
            headers=admin_headers,
        )
        assert uploaded.status_code == 200, uploaded.text

        captured: dict = {}

        def fake_chat(messages, system=None, model=None, provider=None):
            captured["prompt"] = messages[-1]["content"]
            return json.dumps({"summary": "s"})

        monkeypatch.setattr(ai_provider, "chat", fake_chat)
        resp = client.post(f"/api/projects/{pid}/ai-review", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        assert "ATTACHED BUT NOT READABLE" in captured["prompt"]
        assert "Utility Matrix B7.xlsx" in captured["prompt"]
        assert "never list them under missing_documents" in captured["prompt"]

