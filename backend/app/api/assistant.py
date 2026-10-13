"""The Project Delivery Assistant (/api/projects/{project_id}/assistant).

The conversational front door to the app's own generators. Two steps, on
purpose:

* POST /message  - records what the team pasted and proposes ONE allowed action
                   (nothing else is written; the model may not pick a blocked
                   or invented step);
* POST /run      - executes one action and writes the MOM / assessment / EAR /
                   SOW / BOQ / drawing list / binder / MTO through the existing
                   generators, then answers with the artifacts and the new gate.

The gates are the pipeline's own rules (app/api/pipeline.py), so a request that
skips a gate is refused with 409 and the same sentence the pipeline panel shows.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..ai import provider
from ..core.rbac import (
    CAP_PROJECTS_EDIT,
    effective_permissions,
    get_current_user,
    require_capability,
)
from ..db import get_db
from ..models import AssistantMessage, User
from ..schemas import (
    AssistantMessageIn,
    AssistantRunIn,
    AssistantStateOut,
    AssistantTurnOut,
)
from ..services import assistant_orchestrator as assistant
from ..services import workflow
from .projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/assistant", tags=["assistant"])


def _require_action_capability(user: User, action_id: str) -> None:
    """The reused generators check nothing themselves, so the gate is here."""
    needed = assistant.capability_for(action_id)
    if needed and needed not in effective_permissions(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission: " + needed,
        )


def _require_provider() -> None:
    ok, reason = provider.available()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=reason or "The AI provider is offline. Set the provider and its key in Settings.",
        )


@router.get("", response_model=AssistantStateOut)
def assistant_state(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The stage ribbon, the gate, the EAR track, the action list and the transcript."""
    project = get_project_or_404(db, project_id)
    return AssistantStateOut(
        project_id=project.id,
        pr_number=project.pr_number,
        pipeline=assistant.pipeline_state(db, project),
        gate=assistant.gate(db, project),
        ear=assistant.ear_state(db, project),
        actions=assistant.action_catalog(),
        ai=assistant.ai_status(),
        transcript=assistant.transcript(db, project),
    )


@router.post("/message", response_model=AssistantTurnOut)
def assistant_message(
    project_id: int,
    body: AssistantMessageIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    """Paste notes or instructions; get the one step that should run next."""
    project = get_project_or_404(db, project_id)
    if not (body.message or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The message is empty."
        )
    _require_provider()
    return AssistantTurnOut(**assistant.propose(
        db, project, user, body.message, model=body.model, provider_id=body.provider
    ))


@router.post("/run", response_model=AssistantTurnOut)
def assistant_run(
    project_id: int,
    body: AssistantRunIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    """Execute one action. 409 with the pipeline's own sentence when blocked."""
    project = get_project_or_404(db, project_id)
    action_id = (body.action or "").strip()
    if action_id not in assistant.ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown action. Valid: " + ", ".join(sorted(assistant.ACTIONS)),
        )
    _require_action_capability(user, action_id)
    if assistant.ACTIONS[action_id].writer is not None:
        _require_provider()
    try:
        result = assistant.run_action(
            db, project, user, action_id, note=body.note, model=body.model,
            provider_id=body.provider,
        )
    except assistant.GateBlocked as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.reason)
    return AssistantTurnOut(**result)


@router.get("/messages", response_model=list[AssistantTurnOut])
def assistant_messages(
    project_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The transcript, oldest first."""
    project = get_project_or_404(db, project_id)
    return [
        AssistantTurnOut(**row)
        for row in assistant.transcript(db, project, limit=limit, offset=offset)
    ]


@router.delete("/messages", status_code=status.HTTP_204_NO_CONTENT)
def assistant_reset(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    """Clear the transcript (the documents the assistant produced stay)."""
    project = get_project_or_404(db, project_id)
    db.query(AssistantMessage).filter(AssistantMessage.project_id == project.id).delete()
    workflow.log_action(db, user, "assistant:reset", project, {})
    db.commit()
    return None


@router.get("/actions")
def assistant_actions(_user: User = Depends(get_current_user)):
    """The registry the UI renders: id, label, track, stage, panel, capability."""
    return assistant.action_catalog()
