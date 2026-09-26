"""Retrieval over the corpus, feedback capture and training export."""

import json

from app.ai import retrieval
from app.db import SessionLocal
from app.models import CorpusChunk, CorpusDocument, User

TEST_DOCS = ["IHP-AI-TEST-nitrogen.txt", "IHP-AI-TEST-chiller.txt"]


def _cleanup(db) -> None:
    for name in TEST_DOCS:
        docs = db.query(CorpusDocument).filter(CorpusDocument.filename == name).all()
        for doc in docs:
            db.query(CorpusChunk).filter(CorpusChunk.document_id == doc.id).delete()
            db.delete(doc)
    db.commit()


def _seed_corpus(db):
    admin = db.query(User).filter(User.username == "admin").first()
    nitrogen = CorpusDocument(
        filename=TEST_DOCS[0], source="archive", chunk_count=1,
        uploaded_by_id=admin.id,
    )
    chiller = CorpusDocument(
        filename=TEST_DOCS[1], source="archive", chunk_count=1,
        uploaded_by_id=admin.id,
    )
    db.add_all([nitrogen, chiller])
    db.flush()
    db.add(CorpusChunk(
        document_id=nitrogen.id, chunk_index=0, text=(
            "PR 10444 B3 nitrogen line: the scope of work covered a 2 inch "
            "stainless steel nitrogen line from the manifold to the glovebox, "
            "including pressure testing at 10 bar and labelling."
        ),
    ))
    db.add(CorpusChunk(
        document_id=chiller.id, chunk_index=0, text=(
            "PR 10666 chiller replacement: remove the 40 kW air cooled chiller on "
            "the roof and install a new unit with vibration isolators."
        ),
    ))
    db.commit()
    return nitrogen.id, chiller.id


def test_chunk_text_bounds_every_chunk():
    """A document with no blank lines must still produce bounded chunks."""
    from app.ai.corpus import chunk_text

    long_paragraph = ("Nitrogen line scope item with pressure test. " * 400).strip()
    chunks = chunk_text(long_paragraph, max_chars=500)
    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) > 4000


def test_chunk_text_strips_nul_bytes():
    """Postgres rejects NUL in text columns; extraction emits them."""
    from app.ai.corpus import chunk_text

    chunks = chunk_text("Scope of work\x00 for the nitrogen line\r\nsecond line")
    assert chunks
    assert "\x00" not in chunks[0]
    assert "\r" not in chunks[0]
    assert "nitrogen line" in chunks[0]


def test_keyword_retrieval_finds_the_right_document():
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed_corpus(db)
        hits = retrieval.search("how did we install the nitrogen line?", db, k=3)
        assert hits, "retrieval returned nothing"
        assert hits[0]["filename"] == TEST_DOCS[0]
        assert "nitrogen" in hits[0]["text"].lower()

        other = retrieval.search("chiller vibration isolators", db, k=3)
        assert other and other[0]["filename"] == TEST_DOCS[1]
    finally:
        _cleanup(db)
        db.close()


def test_retrieval_stats_counts_chunks():
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed_corpus(db)
        stats = retrieval.stats(db)
        assert stats["documents"] >= 2
        assert stats["chunks"] >= 2
        assert stats["by_source"].get("archive", 0) >= 2
    finally:
        _cleanup(db)
        db.close()


def test_search_endpoint_returns_cited_hits(client, admin_headers):
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed_corpus(db)
        resp = client.get(
            "/api/ai/search", params={"q": "nitrogen line 2 inch"}, headers=admin_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["count"] >= 1
        assert body["hits"][0]["filename"] == TEST_DOCS[0]
    finally:
        _cleanup(db)
        db.close()


def test_feedback_is_recorded_and_exported(client, admin_headers, data_dir):
    resp = client.post(
        "/api/ai/feedback",
        json={
            "question": "Which projects are overdue?",
            "answer": "11 projects are overdue.",
            "rating": "up",
            "mode": "live",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["recorded"] is True

    stats = client.get("/api/ai/feedback/stats", headers=admin_headers).json()
    assert stats["up"] >= 1

    export = client.post("/api/ai/training/export", headers=admin_headers)
    assert export.status_code == 200, export.text
    body = export.json()
    assert body["written"] >= len(TEST_DOCS)  # synthetic live-fact pairs
    dataset = data_dir / "training" / "ihp_sft.jsonl"
    assert dataset.exists()
    first = json.loads(dataset.read_text(encoding="utf-8").splitlines()[0])
    assert [m["role"] for m in first["messages"]] == ["system", "user", "assistant"]


def test_feedback_rejects_a_bad_rating(client, admin_headers):
    resp = client.post(
        "/api/ai/feedback",
        json={"question": "x", "rating": "maybe"},
        headers=admin_headers,
    )
    assert resp.status_code == 400
