"""ICR branch endpoints (/api/projects/{id}/icr).

Per v2 spec Section 2A: ICR-classified projects route MTO -> Project Control
(orders materials) -> Equipment Assessment Team (install + follow-up). They
NEVER reach EAR, SOW, Procurement, WorkPermit, Construction, or Closeout.

This router records the ICR hand-off milestones on IcrHandoff rows. The
construction dashboard does not see these projects.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import CAP_ICR_HANDOFF, get_current_user, require_capability
from ..db import get_db
from ..models import IcrHandoff, Project, User
from ..schemas import IcrHandoffCreate, IcrHandoffOut
from ..services import workflow
from .projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/icr", tags=["icr"])


def _require_icr(project: Project) -> None:
    if project.disposition != "ICR":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ICR hand-offs only apply to ICR-classified projects.",
        )


@router.get("/handoffs", response_model=list[IcrHandoffOut])
def list_handoffs(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List the ICR hand-off milestones recorded for this project."""
    project = get_project_or_404(db, project_id)
    _require_icr(project)
    return db.scalars(
        select(IcrHandoff)
        .where(IcrHandoff.project_id == project.id)
        .order_by(IcrHandoff.recorded_at, IcrHandoff.id)
    ).all()


@router.post("/handoffs", response_model=IcrHandoffOut)
def record_handoff(
    project_id: int,
    body: IcrHandoffCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_ICR_HANDOFF)),
):
    """Record a hand-off milestone for the ICR branch.

    Common flow:
        mto_to_project_control -> materials_ordered -> materials_received
        -> eat_install_scheduled -> eat_installed -> follow_up -> closed

    Recording the `closed` milestone also moves the project stage to
    ICR_DONE (the ICR-branch terminal state) so the dashboard knows the
    project is finished.
    """
    project = get_project_or_404(db, project_id)
    _require_icr(project)

    entry = IcrHandoff(
        project_id=project.id,
        milestone=body.milestone,
        status=body.status,
        note=body.note,
        recorded_by_id=user.id,
    )
    db.add(entry)
    workflow.log_action(
        db,
        user,
        f"icr:handoff:{body.milestone}",
        project,
        {"milestone": body.milestone, "status": body.status},
    )

    if body.milestone == "closed":
        # Move the project to the ICR terminal stage. The workflow
        # transition() guard will also reject this if the project is
        # somehow mis-classified.
        try:
            workflow.transition(project, workflow.ICR_DONE, user, db)
        except workflow.WorkflowError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

    db.commit()
    db.refresh(entry)
    return entry
