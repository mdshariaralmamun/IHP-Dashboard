"""Stage 6 Construction execution endpoints (/api/projects/{id}/construction).

Per v2 spec Section 2: only the PROJECT branch reaches this stage. ICR
projects never create a ConstructionRecord.

This is the load-bearing endpoint for:
  - WCF / Work Permit tracking (wcf_data JSON column)
  - Trade-wise execution assignment chart (schedule_data JSON column)
  - Construction lifecycle status (planned -> in_progress -> completed)

The router also serves the cross-project construction dashboard at
``/api/construction/dashboard`` and the per-stage project rollups under
``/api/construction/projects``.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.rbac import (
    CAP_CONSTRUCTION_MANAGE,
    CAP_WORK_PERMIT_MANAGE,
    get_current_user,
    require_capability,
)
from ..db import get_db
from ..models import BoqMtoItem, ConstructionRecord, Project, User
from ..schemas import (
    ConstructionDashboardKpis,
    ConstructionOut,
    ConstructionProjectSummary,
    ConstructionUpdate,
)
from ..services import workflow
from .projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/construction", tags=["construction"])


def _require_project_branch(project: Project) -> None:
    """ICR-classified projects never reach this stage; guard at the door."""
    if project.disposition == "ICR":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ICR-classified projects do not have a construction record; "
            "they follow the MTO -> Project Control -> EAT hand-off flow.",
        )


def _get_or_create(project: Project, db: Session, user: User) -> ConstructionRecord:
    _require_project_branch(project)
    if project.construction is not None:
        return project.construction
    rec = ConstructionRecord(
        project_id=project.id,
        status="planned",
        updated_by_id=user.id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.get("", response_model=ConstructionOut)
def get_construction(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    return _get_or_create(project, db, user)


@router.patch("", response_model=ConstructionOut)
def update_construction(
    project_id: int,
    body: ConstructionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_CONSTRUCTION_MANAGE)),
):
    project = get_project_or_404(db, project_id)
    rec = _get_or_create(project, db, user)
    if body.status is not None:
        rec.status = body.status
        if body.status == "in_progress" and rec.started_at is None:
            rec.started_at = datetime.now(timezone.utc)
        if body.status == "completed" and rec.completed_at is None:
            rec.completed_at = datetime.now(timezone.utc)
    if body.schedule_data is not None:
        rec.schedule_data = body.schedule_data
    if body.wcf_data is not None:
        rec.wcf_data = body.wcf_data
    rec.updated_by_id = user.id
    rec.updated_at = datetime.now(timezone.utc)
    workflow.log_action(
        db, user, f"construction:update:{body.status or 'metadata'}", project,
        {"status": body.status, "wcf_updated": body.wcf_data is not None,
         "schedule_updated": body.schedule_data is not None},
    )
    db.commit()
    db.refresh(rec)
    return rec


@router.post("/work-permit", response_model=ConstructionOut)
def record_work_permit(
    project_id: int,
    body: dict | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_WORK_PERMIT_MANAGE)),
):
    """Mark the WCF / work permit as filed for this project.

    Accepts an optional body whose fields are merged into construction.wcf_data
    (e.g. ``{"permit_number": "WCF-2026-0042", "notes": "..."}``) so the
    permit number and filing notes land on the record. ``filed_at`` and
    ``filed_by`` are always stamped; the user cannot spoof them.
    """
    project = get_project_or_404(db, project_id)
    rec = _get_or_create(project, db, user)
    wcf = dict(rec.wcf_data or {})
    if isinstance(body, dict):
        for key, value in body.items():
            if key in {"filed_at", "filed_by"}:
                # These are server-stamped; user input is ignored.
                continue
            wcf[key] = value
    wcf["filed_at"] = datetime.now(timezone.utc).isoformat()
    wcf["filed_by"] = user.username
    rec.wcf_data = wcf
    rec.updated_by_id = user.id
    rec.updated_at = datetime.now(timezone.utc)
    workflow.log_action(
        db, user, "construction:work_permit_filed", project, wcf
    )
    db.commit()
    db.refresh(rec)
    return rec


# ---------- Cross-project construction dashboard ----------
#
# Aggregates that power /dashboard/construction. Sourced from existing models
# (Project, ConstructionRecord, BoqMtoItem) so we don't invent a separate
# dashboard schema. ICR projects are excluded: their lifecycle ends at
# ICR_DONE without ever entering procurement, work-permit, or construction.

dashboard_router = APIRouter(prefix="/construction", tags=["construction_dashboard"])


@dashboard_router.get("/dashboard", response_model=ConstructionDashboardKpis)
def get_dashboard_kpis(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Roll-up KPIs for the construction dashboard.

    Counts only PROJECT-classified projects. A project is "in construction"
    once it has a ConstructionRecord, BOQ line items, or a WCF filing —
    regardless of its current workflow stage — since those artifacts are
    the only things the construction team actually works on.
    """
    project_class_projects = db.scalars(
        select(Project).where(Project.disposition != "ICR")
    ).all()
    project_ids = [p.id for p in project_class_projects]

    # Projects with any construction-side artifact: a construction record,
    # a WCF filing, or at least one design BOQ line. ICR projects are
    # excluded entirely.
    active_construction = 0
    active_permits = 0
    for p in project_class_projects:
        construction = p.construction
        wcf = (construction.wcf_data or {}) if construction else {}
        has_wcf = bool(wcf.get("filed_at"))
        if construction is not None and construction.status in (
            "planned",
            "in_progress",
        ):
            active_construction += 1
        if has_wcf:
            active_permits += 1
            # Filing a WCF also implies the project is on the construction
            # radar, even if no ConstructionRecord exists yet.
            if construction is None:
                active_construction += 1

    boq_rows = (
        db.scalars(
            select(BoqMtoItem).where(
                BoqMtoItem.project_id.in_(project_ids),
                BoqMtoItem.mto_kind == "design",
            )
        ).all()
        if project_ids
        else []
    )
    total_materials = len(boq_rows)
    materials_delivered = sum(
        1 for b in boq_rows if b.delivery_status in ("delivered", "installed")
    )
    delivery_rate = (
        (materials_delivered / total_materials) * 100.0
        if total_materials
        else 0.0
    )

    return ConstructionDashboardKpis(
        total_projects=db.scalar(select(func.count()).select_from(Project)) or 0,
        active_construction_projects=active_construction,
        total_materials_tracked=total_materials,
        materials_delivered=materials_delivered,
        active_work_permits=active_permits,
        delivery_rate=delivery_rate,
    )


