"""Construction crew, work-load and notification endpoints.

The construction day is two 4-hour shifts:

    AM   07:00 - 11:00   (4 h)
    PM   12:00 - 16:00   (4 h)
    FULL both            (8 h)

Admins (``construction.manage``) assign a person to a project for a day
and shift; the board then shows each person's live load against the 8-hour
day, the per-project totals, and warns when somebody is over-allocated.
Assignments can be pushed to the person by email, WhatsApp or SMS when a
provider is configured - otherwise the exact message is returned so it can
be copied and sent manually.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import CAP_CONSTRUCTION_MANAGE, get_current_user, require_capability
from ..db import get_db
from ..models import CrewAssignment, Project, User
from ..services import schedule as sched

router = APIRouter(prefix="/construction", tags=["construction_crew"])

#: The two construction shifts, in hours.
SHIFT_HOURS: dict[str, tuple[str, float]] = {
    "AM": ("07:00-11:00", 4.0),
    "PM": ("12:00-16:00", 4.0),
    "FULL": ("07:00-16:00 (with lunch 11-12)", 8.0),
}
DAY_CAPACITY_HOURS = 8.0

#: Buckets that make up the CONSTRUCTION division (the dashboard scope).
CONSTRUCTION_BUCKETS = {
    "CONSTRUCTION", "PTW/WICF", "PTW", "WICF", "SHUTDOWN", "QUALITY INSPECTION",
}


class AssignmentIn(BaseModel):
    project_id: int
    person_name: str
    person_email: str | None = None
    person_phone: str | None = None
    work_date: str                      # YYYY-MM-DD
    shift: str = "FULL"
    hours: float | None = None
    task: str | None = None
    notes: str | None = None


class AssignmentPatch(BaseModel):
    person_name: str | None = None
    person_email: str | None = None
    person_phone: str | None = None
    work_date: str | None = None
    shift: str | None = None
    hours: float | None = None
    task: str | None = None
    notes: str | None = None


def _parse_day(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value[:10])
    except ValueError as exc:
        raise HTTPException(400, f"Invalid date {value!r}; use YYYY-MM-DD") from exc


def _assignment_out(a: CrewAssignment, project: Project | None = None) -> dict:
    shift_label, shift_hours = SHIFT_HOURS.get(a.shift, ("-", a.hours))
    return {
        "id": a.id,
        "project_id": a.project_id,
        "pr_number": project.pr_number if project else None,
        "project_title": project.title if project else None,
        "project_location": project.location if project else None,
        "person_name": a.person_name,
        "person_email": a.person_email,
        "person_phone": a.person_phone,
        "work_date": a.work_date.strftime("%Y-%m-%d") if a.work_date else None,
        "shift": a.shift,
        "shift_label": shift_label,
        "shift_hours": shift_hours,
        "hours": a.hours,
        "task": a.task,
        "notes": a.notes,
        "notified_at": a.notified_at.isoformat() if a.notified_at else None,
        "notify_channel": a.notify_channel,
        "notify_error": a.notify_error,
    }


def notify_channels() -> dict[str, bool]:
    """Which delivery channels are configured right now."""
    from ..core.config import get_settings

    s = get_settings()
    return {
        "email": bool(s.SMTP_HOST),
        "whatsapp": bool(os.getenv("WHATSAPP_API_URL") and os.getenv("WHATSAPP_TOKEN")),
        "sms": bool(os.getenv("SMS_API_URL") and os.getenv("SMS_TOKEN")),
    }


def build_message(a: CrewAssignment, project: Project | None) -> str:
    shift_label, _ = SHIFT_HOURS.get(a.shift, ("-", a.hours))
    lines = [
        f"Work assignment - {a.work_date.strftime('%a %d %b %Y') if a.work_date else ''}",
        f"Project: {project.pr_number if project else a.project_id} "
        f"{(project.title if project else '') or ''}",
        f"Shift: {a.shift} ({shift_label})  Hours: {a.hours:g}",
    ]
    if project and project.location:
        lines.append(f"Location: {project.location}")
    if a.task:
        lines.append(f"Task: {a.task}")
    if a.notes:
        lines.append(f"Notes: {a.notes}")
    lines.append("— IHP Project Delivery")
    return "\n".join(lines)


def _post_json(url: str, payload: dict, token: str) -> tuple[bool, str | None]:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        return True, None
    except Exception as exc:  # noqa: BLE001 - report the provider error to the admin
        return False, str(exc)[:300]


@router.get("/overview")
def construction_overview(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Construction-division progress: started / finished / pending and time."""
    rows = db.scalars(select(Project)).all()
    from ..api.projects import _derive_tracker_fields

    today = date.today()
    started = finished = pending = 0
    planned_hours = remaining_hours = 0.0
    slack_days: list[int] = []
    projects = []
    for p in rows:
        d = _derive_tracker_fields(p)
        if (p.planner_bucket or "").upper() not in CONSTRUCTION_BUCKETS:
            continue
        item = sched.build_item(p, d, today=today)
        pct = item.completion_pct or 0
        if pct >= 100:
            finished += 1
        elif pct > 0 or item.current_stage in (
            "CONSTRUCTION", "WORK_PERMIT", "PROCUREMENT",
        ):
            started += 1
        else:
            pending += 1
        if item.effort_hours:
            planned_hours += item.effort_hours
        if item.remaining_hours:
            remaining_hours += item.remaining_hours
        if item.days_left is not None and item.required_hours_per_day:
            # Flexibility: days available beyond what the remaining work needs
            # at a 8 h/day single crew rate.
            needed = item.remaining_hours / DAY_CAPACITY_HOURS if item.remaining_hours else 0
            slack_days.append(int(item.days_left - needed))
        projects.append(item.to_dict())

    projects.sort(key=lambda x: x.get("days_left") if x.get("days_left") is not None else 9999)
    return {
        "today": today.isoformat(),
        "started": started,
        "finished": finished,
        "pending": pending,
        "total": len(projects),
        "planned_hours": round(planned_hours, 1),
        "remaining_hours": round(remaining_hours, 1),
        "flexibility": {
            "min_slack_days": min(slack_days) if slack_days else None,
            "max_slack_days": max(slack_days) if slack_days else None,
            "negative_slack": sum(1 for s in slack_days if s < 0),
        },
        "projects": projects,
    }


