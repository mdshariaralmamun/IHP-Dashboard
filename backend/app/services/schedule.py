"""Construction schedule analysis (Planner-driven).

Turns the Planner schedule fields into the live construction view:

  * finish-date windows    - overdue / today / this week / 2 weeks / 3 weeks /
                             this month / later
  * urgency                - the Planner priority
  * stage gate             - the workflow stage that must still complete
  * prorated pace          - remaining effort spread over the days left, i.e.
                             how many man-hours per day the project needs now
  * delay risk             - overdue, on hold, behind plan, or blocked by an
                             upstream Design / MTO / Procore gate

Why the gate matters: design work (SOW/BOQ/MTO, Procore approval) is the
predecessor of construction. If a Design-division project is late, the
construction it feeds is late too - so those are reported as blockers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

#: Workflow stage -> the stage that comes next (the "gate" to be finished).
NEXT_STAGE: dict[str, str] = {
    "INTAKE": "MOM",
    "MOM_SENT": "MOM confirmation",
    "MOM_CONFIRMED": "Disposition",
    "DISPOSITION": "EAR",
    "EAR_DRAFT": "EAR review",
    "EAR_REVIEW": "EAR approval",
    "EAR_APPROVED": "ASEPC / SOW",
    "SOW_DRAFT": "SOW review",
    "SOW_REVIEW": "SOW approval",
    "SOW_APPROVED": "MTO",
    "MTO_DRAFT": "MTO review",
    "MTO_APPROVED": "Procurement",
    "PROCUREMENT": "Work permit",
    "WORK_PERMIT": "Construction",
    "CONSTRUCTION": "Quality inspection / WCC",
    "CLOSEOUT": "WCH / handover",
    "PUNCH_LIST": "Punch list clearance",
    "ICR_DONE": "Equipment installation (ICR)",
}

#: Window keys in display order.
WINDOWS: tuple[str, ...] = (
    "overdue", "today", "week", "two_weeks", "three_weeks", "month", "later",
)

WINDOW_LABELS: dict[str, str] = {
    "overdue": "Overdue",
    "today": "Due today",
    "week": "Due this week",
    "two_weeks": "Next 2 weeks",
    "three_weeks": "Next 3 weeks",
    "month": "Within the month",
    "later": "Later",
}

_HOURS = re.compile(r"([\d,.]+)\s*(?:hours|hrs|h)\b", re.I)


def parse_hours(value: str | None) -> float | None:
    """Parse an effort cell such as "472 hours" into a number."""
    if not value:
        return None
    m = _HOURS.search(str(value))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    """Parse the ISO dates stored in the project description."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


@dataclass
class ScheduleItem:
    """One project as seen by the construction dashboard."""

    id: int
    pr_number: str
    title: str
    pi_name: str | None = None
    location: str | None = None
    phase: str | None = None
    bucket: str | None = None
    #: Planner "Assigned to" column - the IHP person who owns the task.
    assigned_to: str | None = None
    execution_lead: str | None = None
    stage: str = "INTAKE"
    current_stage: str = "INTAKE"
    next_gate: str | None = None
    priority: str | None = None
    trades: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    start_date: str | None = None
    finish_date: str | None = None
    days_left: int | None = None
    completion_pct: int | None = None
    effort_hours: float | None = None
    remaining_hours: float | None = None
    required_hours_per_day: float | None = None
    window: str | None = None
    risks: list[str] = field(default_factory=list)
    risk_level: str = "low"

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        return d


def _window_for(days_left: int) -> str:
    if days_left < 0:
        return "overdue"
    if days_left == 0:
        return "today"
    if days_left <= 7:
        return "week"
    if days_left <= 14:
        return "two_weeks"
    if days_left <= 21:
        return "three_weeks"
    if days_left <= 31:
        return "month"
    return "later"


def build_item(p: object, derived: dict, today: date | None = None) -> ScheduleItem:
    """Build one schedule row from a Project ORM object + its derived fields."""
    today = today or date.today()
    finish = parse_date(derived.get("finish_date"))
    start = parse_date(derived.get("start_date"))
    pct = derived.get("completion_pct")
    effort = parse_hours(derived.get("effort"))
    flags = [str(f).upper() for f in (derived.get("flags") or [])]

    item = ScheduleItem(
        id=getattr(p, "id"),
        pr_number=getattr(p, "pr_number"),
        title=getattr(p, "title"),
        pi_name=getattr(p, "pi_name"),
        location=getattr(p, "location"),
        phase=derived.get("phase"),
        assigned_to=derived.get("assigned_to"),
        execution_lead=derived.get("execution_lead"),
        bucket=getattr(p, "planner_bucket", None),
        stage=getattr(p, "stage") or "INTAKE",
        current_stage=getattr(p, "stage") or "INTAKE",
        priority=derived.get("priority"),
        trades=derived.get("trades") or [],
        flags=flags,
        start_date=derived.get("start_date"),
        finish_date=derived.get("finish_date"),
        completion_pct=pct,
        effort_hours=effort,
    )
    item.next_gate = NEXT_STAGE.get(item.current_stage, "Completion")

    if finish:
        item.days_left = (finish - today).days
        item.window = _window_for(item.days_left)

    # Prorated pace: the man-hours per day needed to still hit the finish date.
    if effort is not None and pct is not None:
        remaining = max(effort * (1 - pct / 100.0), 0.0)
        item.remaining_hours = round(remaining, 1)
        if item.days_left is not None:
            span = max(item.days_left, 1)
            item.required_hours_per_day = round(remaining / span, 1)

    # ---- delay risk -----------------------------------------------------
    risks: list[str] = []
    if item.days_left is not None and item.days_left < 0:
        risks.append("overdue")
    if "ON HOLD" in flags:
        risks.append("on hold")
    if item.days_left is not None and 0 <= item.days_left <= 7 and (pct or 0) < 80:
        risks.append("tight finish")
    # Behind plan: how much of the timeline has elapsed vs work completed.
    if start and finish and pct is not None:
        total = (finish - start).days
        elapsed = (today - start).days
        if total > 0 and 0 <= elapsed <= total:
            expected = elapsed / total * 100
            if expected - pct > 25:
                risks.append("behind plan")
    # Upstream gate: a Design-division project that must finish first.
    if item.phase == "Design" and item.days_left is not None and item.days_left <= 14:
        risks.append("design gate")
    item.risks = risks
    # HIGH is reserved for work that is already late or stopped, so the alert
    # stays meaningful. Schedule slippage and upstream gates are MEDIUM.
    item.risk_level = (
        "high" if any(r in ("overdue", "on hold") for r in risks)
        else "medium" if risks
        else "low"
    )
    return item
