"""The next step, the to-do list and cancellation - one place per PR.

Every PR gets exactly one **next step**: which lifecycle stage comes next
(MTO, EAR, Design, Procore, PTW/WICF, Construction, Shutdown, Quality
Inspection, WCC, WCH - or ICR for the equipment branch), which follow-up
bucket it lives in, who owns it and when it is due. The steps that get it
there are ordinary to-do rows, so the team keeps one list per PR and one
global list across the whole register.

Cancelling is terminal and gets its own record: a short reason, a written
justification and the email the PI was sent (or the draft to send), because
the PI re-initiates under a NEW PR rather than reopening this one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import CAP_PROJECTS_EDIT, get_current_user, require_capability
from ..db import get_db
from ..models import Project, ProjectTodo, User
from ..schemas import (
    CancelInput,
    CancelResult,
    NextStepInput,
    NextStepOut,
    TodoCreate,
    TodoOut,
    TodoRowOut,
    TodoUpdate,
)
from ..services import emailer, workflow
from .projects import get_project_or_404

router = APIRouter(prefix="/projects", tags=["planning"])
todos_router = APIRouter(prefix="/todos", tags=["todos"])

#: The follow-up buckets, in lifecycle order. The Planner's own buckets plus
#: the equipment-branch pair (MTO / ICR), so every task names the place the
#: team actually works it - the full-picture view groups by this.
FOLLOWUP_BUCKETS: tuple[str, ...] = (
    "MTO",
    "EAR",
    "DESIGN",
    "PROCORE",
    "PTW/WICF",
    "CONSTRUCTION",
    "SHUTDOWN",
    "QUALITY INSPECTION",
    "WCC",
    "WCH",
    "ICR",
)

_BUCKET_LOOKUP = {b.upper(): b for b in FOLLOWUP_BUCKETS}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _bucket(value: str | None) -> str | None:
    """Canonical bucket name, or 422 when it is not one we follow up in."""
    raw = _clean(value)
    if raw is None:
        return None
    canonical = _BUCKET_LOOKUP.get(raw.upper())
    if canonical is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown follow-up bucket {raw!r}. "
                f"Valid: {', '.join(FOLLOWUP_BUCKETS)}"
            ),
        )
    return canonical


def _todo_rows(db: Session, project_id: int) -> list[TodoOut]:
    rows = db.scalars(
        select(ProjectTodo)
        .where(ProjectTodo.project_id == project_id)
        .order_by(ProjectTodo.status, ProjectTodo.due_date, ProjectTodo.id)
    ).all()
    return [TodoOut.model_validate(t) for t in rows]


def _next_step(project: Project, todos: list[TodoOut]) -> NextStepOut:
    return NextStepOut(
        project_id=project.id,
        pr_number=project.pr_number,
        stage=project.stage,
        next_stage=project.next_stage,
        next_stage_bucket=project.next_stage_bucket,
        next_stage_date=project.next_stage_date,
        next_stage_owner=project.next_stage_owner,
        next_step_note=project.next_step_note,
        cancel_reason=project.cancel_reason,
        cancel_justification=project.cancel_justification,
        cancel_notified_at=project.cancel_notified_at,
        todos=todos,
    )


@router.get("/{project_id}/next-step", response_model=NextStepOut)
def get_next_step(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The PR's next step plus every to-do row filed under it."""
    project = get_project_or_404(db, project_id)
    return _next_step(project, _todo_rows(db, project.id))