@dashboard_router.get(
    "/projects", response_model=list[ConstructionProjectSummary]
)
def list_dashboard_projects(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Per-project summary cards for the construction dashboard.

    Includes every PROJECT-classified project (any stage) plus the
    in-progress construction metrics from the project's ConstructionRecord
    and BoqMtoItem rows.
    """
    projects = db.scalars(
        select(Project)
        .where(Project.disposition != "ICR")
        .order_by(Project.id)
    ).all()
    if not projects:
        return []

    project_ids = [p.id for p in projects]
    construction_by_pid = {
        c.project_id: c
        for c in db.scalars(
            select(ConstructionRecord).where(
                ConstructionRecord.project_id.in_(project_ids)
            )
        ).all()
    }
    boq_by_pid: dict[int, list[BoqMtoItem]] = {}
    for row in db.scalars(
        select(BoqMtoItem).where(
            BoqMtoItem.project_id.in_(project_ids),
            BoqMtoItem.mto_kind == "design",
        )
    ).all():
        boq_by_pid.setdefault(row.project_id, []).append(row)

    summaries: list[ConstructionProjectSummary] = []
    for p in projects:
        boq = boq_by_pid.get(p.id, [])
        delivered = sum(
            1 for b in boq if b.delivery_status in ("delivered", "installed")
        )
        wcf = (
            (construction_by_pid[p.id].wcf_data or {})
            if p.id in construction_by_pid
            else {}
        )
        summaries.append(
            ConstructionProjectSummary(
                id=p.id,
                pr_number=p.pr_number,
                title=p.title,
                stage=p.stage,
                location=p.location,
                pi_name=p.pi_name,
                disposition=p.disposition,
                created_at=p.created_at,
                # Permits: surfaced as the count of WCF filings the project
                # has recorded. Today the schema allows exactly one WCF
                # entry per ConstructionRecord, so the count is 0 or 1;
                # counts in the future if a project ever needs multiple
                # (e.g. parallel hot/cold work).
                permits_count=1 if wcf.get("filed_at") else 0,
                active_permits_count=1 if wcf.get("filed_at") else 0,
                materials_count=len(boq),
                materials_delivered_count=delivered,
                # Team headcount: a true ConstructionTeamMember table is
                # not part of the v1 model. We surface the construction
                # record's existence (0 or 1) as a stand-in so the dashboard
                # does not show a misleading zero everywhere.
                team_count=1 if p.id in construction_by_pid else 0,
            )
        )
    return summaries
