"""The assistant's knowledge base is the app's own documents."""

from pathlib import Path

from app.ai import retrieval
from app.db import SessionLocal
from app.models import Attachment, CorpusChunk, CorpusDocument, Project, User

TEXT_DOC = "IHP-APP-TEST-scope.txt"
SCOPE_TEXT = (
    "Scope of work for PR-99001: supply and install a 2 inch stainless steel "
    "nitrogen line from the manifold to the glovebox, pressure test at 10 bar, "
    "label all valves, and hand over the test certificate."
)


def _project(db) -> Project:
    return db.query(Project).filter(Project.pr_number == "PR-99001").first()


def _make_attachment(db, project) -> Attachment:
    from app.core.config import get_settings

    data_dir = Path(get_settings().DATA_DIR)
    directory = data_dir / "projects" / project.pr_number / "SOW"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("v1_" + TEXT_DOC)
    path.write_text(SCOPE_TEXT, encoding="utf-8")
    admin = db.query(User).filter(User.username == "admin").first()
    attachment = Attachment(
        project_id=project.id,
        stage="SOW",
        filename=TEXT_DOC,
        stored_path=str(path),
        content_type="text/plain",
        size_bytes=len(SCOPE_TEXT),
        version=1,
        uploaded_by_id=admin.id,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


def _cleanup(db) -> None:
    for doc in db.query(CorpusDocument).filter(
        CorpusDocument.filename == "attachment/" + TEXT_DOC
    ).all():
        db.query(CorpusChunk).filter(CorpusChunk.document_id == doc.id).delete()
        db.delete(doc)
    for attachment in db.query(Attachment).filter(Attachment.filename == TEXT_DOC).all():
        Path(attachment.stored_path).unlink(missing_ok=True)
        db.delete(attachment)
    db.commit()


def test_uploaded_document_is_indexed_and_retrievable(live_projects):
    """An attachment uploaded through the app becomes citable knowledge."""
    from app.services import app_documents

    db = live_projects
    _cleanup(db)
    admin = db.query(User).filter(User.username == "admin").first()
    attachment = _make_attachment(db, _project(db))

    result = app_documents.index_attachment(db, attachment, admin.id, embed=False)
    assert result["indexed"] >= 1

    hits = retrieval.search("nitrogen line pressure test", db, k=3)
    assert hits, "the uploaded document was not retrievable"
    assert hits[0]["filename"] == "attachment/" + TEXT_DOC
    assert hits[0]["project_id"] == _project(db).id

    # The document is scoped to its project, so another project sees nothing.
    scoped = retrieval.search(
        "nitrogen line pressure test", db, k=3, project_id=_project(db).id + 9999
    )
    assert all(hit["project_id"] is None for hit in scoped)

    _cleanup(db)


def test_deleting_an_attachment_removes_its_corpus_copy(live_projects):
    from app.services import app_documents

    db = live_projects
    _cleanup(db)
    admin = db.query(User).filter(User.username == "admin").first()
    attachment = _make_attachment(db, _project(db))
    app_documents.index_attachment(db, attachment, admin.id, embed=False)
    assert db.query(CorpusDocument).filter(
        CorpusDocument.filename == "attachment/" + TEXT_DOC
    ).count() == 1

    removed = app_documents.remove_attachment_index(db, attachment)
    assert removed == 1
    assert db.query(CorpusChunk).filter(
        CorpusChunk.document_id.is_(None)
    ).count() == 0
    _cleanup(db)


def test_reindex_endpoint_queues_the_job(client, admin_headers):
    resp = client.post("/api/projects/attachments/reindex", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["started"] is True
