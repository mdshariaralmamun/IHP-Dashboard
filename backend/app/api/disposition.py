"""Disposition decision endpoint: classify PR as ICR or PROJECT (/api/projects/{id}/disposition).

- ICR path: routes straight to MTO generation (skips EAR & SOW).
- PROJECT path: proceeds through EAR -> SOW revisions -> BOQ/MTO.

All stage changes go through the workflow state machine so the audit log
records every transition and an invalid move is rejected with 409.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..core.rbac import CAP_DISPOSITION_MANAGE, require_capability
from ..db import get_db
from ..models import Project, User
from ..schemas import DispositionUpdate, ProjectDetail
from ..services import workflow
from .projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/disposition", tags=["disposition"])


@router.post("", response_model=ProjectDetail)
def set_project_disposition(
    project_id: int,
    body: DispositionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_DISPOSITION_MANAGE)),
):
    """Set project disposition to ICR or PROJECT and branch the workflow accordingly."""
    project = get_project_or_404(project_id, db)
    project.disposition = body.disposition

    target_stage = (
        workflow.MTO_DRAFT if body.disposition == "ICR" else workflow.EAR_DRAFT
    )
    branch_action = f"disposition:{body.disposition}"
    branch_detail = {
        "disposition": body.disposition,
        "justification": body.justification,
        "new_stage": target_stage,
    }

    # Walk through the state machine: an intermediate DISPOSITION step is
    # only inserted when the project's current stage can't jump straight to
    # the branch target. For ICR coming from INTAKE/MOM_SENT, MTO_DRAFT is
    # a direct legal transition so we skip the intermediate stop.
    try:
        current = project.stage
        if current == target_stage:
            # No stage change — just record the disposition itself.
            workflow.log_action(db, user, branch_action, project, branch_detail)
        elif (
            current in (workflow.INTAKE, workflow.MOM_SENT, workflow.MOM_CONFIRMED)
            and target_stage == workflow.MTO_DRAFT
        ):
            # ICR short-circuit: direct transition (state machine allows it
            # from INTAKE / MOM_SENT / MOM_CONFIRMED) and audit the disposition.
            workflow.transition(project, target_stage, user, db, branch_detail, action=branch_action)
        else:
            # PROJECT branch: stage through DISPOSITION first, then to EAR_DRAFT.
            if current != workflow.DISPOSITION:
                workflow.transition(project, workflow.DISPOSITION, user, db)
            workflow.transition(project, target_stage, user, db, branch_detail, action=branch_action)
    except workflow.WorkflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot apply disposition from stage {project.stage}: {exc}",
        ) from exc

    db.commit()
    db.refresh(project)
    return project