@router.put("/{project_id}/next-step", response_model=NextStepOut)
def set_next_step(
    project_id: int,
    body: NextStepInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    """Schedule (or execute) the PR's next step.

    Fields are PATCH-style: only what is sent is written, so the panel can
    save one control at a time. With move_now the project is walked into
    next_stage through the workflow - an illegal hop answers 409 with the
    workflow's own explanation, exactly like the stage panel.
    """
    project = get_project_or_404(db, project_id)
    data = body.model_dump(exclude_unset=True)

    if "next_stage" in data:
        target = _clean(data["next_stage"])
        if target is not None and target not in workflow.STAGES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown stage {target!r}. Valid: {', '.join(workflow.STAGES)}",
            )
        project.next_stage = target

    if "next_stage_bucket" in data:
        project.next_stage_bucket = _bucket(data["next_stage_bucket"])
    if "next_stage_date" in data:
        project.next_stage_date = _clean(data["next_stage_date"])
    if "next_stage_owner" in data:
        project.next_stage_owner = _clean(data["next_stage_owner"])
    if "next_step_note" in data:
        project.next_step_note = _clean(data["next_step_note"])

    moved_to: str | None = None
    if body.move_now and body.next_stage:
        if (
            project.disposition == "ICR"
            and body.next_stage in workflow.PROJECT_ONLY_STAGES
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ICR-classified projects route through the ICR branch, not "
                f"{body.next_stage}.",
            )
        try:
            workflow.transition(
                project,
                body.next_stage,
                user,
                db,
                detail={
                    "justification": _clean(body.justification)
                    or _clean(project.next_step_note)
                    or "next step",
                    "from": "next-step",
                },
                action="stage:next-step",
            )
        except workflow.WorkflowError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        moved_to = project.stage
        # The plan was carried out: clear the scheduled stage/date so the
        # panel does not show the move that already happened as still open.
        project.next_stage = None
        project.next_stage_date = None

    workflow.log_action(
        db,
        user,
        "next-step:update",
        project,
        {
            "next_stage": project.next_stage,
            "bucket": project.next_stage_bucket,
            "date": project.next_stage_date,
            "owner": project.next_stage_owner,
            "moved_to": moved_to,
        },
    )
    db.commit()
    db.refresh(project)
    return _next_step(project, _todo_rows(db, project.id))


@router.post(
    "/{project_id}/todos",
    response_model=TodoOut,
    status_code=status.HTTP_201_CREATED,
)
def create_todo(
    project_id: int,
    body: TodoCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    """Add one to-do row to a PR (bucket + optional owner and due date)."""
    project = get_project_or_404(db, project_id)
    title = _clean(body.title)
    if title is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A to-do needs a title.",
        )
    todo = ProjectTodo(
        project_id=project.id,
        bucket=_bucket(body.bucket) or project.next_stage_bucket,
        title=title[:300],
        stage=_clean(body.stage),
        assignee_username=_clean(body.assignee_username),
        due_date=_clean(body.due_date),
        note=_clean(body.note),
        status="open",
        created_by_id=user.id,
    )
    db.add(todo)
    workflow.log_action(
        db,
        user,
        "todo:create",
        project,
        {"title": todo.title, "bucket": todo.bucket, "assignee": todo.assignee_username},
    )
    db.commit()
    db.refresh(todo)
    return todo


@todos_router.patch("/{todo_id}", response_model=TodoOut)
def update_todo(
    todo_id: int,
    body: TodoUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    """Edit a to-do, or tick it off / reopen it."""
    todo = db.get(ProjectTodo, todo_id)
    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="To-do not found"
        )
    project = db.get(Project, todo.project_id)
    data = body.model_dump(exclude_unset=True)

    if "title" in data and _clean(data["title"]):
        todo.title = _clean(data["title"])[:300]
    if "bucket" in data:
        todo.bucket = _bucket(data["bucket"])
    if "stage" in data:
        todo.stage = _clean(data["stage"])
    if "assignee_username" in data:
        todo.assignee_username = _clean(data["assignee_username"])
    if "due_date" in data:
        todo.due_date = _clean(data["due_date"])
    if "note" in data:
        todo.note = _clean(data["note"])
    if data.get("status"):
        todo.status = data["status"]
        if todo.status == "done":
            todo.completed_at = _now()
            todo.completed_by_id = user.id
        else:
            todo.completed_at = None
            todo.completed_by_id = None

    workflow.log_action(
        db,
        user,
        "todo:update",
        project,
        {"todo_id": todo.id, "fields": sorted(data), "status": todo.status},
    )
    db.commit()
    db.refresh(todo)
    return todo


