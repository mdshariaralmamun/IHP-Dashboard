"""The five-stage IHP delivery pipeline (/api/projects/{id}/pipeline).

One row per stage per project is the single answer to "where is this PR?":

    1  Minutes of Meeting (MOM)
    2  Project Summary / EAR & Cost Estimate      (needs a confirmed MOM)
    3  Scope of Work package (SOW + BOQ + Drawings)
    4  Procore comments & revision                 (the submittal status lives here)
    5  Material Take-Off (MTO)                     (needs Procore approved)

The guard rules are enforced here, not in the panel, so no UI can skip a gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import CAP_PROJECTS_EDIT, get_current_user, require_capability
from ..db import get_db
from ..models import PipelineStage, User
from ..services import workflow
from .projects import get_project_or_404

router = APIRouter(prefix="/projects", tags=["pipeline"])

#: The five stages as the team describes them.
STAGES: dict[int, str] = {
    1: "Minutes of Meeting (MOM)",
    2: "Project Summary / EAR & Cost Estimate",
    3: "Scope of Work package (SOW + BOQ + Drawings)",
    4: "Procore Comments & Revisions",
    5: "Material Take-Off (MTO)",
}

#: What each stage may be set to. Stage 4 carries the Procore submittal status.
STAGE_STATUSES: dict[int, tuple[str, ...]] = {
    1: ("not_started", "in_progress", "awaiting_feedback", "confirmed"),
    2: ("not_started", "in_progress", "pending_approval", "approved"),
    3: ("not_started", "in_progress", "pending_approval", "approved"),
    4: ("not_started", "under_review", "revise_and_resubmit", "approved_as_noted", "approved"),
    5: ("not_started", "in_progress", "done"),
}

#: The Procore statuses that unlock the MTO.
PROCORE_APPROVED = ("approved", "approved_as_noted")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rows(db: Session, project_id: int) -> dict[int, PipelineStage]:
    rows = db.scalars(
        select(PipelineStage).where(PipelineStage.project_id == project_id)
    ).all()
    by_stage = {row.stage: row for row in rows}
    created = False
    for stage in STAGES:
        if stage not in by_stage:
            row = PipelineStage(project_id=project_id, stage=stage, status="not_started")
            db.add(row)
            by_stage[stage] = row
            created = True
    if created:
        db.commit()
        for row in by_stage.values():
            db.refresh(row)
    return by_stage


def blocked_reason(by_stage: dict[int, PipelineStage], stage: int) -> str | None:
    """Why this stage may not start yet, or None when it may."""
    if stage == 2:
        first = by_stage[1].status
        if first not in ("confirmed",):
            return "Confirm the MOM first (Stage 1) - feedback recorded or no changes."
    if stage == 3:
        if by_stage[2].status not in ("approved", "pending_approval"):
            return "Stage 2 must be approved (or out for approval) before the SOW package."
    if stage == 4:
        if by_stage[3].status not in ("approved", "pending_approval"):
            return "Compile and issue the SOW package (Stage 3) before the Procore review."
    if stage == 5:
        if by_stage[4].status not in PROCORE_APPROVED:
            return "The MTO unlocks when Procore is Approved or Approved as Noted."
    return None


def _payload(by_stage: dict[int, PipelineStage]) -> dict[str, Any]:
    stages = []
    for stage, label in STAGES.items():
        row = by_stage[stage]
        stages.append(
            {
                "stage": stage,
                "label": label,
                "status": row.status,
                "note": row.note,
                "updated_at": row.updated_at,
                "allowed_statuses": list(STAGE_STATUSES[stage]),
                "blocked_reason": blocked_reason(by_stage, stage)
                if row.status == "not_started"
                else None,
            }
        )
    return {
        "stages": stages,
        "procore_status": by_stage[4].status,
        "mto_unlocked": by_stage[4].status in PROCORE_APPROVED,
        "current_stage": next(
            (s["stage"] for s in stages if s["status"] == "not_started"), 5
        ),
    }


@router.get("/{project_id}/pipeline")
def get_pipeline(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The five stages with their status, what is blocking, and the MTO gate."""
    project = get_project_or_404(db, project_id)
    return {"project_id": project.id, **_payload(_rows(db, project.id))}


class StageUpdate(BaseModel):
    status: str
    note: str | None = None


@router.post("/{project_id}/pipeline/{stage}/advance")
def set_stage(
    project_id: int,
    stage: int,
    body: StageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    """Set one stage's status (and the Procore status, on stage 4)."""
    project = get_project_or_404(db, project_id)
    if stage not in STAGES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="stage must be 1..5 - " + ", ".join(f"{k} {v}" for k, v in STAGES.items()),
        )
    wanted = (body.status or "").strip().lower()
    if wanted not in STAGE_STATUSES[stage]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"stage {stage} accepts: " + ", ".join(STAGE_STATUSES[stage]),
        )
    by_stage = _rows(db, project.id)
    reason = blocked_reason(by_stage, stage) if wanted != "not_started" else None
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)

    row = by_stage[stage]
    previous = row.status
    row.status = wanted
    if body.note is not None:
        row.note = (body.note or "").strip() or None
    row.updated_by_id = user.id
    workflow.log_action(
        db,
        user,
        "pipeline:stage",
        project,
        {"stage": stage, "from": previous, "to": wanted, "note": row.note},
    )
    db.commit()
    db.refresh(row)
    return {
        "project_id": project.id,
        "stage": stage,
        "status": row.status,
        **_payload(_rows(db, project.id)),
    }
