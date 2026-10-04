"""The PR data room: raw source files, their text, and the AI brief.

Every PR collects the raw material in whatever format it arrives - engineer
row data, PI emails, the utility matrix, the technical specification, the PR
form, drawings, supplier quotations. The files are stored verbatim, their text
is extracted and cached, and the AI turns the whole room into a structured
brief (scope by trade, utility matrix, line items, open questions) that the
MOM / Project Summary / SOW / BOQ / MTO are built from.

The analysis runs in the background: a data room of a dozen PDFs takes longer
than any HTTP request should, so the endpoint answers immediately with a
running brief and the page polls it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import brief as brief_ai
from ..ai import provider
from ..core.rbac import CAP_ATTACHMENTS_UPLOAD, get_current_user, require_capability
from ..db import SessionLocal, get_db
from ..models import Project, SourceBrief, SourceDocument, User
from ..schemas import SourceBriefOut, SourceDocumentOut, SourceRoomOut
from ..services import source_extract, storage, workflow
from .projects import get_project_or_404

router = APIRouter(prefix="/projects", tags=["sources"])
sources_router = APIRouter(prefix="/sources", tags=["sources"])

#: Refuse absurd uploads (same ceiling as the attachment endpoint).
MAX_UPLOAD_BYTES = 60 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _category(value: str | None) -> str:
    key = (value or "99_Unsorted").strip() or "99_Unsorted"
    if key not in source_extract.TAXONOMY_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown category {key!r}. Valid: "
                + ", ".join(source_extract.TAXONOMY_KEYS)
            ),
        )
    return key


def _doc_type(value: str | None) -> str:
    key = (value or "other").strip().lower() or "other"
    if key not in source_extract.DOC_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown document type {key!r}. Valid: "
                + ", ".join(source_extract.DOC_TYPES)
            ),
        )
    return key


def read_text(source: SourceDocument) -> str:
    """The cached text of a source document (empty when there is none)."""
    if not source.text_path:
        return ""
    path = Path(source.text_path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def project_texts(db: Session, project_id: int) -> tuple[list[SourceDocument], dict[int, str]]:
    sources = db.scalars(
        select(SourceDocument)
        .where(SourceDocument.project_id == project_id)
        .order_by(SourceDocument.category, SourceDocument.id)
    ).all()
    return list(sources), {s.id: read_text(s) for s in sources}


@router.get("/{project_id}/sources", response_model=SourceRoomOut)
def list_sources(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The data room, grouped by the archive taxonomy, plus the latest brief."""
    project = get_project_or_404(db, project_id)
    sources, _texts = project_texts(db, project.id)
    brief = db.scalars(
        select(SourceBrief)
        .where(SourceBrief.project_id == project.id)
        .order_by(SourceBrief.id.desc())
    ).first()
    return SourceRoomOut(
        project_id=project.id,
        pr_number=project.pr_number,
        taxonomy=list(source_extract.TAXONOMY),
        doc_types=list(source_extract.DOC_TYPES),
        documents=[SourceDocumentOut.model_validate(s) for s in sources],
        brief=SourceBriefOut.model_validate(brief) if brief else None,
        readable_documents=sum(1 for s in sources if s.text_chars > 0),
        total_bytes=sum(s.size_bytes for s in sources),
    )


@router.post(
    "/{project_id}/sources",
    response_model=SourceRoomOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_sources(
    project_id: int,
    files: list[UploadFile] = File(...),
    category: str = Form("99_Unsorted"),
    doc_type: str = Form("other"),
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_ATTACHMENTS_UPLOAD)),
):
    """Upload one or more raw files into the PR data room.

    The text is extracted on upload so the reviewer immediately sees whether
    the file was readable, and the AI has something to read.
    """
    project = get_project_or_404(db, project_id)
    cat = _category(category)
    kind = _doc_type(doc_type)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No files were sent.",
        )

    stored = 0
    for upload in files:
        data = await upload.read()
        if not data:
            continue
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{upload.filename} is larger than 60 MB.",
            )
        filename = upload.filename or "upload"
        path, _version = storage.store_upload(project.pr_number, "SOURCE", filename, data)
        text, note = source_extract.extract_text(path)
        text_path = None
        if text:
            text_path = path.with_suffix(path.suffix + ".txt")
            text_path.write_text(text, encoding="utf-8")
        db.add(
            SourceDocument(
                project_id=project.id,
                category=cat,
                doc_type=kind,
                filename=filename,
                stored_path=str(path),
                text_path=str(text_path) if text_path else None,
                content_type=upload.content_type,
                size_bytes=len(data),
                text_chars=len(text),
                text_excerpt=source_extract.excerpt(text) or None,
                extraction_note=note or None,
                uploaded_by_id=user.id,
            )
        )
        stored += 1

    if not stored:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Every uploaded file was empty.",
        )
    workflow.log_action(
        db,
        user,
        "source:upload",
        project,
        {"count": stored, "category": cat, "doc_type": kind},
    )
    db.commit()
    return list_sources(project.id, db, user)


