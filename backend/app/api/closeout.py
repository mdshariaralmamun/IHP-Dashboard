"""Stage 7 Closeout endpoints (/api/projects/{id}/closeout).

Stub implementation that follows the existing schema. The full
construction-dashboard / punch-list UI work is part of Section 7 (UI
redesign); this router exists so the closeout stage is reachable and
testable.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import CAP_CLOSEOUT_MANAGE, get_current_user, require_capability
from ..db import get_db
from ..models import CloseoutRecord, Project, PunchListItem, User
from ..schemas import CloseoutOut, PunchListItemOut
from ..services import workflow
from .projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/closeout", tags=["closeout"])


def _require_project_branch(project: Project) -> None:
    if project.disposition == "ICR":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ICR-classified projects do not have a closeout record; "
            "their lifecycle ends at ICR_DONE.",
        )


def _get_or_create(project: Project, db: Session, user: User) -> CloseoutRecord:
    _require_project_branch(project)
    if project.closeout is not None:
        return project.closeout
    rec = CloseoutRecord(
        project_id=project.id,
        status="open",
        testing_commissioning_notes="",
        as_built_drawings_submitted=False,
        o_and_m_manuals_submitted=False,
        updated_by_id=user.id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.get("", response_model=CloseoutOut)
def get_closeout(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    return _get_or_create(project, db, user)


@router.patch("", response_model=CloseoutOut)
def update_closeout(
    project_id: int,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_CLOSEOUT_MANAGE)),
):
    project = get_project_or_404(db, project_id)
    rec = _get_or_create(project, db, user)
    for field in (
        "status",
        "testing_commissioning_notes",
        "as_built_drawings_submitted",
        "o_and_m_manuals_submitted",
        "warranty_provider",
        "warranty_notes",
        "client_signoff_by",
        "client_feedback",
    ):
        if field in body:
            setattr(rec, field, body[field])
    if "warranty_start_date" in body and body["warranty_start_date"]:
        rec.warranty_start_date = datetime.fromisoformat(body["warranty_start_date"])
    if "warranty_end_date" in body and body["warranty_end_date"]:
        rec.warranty_end_date = datetime.fromisoformat(body["warranty_end_date"])
    if "client_signoff_date" in body and body["client_signoff_date"]:
        rec.client_signoff_date = datetime.fromisoformat(body["client_signoff_date"])
    rec.updated_by_id = user.id
    rec.updated_at = datetime.now(timezone.utc)
    workflow.log_action(db, user, "closeout:update", project, body)
    db.commit()
    db.refresh(rec)
    return rec


# ---------- Punch list ----------

@router.post("/start-punch-list", response_model=CloseoutOut)
def start_punch_list(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_CLOSEOUT_MANAGE)),
):
    """Advance the project CLOSEOUT -> PUNCH_LIST once WCC/WCH is done.

    Handover defects found after WCC/WCH are tracked on the punch list;
    this flips the workflow stage so the tracker shows the Punch List step.
    """
    project = get_project_or_404(db, project_id)
    _require_project_branch(project)
    workflow.transition(project, workflow.PUNCH_LIST, user, db)
    rec = _get_or_create(project, db, user)
    db.commit()
    db.refresh(rec)
    return rec

@router.get("/punch-list", response_model=list[PunchListItemOut])
def list_punch_items(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List all punch-list items for the project's closeout."""
    project = get_project_or_404(db, project_id)
    _require_project_branch(project)
    rec = _get_or_create(project, db, _user)
    return db.scalars(
        select(PunchListItem)
        .where(PunchListItem.closeout_id == rec.id)
        .order_by(PunchListItem.id)
    ).all()


@router.post(
    "/punch-list",
    response_model=PunchListItemOut,
    status_code=status.HTTP_201_CREATED,
)
def add_punch_item(
    project_id: int,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_CLOSEOUT_MANAGE)),
):
    """Append a row to the project's punch list."""
    project = get_project_or_404(db, project_id)
    _require_project_branch(project)
    rec = _get_or_create(project, db, user)
    trade = (body.get("trade") or "").strip()
    description = (body.get("description") or "").strip()
    if not trade or not description:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="trade and description are required",
        )
    item = PunchListItem(
        project_id=project.id,
        closeout_id=rec.id,
        trade=trade,
        description=description,
        location=body.get("location") or "",
        severity=body.get("severity") or "minor",
        status="open",
        assigned_to=body.get("assigned_to") or None,
        due_date=(
            datetime.fromisoformat(body["due_date"])
            if body.get("due_date")
            else None
        ),
    )
    db.add(item)
    workflow.log_action(
        db, user, "closeout:punch_item_added", project,
        {"trade": trade, "severity": item.severity},
    )
    db.commit()
    db.refresh(item)
    return item


@router.patch("/punch-list/{item_id}", response_model=PunchListItemOut)
def update_punch_item(
    project_id: int,
    item_id: int,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_CLOSEOUT_MANAGE)),
):
    """Update a punch-list item (status, severity, assignment, etc)."""
    project = get_project_or_404(db, project_id)
    _require_project_branch(project)
    item = db.get(PunchListItem, item_id)
    if not item or item.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Punch item not found"
        )
    for field in (
        "trade",
        "description",
        "location",
        "severity",
        "status",
        "assigned_to",
        "resolution_notes",
    ):
        if field in body:
            setattr(item, field, body[field])
    if "due_date" in body and body["due_date"]:
        item.due_date = datetime.fromisoformat(body["due_date"])
    if body.get("status") in ("resolved", "verified") and not item.resolved_at:
        item.resolved_at = datetime.now(timezone.utc)
    item.updated_at = datetime.now(timezone.utc)
    workflow.log_action(
        db, user, "closeout:punch_item_updated", project,
        {"item_id": item_id, "status": body.get("status")},
    )
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/punch-list/{item_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_punch_item(
    project_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_CLOSEOUT_MANAGE)),
):
    """Delete a punch-list item."""
    project = get_project_or_404(db, project_id)
    _require_project_branch(project)
    item = db.get(PunchListItem, item_id)
    if not item or item.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Punch item not found"
        )
    db.delete(item)
    workflow.log_action(
        db, user, "closeout:punch_item_deleted", project, {"item_id": item_id}
    )
    db.commit()