@todos_router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    todo = db.get(ProjectTodo, todo_id)
    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="To-do not found"
        )
    project = db.get(Project, todo.project_id)
    workflow.log_action(
        db, user, "todo:delete", project, {"todo_id": todo.id, "title": todo.title}
    )
    db.delete(todo)
    db.commit()


@todos_router.get("/buckets")
def followup_buckets(_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """The buckets the to-do list groups by, in lifecycle order."""
    return {"buckets": list(FOLLOWUP_BUCKETS)}


@todos_router.get("")
def list_todos(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    assignee: str | None = Query(None, description="Exact assignee username"),
    bucket: str | None = Query(None, description="Follow-up bucket"),
    status_filter: str = Query(
        "open", alias="status", description="open | done | all"
    ),
    mine: bool = Query(False, description="Only rows assigned to me"),
    project_id: int | None = Query(None),
    q: str | None = Query(None, description="Search title, note, PR or project title"),
):
    """The full-picture to-do list across every PR.

    Rows carry their project context (PR number, title, stage, disposition and
    the project's scheduled next stage) so the board can be read without
    opening each PR.
    """
    stmt = select(ProjectTodo, Project).join(
        Project, ProjectTodo.project_id == Project.id
    )
    if status_filter in ("open", "done"):
        stmt = stmt.where(ProjectTodo.status == status_filter)
    if assignee:
        stmt = stmt.where(ProjectTodo.assignee_username == assignee)
    if mine:
        stmt = stmt.where(ProjectTodo.assignee_username == user.username)
    if bucket:
        stmt = stmt.where(ProjectTodo.bucket == _bucket(bucket))
    if project_id:
        stmt = stmt.where(ProjectTodo.project_id == project_id)
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            ProjectTodo.title.ilike(needle)
            | Project.title.ilike(needle)
            | Project.pr_number.ilike(needle)
        )

    rows = db.execute(
        stmt.order_by(
            ProjectTodo.status,
            ProjectTodo.due_date.is_(None),
            ProjectTodo.due_date,
            ProjectTodo.id,
        )
    ).all()

    today = _now().date().isoformat()
    out: list[TodoRowOut] = []
    for todo, project in rows:
        payload = {
            column.name: getattr(todo, column.name)
            for column in ProjectTodo.__table__.columns
        }
        payload.update(
            {
                "pr_number": project.pr_number,
                "project_title": project.title,
                "project_stage": project.stage,
                "project_disposition": project.disposition,
                "project_next_stage": project.next_stage,
            }
        )
        out.append(TodoRowOut.model_validate(payload))

    open_rows = [r for r in out if r.status != "done"]
    by_bucket: dict[str, int] = {}
    by_assignee: dict[str, int] = {}
    overdue = 0
    for row in open_rows:
        key = row.bucket or "(no bucket)"
        by_bucket[key] = by_bucket.get(key, 0) + 1
        who = row.assignee_username or "(unassigned)"
        by_assignee[who] = by_assignee.get(who, 0) + 1
        if row.due_date and row.due_date[:10] < today:
            overdue += 1

    return {
        "rows": [r.model_dump() for r in out],
        "buckets": list(FOLLOWUP_BUCKETS),
        "counts": {
            "total": len(out),
            "open": len(open_rows),
            "done": len(out) - len(open_rows),
            "overdue": overdue,
            "mine": sum(1 for r in open_rows if r.assignee_username == user.username),
            "by_bucket": by_bucket,
            "by_assignee": by_assignee,
        },
    }