@router.get("/{project_id}/sources/brief", response_model=SourceBriefOut | None)
def latest_brief(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The newest AI brief for this PR (None until one has been run)."""
    project = get_project_or_404(db, project_id)
    brief = db.scalars(
        select(SourceBrief)
        .where(SourceBrief.project_id == project.id)
        .order_by(SourceBrief.id.desc())
    ).first()
    return SourceBriefOut.model_validate(brief) if brief else None


@router.post(
    "/{project_id}/sources/analyze",
    response_model=SourceBriefOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def analyze_sources(
    project_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_ATTACHMENTS_UPLOAD)),
):
    """Read the whole data room and store a structured project brief.

    Runs in the background: the page polls GET .../sources/brief until the
    status turns ready or failed.
    """
    project = get_project_or_404(db, project_id)
    sources, _texts = project_texts(db, project.id)
    if not sources:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload the raw data first - the data room is empty.",
        )
    if not any(s.text_chars for s in sources):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "None of the uploaded files could be read (scanned images or "
                "drawings). Upload a text-based document or the Excel row data."
            ),
        )
    last = db.scalars(
        select(SourceBrief)
        .where(SourceBrief.project_id == project.id)
        .order_by(SourceBrief.id.desc())
    ).first()
    brief = SourceBrief(
        project_id=project.id,
        version=(last.version + 1) if last else 1,
        status="running",
        created_by_id=user.id,
    )
    db.add(brief)
    workflow.log_action(
        db, user, "source:analyze", project, {"version": brief.version}
    )
    db.commit()
    db.refresh(brief)
    background.add_task(_run_analysis, brief.id, project.id)
    return SourceBriefOut.model_validate(brief)


def _run_analysis(brief_id: int, project_id: int) -> None:
    """Background worker: read the room, ask the model, store the brief."""
    db = SessionLocal()
    try:
        brief = db.get(SourceBrief, brief_id)
        project = db.get(Project, project_id)
        if brief is None or project is None:
            return
        sources, texts = project_texts(db, project_id)
        brief.model = getattr(provider, "DEFAULT_MODEL", None) or brief.model
        try:
            payload = brief_ai.run_brief(project, sources, texts)
        except Exception as exc:  # noqa: BLE001 - recorded on the brief
            brief.status = "failed"
            brief.error = str(exc)[:2000]
            brief.finished_at = _now()
            db.commit()
            return
        brief.payload = payload
        brief.status = "ready"
        brief.finished_at = _now()
        db.commit()
    finally:
        db.close()


@sources_router.get("/taxonomy")
def taxonomy(_user: User = Depends(get_current_user)):
    """The folder taxonomy and document types the data room files by."""
    return {
        "taxonomy": list(source_extract.TAXONOMY),
        "doc_types": list(source_extract.DOC_TYPES),
    }


@sources_router.get("/{source_id}/text")
def source_text(
    source_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The extracted text of one source document (for the reviewer)."""
    source = db.get(SourceDocument, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source document not found"
        )
    return {
        "id": source.id,
        "filename": source.filename,
        "doc_type": source.doc_type,
        "category": source.category,
        "text": read_text(source),
        "note": source.extraction_note,
    }


@sources_router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_ATTACHMENTS_UPLOAD)),
):
    source = db.get(SourceDocument, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source document not found"
        )
    project = db.get(Project, source.project_id)
    for candidate in (source.stored_path, source.text_path):
        if candidate:
            Path(candidate).unlink(missing_ok=True)
    workflow.log_action(
        db,
        user,
        "source:delete",
        project,
        {"filename": source.filename},
    )
    db.delete(source)
    db.commit()
