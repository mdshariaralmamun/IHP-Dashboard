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

import shutil
import tempfile
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
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import brief as brief_ai
from ..ai import provider
from ..core.rbac import CAP_ATTACHMENTS_UPLOAD, get_current_user, require_capability
from ..db import SessionLocal, get_db
from ..models import Project, SourceBrief, SourceDocument, User
from ..schemas import SourceBriefOut, SourceDocumentOut, SourceRoomOut
from ..services import source_extract, storage, workflow
from .projects import _derive_tracker_fields, get_project_or_404

router = APIRouter(prefix="/projects", tags=["sources"])
sources_router = APIRouter(prefix="/sources", tags=["sources"])

#: Refuse absurd uploads (same ceiling as the attachment endpoint).
MAX_UPLOAD_BYTES = 60 * 1024 * 1024

#: Content types for the generated deliverables, so the browser handles them
#: as Word / Excel rather than as an unknown download.
REPORT_CONTENT_TYPES = {
    "Project Summary": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "Scope of Work": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "BOQ": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "Cost Estimate": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "MTO": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


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




@router.post("/{project_id}/sources/generate")
def generate_deliverables(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_ATTACHMENTS_UPLOAD)),
):
    """Build the project documents from the latest AI brief.

    Project Summary, Scope of Work, Bill of Quantities and the materials
    take-off are rendered from the team's own templates and attached to the PR
    as deliverables. Prices stay blank: the QS owns them.
    """
    from ..models import Attachment
    from ..services import template_docgen

    project = get_project_or_404(db, project_id)
    brief = db.scalars(
        select(SourceBrief)
        .where(SourceBrief.project_id == project.id)
        .order_by(SourceBrief.id.desc())
    ).first()
    if brief is None or brief.status != "ready" or not brief.payload:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run Analyze with AI first - the documents are built from it.",
        )
    payload = brief.payload
    derived = _derive_tracker_fields(project)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")

    # Project Budget step (between the MOM and the EAR summary): match every
    # line item against the Planner's price master. Only clear matches are
    # used; the rest stay empty for the QS.
    from ..services import price_master

    suggestions: dict[str, Any] = {}
    for item in payload.get("line_items") or []:
        if not isinstance(item, dict):
            continue
        match = price_master.suggest_price(
            db, item.get("description"), item.get("unit")
        )
        if match and match["unit_price"]:
            suggestions[template_docgen.line_key(item)] = match
    prices = {key: value["unit_price"] for key, value in suggestions.items()}
    work = Path(tempfile.mkdtemp(prefix="ihp-gen-"))
    jobs = (
        (
            "Project Summary",
            f"{project.pr_number} Project Summary {stamp}.docx",
            lambda out: template_docgen.generate_project_summary(
                project, payload, out, derived
            ),
        ),
        (
            "Scope of Work",
            f"{project.pr_number} Scope of Work {stamp}.docx",
            lambda out: template_docgen.generate_sow(project, payload, out),
        ),
        (
            "BOQ",
            f"{project.pr_number} BOQ {stamp}.xlsx",
            lambda out: template_docgen.generate_boq(project, payload, out),
        ),
        (
            "Cost Estimate",
            f"{project.pr_number} Cost Estimate {stamp}.xlsx",
            lambda out: template_docgen.generate_cost_estimate(
                project, payload, out, prices=prices
            ),
        ),
        (
            "MTO",
            f"{project.pr_number} MTO {stamp}.xlsx",
            lambda out: template_docgen.generate_boq_mto(project, payload, out),
        ),
    )
    generated = []
    try:
        for kind, filename, builder in jobs:
            try:
                path = builder(work / filename)
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Template missing: {exc}",
                ) from exc
            except Exception as exc:  # noqa: BLE001 - reported, never silent
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Could not generate the {kind}: {exc}",
                ) from exc
            data = path.read_bytes()
            stored_path, version = storage.store_upload(
                project.pr_number, "DELIVERABLE", filename, data
            )
            attachment = Attachment(
                project_id=project.id,
                stage="DELIVERABLE",
                filename=filename,
                stored_path=str(stored_path),
                content_type=REPORT_CONTENT_TYPES.get(kind),
                size_bytes=len(data),
                version=version,
                uploaded_by_id=user.id,
            )
            db.add(attachment)
            db.flush()
            generated.append(
                {
                    "kind": kind,
                    "filename": filename,
                    "attachment_id": attachment.id,
                    "size_bytes": len(data),
                    "download_url": (
                        f"/api/projects/{project.id}/attachments/"
                        f"{attachment.id}/download"
                    ),
                }
            )
    finally:
        shutil.rmtree(work, ignore_errors=True)

    workflow.log_action(
        db,
        user,
        "sources:generate",
        project,
        {
            "brief_version": brief.version,
            "documents": [entry["kind"] for entry in generated],
        },
    )
    db.commit()
    return {
        "project_id": project.id,
        "brief_version": brief.version,
        "documents": generated,
        "priced_lines": len(suggestions),
        "price_suggestions": suggestions,
    }


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


