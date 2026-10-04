"""The EAR / Design / Procore boards.

One endpoint serves all three: a phase name selects the projects, and every
row carries what the board is for - the MOM and Project Summary states, whose
court the project is in, the next action, the owner, the follow-up note and
the design dates. Counts come back with the rows so the tiles need no second
request.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import get_current_user
from ..db import get_db
from ..models import MomRecord, Project, User
from ..services.court import DOC_STATUSES, project_court
from .projects import _derive_tracker_fields

router = APIRouter(prefix="/boards", tags=["boards"])

#: phase -> how a project belongs to it. The Planner bucket is the primary
#: signal (it is what the Planner moves), with the workflow stage as the
#: fallback for projects that were re-staged by hand.
_PHASES: dict[str, dict[str, Any]] = {
    "ear": {
        "title": "EAR",
        "buckets": {"EAR"},
        "stage_prefixes": ("EAR_",),
    },
    "design": {
        "title": "Design",
        "buckets": {"DESIGN"},
        "stage_prefixes": ("SOW_", "MTO_"),
    },
    "procore": {
        "title": "Procore",
        "buckets": {"PROCORE"},
        "stage_prefixes": ("PROCUREMENT",),
    },
}


def _in_phase(project: Project, phase: dict[str, Any]) -> bool:
    if (project.planner_bucket or "").upper() in phase["buckets"]:
        return True
    return any(
        (project.stage or "").startswith(prefix)
        for prefix in phase["stage_prefixes"]
    )


def _row(project: Project, mom: MomRecord | None) -> dict[str, Any]:
    derived = _derive_tracker_fields(project)
    state = project_court(project, mom.status if mom else None)
    return {
        "id": project.id,
        "pr_number": project.pr_number,
        "title": project.title,
        "stage": project.stage,
        "pi_name": project.pi_name,
        "pi_email": project.pi_email,
        "location": project.location,
        "owner_username": project.owner_username,
        "followup_note": project.followup_note,
        "mom_status": mom.status if mom else None,
        "summary_status": project.summary_status,
        "start_date": derived.get("start_date"),
        "finish_date": derived.get("finish_date"),
        "assigned_to": derived.get("assigned_to"),
        **state,
    }


@router.get("/{phase}")
def board(
    phase: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    spec = _PHASES.get(phase.lower())
    if spec is None:
        raise HTTPException(
            404, f"Unknown board {phase!r}. Valid: {sorted(_PHASES)}"
        )

    projects = db.scalars(select(Project)).all()
    moms = {
        mom.project_id: mom
        for mom in db.scalars(select(MomRecord)).all()
    }

    # Live rows only: a PR that left the newest Planner export left this
    # phase too. The snapshot is computed once for the whole register.
    derived_all = {p.id: _derive_tracker_fields(p) for p in projects}
    snapshot = max(
        (d["planner_sync_date"] for d in derived_all.values()
         if d["planner_sync_date"]),
        default=None,
    )
    rows = []
    for project in projects:
        sync = derived_all[project.id]["planner_sync_date"]
        if sync is not None and snapshot and sync != snapshot:
            continue
        if not _in_phase(project, spec):
            continue
        rows.append(_row(project, moms.get(project.id)))

    counts = {
        "total": len(rows),
        "my_court": sum(1 for r in rows if r["my_court"]),
        "mom_sent": sum(1 for r in rows if r["mom"]["status"] == "sent"),
        "mom_pending_send": sum(
            1 for r in rows if r["mom"]["status"] in ("none", "draft")
        ),
        "mom_acknowledged": sum(
            1 for r in rows if r["mom"]["status"] == "acknowledged"
        ),
        "summary_sent": sum(1 for r in rows if r["summary"]["status"] == "sent"),
        "summary_pending_send": sum(
            1 for r in rows if r["summary"]["status"] in ("none", "draft")
        ),
        "summary_acknowledged": sum(
            1 for r in rows if r["summary"]["status"] == "acknowledged"
        ),
    }
    return {
        "phase": phase.lower(),
        "title": spec["title"],
        "counts": counts,
        "rows": rows,
    }