@router.post("/{project_id}/cancel", response_model=CancelResult)
def cancel_project(
    project_id: int,
    body: CancelInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    """Cancel a PR: record why, keep the justification, tell the PI.

    Cancelling is terminal. The record is the reason (short), the written
    justification (what was actually decided and by whom) and the email the PI
    received - or the draft, when SMTP is not configured.
    """
    project = get_project_or_404(db, project_id)
    if project.stage == workflow.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{project.pr_number} is already cancelled.",
        )
    reason = _clean(body.reason)
    justification = _clean(body.justification)
    if reason is None or len(reason) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Give a short cancellation reason (at least 3 characters).",
        )
    if justification is None or len(justification) < 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Write the justification (at least 10 characters) - it is the "
            "record of the decision.",
        )

    project.cancel_reason = reason[:200]
    project.cancel_justification = justification
    try:
        workflow.transition(
            project,
            workflow.CANCELLED,
            user,
            db,
            detail={"reason": reason, "justification": justification},
            action="project:cancel",
        )
    except workflow.WorkflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    subject, text = cancel_draft(project, reason, justification)
    to = _clean(body.notify_email) or _clean(project.pi_email)
    emailed = False
    if body.send_email and to:
        emailed = emailer.send_email(to, subject, text)
        if emailed:
            project.cancel_notified_at = _now()

    workflow.log_action(
        db,
        user,
        "project:cancel:notify" if emailed else "project:cancel:record",
        project,
        {"reason": reason, "to": to, "emailed": emailed},
    )
    db.commit()
    db.refresh(project)
    return CancelResult(
        project_id=project.id,
        pr_number=project.pr_number,
        stage=project.stage,
        cancel_reason=project.cancel_reason,
        cancel_justification=project.cancel_justification,
        cancel_notified_at=project.cancel_notified_at,
        emailed=emailed,
        email_to=to,
        email_subject=subject,
        email_body=text,
    )


def cancel_draft(project: Project, reason: str, justification: str) -> tuple[str, str]:
    """The cancellation email: subject + plain-text body, sent or drafted."""
    subject = f"{emailer.pr_label(project)} - request cancelled ({reason})"
    body = (
        f"Dear {project.pi_name or 'Professor'},\n\n"
        f"{emailer.pr_label(project)} - {project.title}\n\n"
        "This request has been cancelled.\n\n"
        f"Reason: {reason}\n"
        f"Justification: {justification}\n\n"
        "If the work is still needed, it will be re-initiated under a new PR "
        "number through the usual request channel; this PR stays closed.\n\n"
        "Kind regards,\nIHP Design and Construction"
    )
    return subject, body
contacts_router = APIRouter(prefix="/contacts", tags=["contacts"])


@contacts_router.get("")
def list_contacts(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    q: str | None = Query(None, description="Search a name or an email"),
    limit: int = Query(500, ge=1, le=2000),
):
    """The PI / requester directory, derived from the register.

    Every PR names the person who owns it (`pi_name` + `pi_email`, or the
    Planner's Requestor line). Grouping those into one row per person gives
    the directory the TQ and EAR mail address - no separate list to maintain,
    and it can never drift from the register.
    """
    projects = db.scalars(select(Project).order_by(Project.id.desc())).all()
    # Grouped by the person, not by the row: the same PI owns several PRs and
    # only some of them carry the email, so the address is merged across their
    # projects instead of producing one contact per spelling.
    people: dict[str, dict[str, Any]] = {}
    for project in projects:
        name = (project.pi_name or "").strip()
        email = (project.pi_email or "").strip()
        if not name and not email:
            continue
        key = " ".join(name.lower().split()) or email.lower()
        entry = people.setdefault(
            key,
            {
                "name": name,
                "email": email,
                "project_count": 0,
                "active_count": 0,
                "projects": [],
            },
        )
        if email and not entry["email"]:
            entry["email"] = email
        if name and not entry["name"]:
            entry["name"] = name
        entry["project_count"] += 1
        if project.stage not in ("CLOSEOUT", "PUNCH_LIST", "ICR_DONE", "CANCELLED"):
            entry["active_count"] += 1
        entry["projects"].append(
            {
                "id": project.id,
                "pr_number": project.pr_number,
                "title": project.title,
                "stage": project.stage,
                "disposition": project.disposition,
            }
        )
    needle = (q or "").strip().lower()
    out = []
    for entry in people.values():
        if needle and needle not in entry["name"].lower() and needle not in entry["email"].lower():
            continue
        entry["projects"] = entry["projects"][:20]
        out.append(entry)
    out.sort(key=lambda e: (-e["active_count"], -e["project_count"], e["name"].lower()))
    return {
        "total": len(out),
        "with_email": sum(1 for e in out if e["email"]),
        "contacts": out[:limit],
    }