@router.get("/{project_id}/sources/mto")
def generate_icr_mto(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The materials take-off for a project with no SOW (the ICR branch).

    ICR work skips EAR/SOW, so the SOW-driven MTO generator has nothing to
    read. The take-off is built from the data room instead: the engineer's
    material list and the AI brief's line items - the same rows the BOQ is
    built from - written into the team's own MTO grid.
    """
    from fastapi.responses import FileResponse

    from ..services import template_docgen

    project = get_project_or_404(db, project_id)
    brief = db.scalars(
        select(SourceBrief)
        .where(SourceBrief.project_id == project.id)
        .order_by(SourceBrief.id.desc())
    ).first()
    if brief is None or brief.status != "ready" or not brief.payload:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Upload the material list (or the quotation) in the data room and "
                "run Analyze with AI first - the MTO is built from it."
            ),
        )
    out_dir = storage.project_dir(project.pr_number, "generated")
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{project.pr_number} MTO.xlsx"
    path = template_docgen.generate_boq_mto(project, brief.payload, out_dir / filename)
    workflow.log_action(
        db, _user, "docgen:mto-icr", project, {"file": filename, "brief": brief.version}
    )
    db.commit()
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )



class PickedMtoItem(BaseModel):
    description: str
    unit: str | None = None
    qty: str | float | int | None = None
    trade: str | None = None
    item_code: str | None = None


class PickedMtoIn(BaseModel):
    items: list[PickedMtoItem]


@router.post("/{project_id}/sources/mto-picked")
def generate_mto_from_picked(
    project_id: int,
    body: PickedMtoIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_ATTACHMENTS_UPLOAD)),
):
    """Build the materials take-off from rows picked out of the price master.

    The engineer searches the master, picks the rows and sets quantities; this
    writes them into the team's own MATERIALS TAKEOFF grid with the master rate
    where the row came from one. Nothing is invented: what was picked is what
    the workbook contains.
    """
    from fastapi.responses import FileResponse

    from ..services import template_docgen

    project = get_project_or_404(db, project_id)
    items = [item for item in body.items if (item.description or "").strip()]
    if not items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pick at least one material from the list first.",
        )
    payload = {
        "scope_by_trade": [],
        "line_items": [
            {
                "ref": item.item_code or str(index + 1),
                "trade": item.trade or "Plumbing",
                "description": item.description,
                "unit": item.unit,
                "qty": item.qty,
            }
            for index, item in enumerate(items)
        ],
    }
    out_dir = storage.project_dir(project.pr_number, "generated")
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{project.pr_number} MTO.xlsx"
    path = template_docgen.generate_boq_mto(project, payload, out_dir / filename)
    workflow.log_action(
        db,
        user,
        "docgen:mto-picked",
        project,
        {"file": filename, "items": len(items)},
    )
    db.commit()
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )



class DraftItemIn(BaseModel):
    description: str
    unit: str | None = None
    qty: str | None = None
    trade: str | None = None
    item_code: str | None = None
    unit_price: float | None = None


class MtoDraftIn(BaseModel):
    items: list[DraftItemIn]


def _draft_rows(db: Session, project_id: int):
    from ..models import MtoDraftItem

    return db.scalars(
        select(MtoDraftItem)
        .where(MtoDraftItem.project_id == project_id)
        .order_by(MtoDraftItem.position, MtoDraftItem.id)
    ).all()


def _draft_out(rows) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "position": row.position,
            "trade": row.trade,
            "description": row.description,
            "unit": row.unit,
            "qty": row.qty,
            "item_code": row.item_code,
            "unit_price": row.unit_price,
        }
        for row in rows
    ]


@router.get("/{project_id}/mto-draft")
def get_mto_draft(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The saved materials take-off draft for this project."""
    project = get_project_or_404(db, project_id)
    rows = _draft_rows(db, project.id)
    return {"project_id": project.id, "count": len(rows), "items": _draft_out(rows)}


@router.put("/{project_id}/mto-draft")
def save_mto_draft(
    project_id: int,
    body: MtoDraftIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_ATTACHMENTS_UPLOAD)),
):
    """Replace the saved draft with the rows currently being edited.

    A save is a whole-list replace: the picker is the single editor, so the
    list it holds IS the draft. Rows keep their id where the line survived, so
    nothing else that references a line is disturbed.
    """
    from ..models import MtoDraftItem

    project = get_project_or_404(db, project_id)
    existing = {row.id: row for row in _draft_rows(db, project.id)}
    kept: set[int] = set()
    for position, item in enumerate(body.items):
        description = (item.description or "").strip()
        if not description:
            continue
        row = existing.get(getattr(item, "database_id", None) or 0)
        if row is None:
            row = MtoDraftItem(project_id=project.id, created_by_id=user.id)
            db.add(row)
        row.position = position
        row.trade = (item.trade or "").strip() or None
        row.description = description
        row.unit = (item.unit or "").strip() or None
        row.qty = (item.qty or "").strip() or None
        row.item_code = (item.item_code or "").strip() or None
        row.unit_price = item.unit_price
        db.flush()
        kept.add(row.id)
    for row_id, row in existing.items():
        if row_id not in kept:
            db.delete(row)
    workflow.log_action(
        db, user, "mto-draft:save", project, {"lines": len(kept)}
    )
    db.commit()
    rows = _draft_rows(db, project.id)
    return {"project_id": project.id, "count": len(rows), "items": _draft_out(rows)}


@router.delete("/{project_id}/mto-draft", status_code=status.HTTP_204_NO_CONTENT)
def clear_mto_draft(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_ATTACHMENTS_UPLOAD)),
):
    """Delete the saved draft (the generated file stays attached)."""
    from ..models import MtoDraftItem

    project = get_project_or_404(db, project_id)
    removed = 0
    for row in _draft_rows(db, project.id):
        db.delete(row)
        removed += 1
    workflow.log_action(db, user, "mto-draft:clear", project, {"lines": removed})
    db.commit()