@router.get("/crew")
def list_crew(
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(CrewAssignment)
    if date_from:
        stmt = stmt.where(CrewAssignment.work_date >= _parse_day(date_from))
    if date_to:
        stmt = stmt.where(CrewAssignment.work_date < _parse_day(date_to) + timedelta(days=1))
    if project_id:
        stmt = stmt.where(CrewAssignment.project_id == project_id)
    stmt = stmt.order_by(CrewAssignment.work_date.desc(), CrewAssignment.person_name)
    rows = db.scalars(stmt).all()
    projects = {
        p.id: p for p in db.scalars(
            select(Project).where(Project.id.in_({r.project_id for r in rows} or {0}))
        ).all()
    }
    return [_assignment_out(a, projects.get(a.project_id)) for a in rows]


@router.post("/crew", status_code=status.HTTP_201_CREATED)
def create_crew(
    body: AssignmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_CONSTRUCTION_MANAGE)),
):
    if body.shift.upper() not in SHIFT_HOURS:
        raise HTTPException(400, "shift must be AM, PM or FULL")
    project = db.get(Project, body.project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    _, default_hours = SHIFT_HOURS[body.shift.upper()]
    rec = CrewAssignment(
        project_id=body.project_id,
        person_name=body.person_name.strip(),
        person_email=(body.person_email or "").strip() or None,
        person_phone=(body.person_phone or "").strip() or None,
        work_date=_parse_day(body.work_date),
        shift=body.shift.upper(),
        hours=body.hours if body.hours is not None else default_hours,
        task=(body.task or "").strip() or None,
        notes=(body.notes or "").strip() or None,
        created_by_id=user.id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _assignment_out(rec, project)


@router.patch("/crew/{assignment_id}")
def update_crew(
    assignment_id: int,
    body: AssignmentPatch,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_CONSTRUCTION_MANAGE)),
):
    rec = db.get(CrewAssignment, assignment_id)
    if rec is None:
        raise HTTPException(404, "Assignment not found")
    data = body.model_dump(exclude_unset=True)
    if "work_date" in data and data["work_date"]:
        rec.work_date = _parse_day(data.pop("work_date"))
    if "shift" in data and data["shift"]:
        shift = data.pop("shift").upper()
        if shift not in SHIFT_HOURS:
            raise HTTPException(400, "shift must be AM, PM or FULL")
        rec.shift = shift
    for field, value in data.items():
        setattr(rec, field, value)
    rec.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rec)
    return _assignment_out(rec, db.get(Project, rec.project_id))


@router.delete("/crew/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_crew(
    assignment_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_CONSTRUCTION_MANAGE)),
):
    rec = db.get(CrewAssignment, assignment_id)
    if rec is None:
        raise HTTPException(404, "Assignment not found")
    db.delete(rec)
    db.commit()


