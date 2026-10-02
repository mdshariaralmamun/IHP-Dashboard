"""Area-wise tracking: who is in a lab now, who was there, what ran there.

A location - a room code like 5-3610 or a shorthand like B5 L3 A1 - is the key
everything is grouped by. The register, the plan markers and the finished
stages together answer the questions that come up on site: which PI holds this
area now, who held it before, how many projects finished here and how many are
running.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import get_current_user
from ..db import get_db
from ..models import PlanMarker, Project, User
from ..services import reference
from .projects import _derive_tracker_fields

# Its own prefix, deliberately not under /projects: "area-report" would be
# swallowed by the /projects/{project_id} route declared before this one.
router = APIRouter(prefix="/areas", tags=["areas"])

#: Stages that mean the work in that area is over.
FINISHED_STAGES = {
    "CLOSEOUT", "PUNCH_LIST", "ICR_DONE", "TECH_LIBRARY", "CANCELLED",
}


def _matches(decoded: dict[str, Any], project: Project, location: str) -> bool:
    """Does this project belong to the decoded area?

    Building and level must agree. The area narrows when both sides state one;
    the room narrows by text, because a project's location is free text that
    names the room more often than it parses.
    """
    theirs = reference.decode_location(location)
    if not theirs or theirs["building"] != decoded["building"]:
        return False
    if theirs["level"] != decoded["level"]:
        return False
    if decoded["area"] is not None and theirs["area"] is not None:
        if theirs["area"] != decoded["area"]:
            return False
    if decoded["room"] and theirs["room"]:
        # Both sides name a room: they must name the same one.
        if decoded["room"] != theirs["room"]:
            return False
    # A room-code query also admits a loose/B-form location on the same
    # building and level: the site writes "5-3610" and "B5 L3 A1" for the
    # same area, and refusing one form would hide the other's projects.
    return True


@router.get("/report")
def area_report(
    location: str = Query(..., description="5-3610, or B5 L3 A1"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Everything the site knows about one area, in one answer."""
    decoded = reference.decode_location(location)
    if not decoded:
        return {
            "ok": False,
            "error": (
                f"Could not decode {location!r}. Use a room code (5-3610) or "
                "the shorthand (B5 L3 A1)."
            ),
        }

    scope = {"building": decoded["building"], "level": decoded["level"]}
    projects = db.scalars(select(Project)).all()

    active: list[dict[str, Any]] = []
    finished: list[dict[str, Any]] = []
    for project in projects:
        where = project.location or ""
        hit = _matches(decoded, project, where)
        markers = db.scalars(
            select(PlanMarker).where(PlanMarker.project_id == project.id)
        ).all()
        if not hit and decoded["room"]:
            # A pin labelled with the room counts even when the register's
            # location text is looser than the drawing.
            hit = any(decoded["room"] in (m.label or "") for m in markers)
        if not hit:
            continue
        derived = _derive_tracker_fields(project)
        row = {
            "id": project.id,
            "pr_number": project.pr_number,
            "title": project.title,
            "stage": project.stage,
            "pi_name": project.pi_name,
            "planner_bucket": project.planner_bucket,
            "finish": derived.get("finish_date"),
            "status": derived.get("latest_status"),
            "marker_labels": [m.label for m in markers],
        }
        (finished if project.stage in FINISHED_STAGES else active).append(row)

    current_pis = sorted(
        {p["pi_name"] for p in active if p["pi_name"]}
    )
    previous_pis = sorted(
        {p["pi_name"] for p in finished if p["pi_name"]} - set(current_pis)
    )
    # PIs named on pins that no register row carries (a divided area, or a
    # plan annotated ahead of the paperwork).
    pin_pis = {
        m.pi_name
        for m in db.scalars(select(PlanMarker)).all()
        if m.pi_name and _matches(
            {**decoded, "area": decoded["area"], "room": decoded["room"]},
            m.project, m.label or "",
        )
    }
    previous_pis += sorted(pin_pis - set(current_pis) - set(previous_pis))

    return {
        "ok": True,
        "input": location,
        "decoded": decoded,
        "described": reference.describe_location(location),
        "area": scope,
        "current_pis": current_pis,
        "previous_pis": sorted(set(previous_pis)),
        "active_count": len(active),
        "finished_count": len(finished),
        "active_projects": active,
        "finished_projects": finished,
    }
