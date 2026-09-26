"""Index the platform's own documents into the AI corpus.

Policy: the assistant answers from IHP platform data only - the live database
(projects, MOM, EAR, SOW, BOQ/MTO, construction, closeout) plus the documents
users upload to those projects. No external engineering archive.

Every uploaded attachment is text-extracted, chunked and stored scoped to its
project, so "what does the SOW say about the gas line?" is answered from the
actual file the team uploaded, cited by name.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import provider
from ..ai.corpus import chunk_text, sanitize_text
from ..models import Attachment, CorpusChunk, CorpusDocument
from .archive_ingest import extract_file_text

#: Attachments we can read. Anything else is counted as unsupported.
INDEXABLE_SUFFIXES = {
    ".pdf", ".docx", ".xlsx", ".xlsm", ".msg", ".txt", ".md", ".csv",
}


def _corpus_name(attachment: Attachment) -> str:
    return f"attachment/{attachment.filename}"[:300]


def remove_attachment_index(db: Session, attachment: Attachment) -> int:
    """Drop the corpus copy of an attachment (used when the file is deleted)."""
    docs = db.scalars(
        select(CorpusDocument).where(
            CorpusDocument.source == "attachment",
            CorpusDocument.project_id == attachment.project_id,
            CorpusDocument.filename == _corpus_name(attachment),
        )
    ).all()
    removed = 0
    for doc in docs:
        db.query(CorpusChunk).filter(CorpusChunk.document_id == doc.id).delete()
        db.delete(doc)
        removed += 1
    if removed:
        db.commit()
    return removed


def index_attachment(
    db: Session,
    attachment: Attachment,
    user_id: int,
    embed: bool = False,
) -> dict[str, Any]:
    """Extract one stored attachment into corpus chunks scoped to its project."""
    path = Path(attachment.stored_path)
    if not path.exists():
        return {"indexed": 0, "reason": "stored file is missing"}
    if path.suffix.lower() not in INDEXABLE_SUFFIXES:
        return {"indexed": 0, "reason": f"unsupported type {path.suffix}"}

    try:
        text = sanitize_text(extract_file_text(path))
    except Exception as exc:  # noqa: BLE001 — a bad file must not break uploads
        return {"indexed": 0, "reason": f"extract failed: {exc}"[:200]}

    chunks = chunk_text(text) if text.strip() else []
    if not chunks:
        return {"indexed": 0, "reason": "no extractable text"}

    # Re-indexing a new version replaces the previous copy.
    remove_attachment_index(db, attachment)

    vectors: list[list[float] | None] = [None] * len(chunks)
    if embed:
        try:
            vectors = provider.embed_many(chunks)
        except Exception:  # noqa: BLE001 — keyword retrieval still works
            vectors = [None] * len(chunks)

    doc = CorpusDocument(
        filename=_corpus_name(attachment),
        source="attachment",
        project_id=attachment.project_id,
        chunk_count=len(chunks),
        uploaded_by_id=user_id,
    )
    db.add(doc)
    db.flush()
    for index, text_chunk in enumerate(chunks):
        db.add(CorpusChunk(
            document_id=doc.id,
            project_id=attachment.project_id,
            chunk_index=index,
            text=text_chunk,
            embedding=vectors[index] if index < len(vectors) else None,
        ))
    db.commit()
    return {"indexed": len(chunks), "document_id": doc.id}


def index_attachments(
    db: Session,
    user_id: int,
    project_id: int | None = None,
    limit: int = 2000,
    embed: bool = False,
    progress: Any = None,
    should_stop: Any = None,
) -> dict[str, Any]:
    """Index every stored attachment (optionally for one project)."""
    started = time.time()
    stmt = select(Attachment).order_by(Attachment.id)
    if project_id is not None:
        stmt = stmt.where(Attachment.project_id == project_id)
    rows = db.scalars(stmt.limit(limit)).all()

    indexed = chunks = skipped = failed = embedded = 0
    for position, attachment in enumerate(rows, start=1):
        if should_stop is not None and should_stop():
            break
        result = index_attachment(db, attachment, user_id, embed=embed)
        count = int(result.get("indexed") or 0)
        if count:
            indexed += 1
            chunks += count
            embedded += count if embed else 0
        elif "unsupported" in str(result.get("reason", "")) or "no extractable" in str(result.get("reason", "")):
            skipped += 1
        else:
            failed += 1
        if progress and (position % 5 == 0 or position == len(rows)):
            progress({
                "scanned": position, "total": len(rows), "indexed": indexed,
                "chunks": chunks, "embedded": embedded, "skipped": skipped,
                "failed": failed, "current": attachment.filename,
                "elapsed_s": round(time.time() - started, 1),
            })

    return {
        "attachments": len(rows),
        "indexed": indexed,
        "chunks": chunks,
        "embedded_chunks": embedded,
        "skipped": skipped,
        "failed": failed,
        "seconds": round(time.time() - started, 1),
    }