@router.get("/load")
def daily_load(
    day: str | None = Query(default=None, description="YYYY-MM-DD, defaults to today"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """One day's work load per person, split into the AM and PM lanes."""
    start = _parse_day(day or date.today().isoformat())
    end = start + timedelta(days=1)
    rows = db.scalars(
        select(CrewAssignment)
        .where(CrewAssignment.work_date >= start)
        .where(CrewAssignment.work_date < end)
        .order_by(CrewAssignment.person_name)
    ).all()
    projects = {
        p.id: p for p in db.scalars(
            select(Project).where(Project.id.in_({r.project_id for r in rows} or {0}))
        ).all()
    }

    people: dict[str, dict] = {}
    project_totals: dict[int, float] = {}
    for a in rows:
        person = people.setdefault(a.person_name, {
            "person_name": a.person_name,
            "person_email": a.person_email,
            "person_phone": a.person_phone,
            "am_hours": 0.0,
            "pm_hours": 0.0,
            "total_hours": 0.0,
            "assignments": [],
        })
        if a.shift == "AM":
            person["am_hours"] += a.hours
        elif a.shift == "PM":
            person["pm_hours"] += a.hours
        else:
            person["am_hours"] += a.hours / 2
            person["pm_hours"] += a.hours / 2
        person["total_hours"] += a.hours
        person["assignments"].append(_assignment_out(a, projects.get(a.project_id)))
        project_totals[a.project_id] = project_totals.get(a.project_id, 0.0) + a.hours

    for person in people.values():
        person["am_hours"] = round(person["am_hours"], 1)
        person["pm_hours"] = round(person["pm_hours"], 1)
        person["total_hours"] = round(person["total_hours"], 1)
        person["idle_hours"] = round(max(DAY_CAPACITY_HOURS - person["total_hours"], 0), 1)
        person["over_hours"] = round(max(person["total_hours"] - DAY_CAPACITY_HOURS, 0), 1)
        person["status"] = (
            "over" if person["over_hours"] > 0
            else "full" if person["total_hours"] >= DAY_CAPACITY_HOURS
            else "partial" if person["total_hours"] > 0
            else "idle"
        )

    return {
        "day": start.strftime("%Y-%m-%d"),
        "shifts": {k: {"label": v[0], "hours": v[1]} for k, v in SHIFT_HOURS.items()},
        "capacity_hours": DAY_CAPACITY_HOURS,
        "people": sorted(people.values(), key=lambda p: p["person_name"]),
        "project_hours": [
            {
                "project_id": pid,
                "pr_number": projects[pid].pr_number if pid in projects else None,
                "title": projects[pid].title if pid in projects else None,
                "hours": round(hours, 1),
            }
            for pid, hours in sorted(project_totals.items(), key=lambda kv: -kv[1])
        ],
        "totals": {
            "people": len(people),
            "hours": round(sum(p["total_hours"] for p in people.values()), 1),
            "over_allocated": sum(1 for p in people.values() if p["status"] == "over"),
            "idle_people": sum(1 for p in people.values() if p["status"] == "idle"),
        },
    }


@router.post("/crew/{assignment_id}/notify")
def notify_assignee(
    assignment_id: int,
    channel: str = Query("auto", description="auto | email | whatsapp | sms | copy"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_CONSTRUCTION_MANAGE)),
):
    """Send the assignment to the person by email / WhatsApp / SMS.

    When a channel is not configured the exact message text is returned so
    the admin can copy and send it manually - nothing is silently dropped.
    """
    from ..services import emailer

    rec = db.get(CrewAssignment, assignment_id)
    if rec is None:
        raise HTTPException(404, "Assignment not found")
    project = db.get(Project, rec.project_id)
    message = build_message(rec, project)
    configured = notify_channels()

    subject = f"Work assignment {rec.work_date.strftime('%d %b') if rec.work_date else ''} - "
    subject += project.pr_number if project else ""

    results: dict[str, object] = {}
    sent_channel: str | None = None
    error: str | None = None

    want = channel.lower()
    try_email = want in ("auto", "email") and rec.person_email and configured["email"]
    try_whatsapp = want in ("auto", "whatsapp") and configured["whatsapp"] and rec.person_phone
    try_sms = want in ("auto", "sms") and configured["sms"] and rec.person_phone

    if try_email:
        ok = emailer.send_email(rec.person_email, subject, message)
        results["email"] = ok
        if ok:
            sent_channel = "email"
        else:
            error = "SMTP send failed"
    elif want in ("auto", "email"):
        results["email"] = "not configured"

    if sent_channel is None and try_whatsapp:
        ok, err = _post_json(
            os.environ["WHATSAPP_API_URL"],
            {"to": rec.person_phone, "message": message},
            os.environ["WHATSAPP_TOKEN"],
        )
        results["whatsapp"] = ok
        if ok:
            sent_channel = "whatsapp"
        else:
            error = err
    elif want in ("auto", "whatsapp"):
        results["whatsapp"] = "not configured"

    if sent_channel is None and try_sms:
        ok, err = _post_json(
            os.environ["SMS_API_URL"],
            {"to": rec.person_phone, "message": message},
            os.environ["SMS_TOKEN"],
        )
        results["sms"] = ok
        if ok:
            sent_channel = "sms"
        else:
            error = err
    elif want in ("auto", "sms"):
        results["sms"] = "not configured"

    rec.notify_channel = sent_channel or want
    rec.notify_error = error
    rec.notified_at = datetime.now(timezone.utc) if sent_channel else rec.notified_at
    db.commit()

    wa_link = None
    if rec.person_phone:
        digits = "".join(ch for ch in rec.person_phone if ch.isdigit())
        if digits:
            wa_link = f"https://wa.me/{digits}?text={urllib.parse.quote(message)}"

    return {
        "sent": sent_channel is not None,
        "channel": sent_channel,
        "configured": configured,
        "results": results,
        "error": error,
        "message": message,
        "whatsapp_link": wa_link,
        "mailto_link": (
            f"mailto:{rec.person_email}?subject={urllib.parse.quote(subject)}"
            f"&body={urllib.parse.quote(message)}"
        ) if rec.person_email else None,
    }
