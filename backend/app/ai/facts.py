"""Live fact pack for the AI assistant.

Why this exists
---------------
Portfolio questions used to be answered from a summary that carried counts
but no dates. Asked "which projects are overdue?" the model could only reply
"the table has no dates", and a crude keyword search (any word longer than
three characters, matched against title/description) happily captured words
like "total" or "project" and returned five unrelated projects instead of
the real totals.

This module reads exactly the same derived Planner fields the construction
dashboard uses and produces two things:

  * render() - a compact, authoritative text block for the model, with the
    numbers spelled out ("QUICK ANSWERS") so a small local model can copy
    them instead of deriving them; and
  * answer() - a deterministic answer for counting/listing questions. No
    model is involved, so those answers cannot drift.

It is read-only and self-contained.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project
from ..services.planner_status import PHASES, phase_for
from ..services.schedule import build_item

#: Longest list printed into the prompt (the rest is summarised as a count).
#: Small local models are slow with long prompts, and the deterministic
#: answers carry the full lists anyway, so the prompt stays deliberately tight.
MAX_ROWS = 12
MAX_WEEK_ROWS = 10
MAX_HOLD_ROWS = 5
MAX_GATE_ROWS = 5

DIVISIONS = list(PHASES)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect(db: Session) -> dict[str, Any]:
    """Read the live database into the fact pack used by the assistant."""
    # Imported lazily: app.api.projects pulls in the whole endpoint layer.
    from ..api.projects import _derive_tracker_fields

    today = date.today()
    rows = list(db.scalars(select(Project)).all())
    derived = {p.id: _derive_tracker_fields(p) for p in rows}

    sync = max(
        (
            info.get("planner_sync_date")
            for info in derived.values()
            if info.get("planner_sync_date")
        ),
        default=None,
    )

    def _removed(info: dict[str, Any]) -> bool:
        """Seen in an older Planner snapshot, absent from the newest one.

        Cancelled / equipment-branch PRs. The dashboard hides them, so the
        assistant's division and stage counts must not include them either -
        otherwise "how many EAR projects?" disagreed with the screen.
        A row that was never tracker-managed has no sync date and is kept.
        """
        date = info.get("planner_sync_date")
        return bool(sync and date and date != sync)

    by_division: Counter[str] = Counter()
    by_stage: Counter[str] = Counter()
    for project in rows:
        info = derived[project.id]
        if _removed(info):
            continue
        by_division[
            phase_for(
                bucket=project.planner_bucket,
                stage=project.stage,
                flags=info.get("flags"),
            )
            or "Unassigned"
        ] += 1
        by_stage[(project.stage or "unknown").upper()] += 1

    # Only the newest Planner import is live (older imports would double
    # count the same project) - the same rule the construction board uses.
    scheduled: list[Any] = []
    unscheduled: list[Project] = []
    assignments: list[dict[str, Any]] = []
    for project in rows:
        info = derived[project.id]
        if sync and info.get("planner_sync_date") != sync:
            continue
        if (info.get("phase") or "") == "Close-up":
            continue
        # Owner data is collected for every live row, scheduled or not: "who is
        # the EAR assigned to?" must not depend on a Planner finish date.
        if info.get("assigned_to") or info.get("execution_lead"):
            assignments.append({
                "pr_number": project.pr_number,
                "title": project.title or "",
                "phase": info.get("phase") or "Unassigned",
                "stage": (project.stage or "").upper(),
                "assigned_to": info.get("assigned_to"),
                "execution_lead": info.get("execution_lead"),
                "requestor": info.get("requestor"),
                "priority": info.get("priority"),
            })
        if not info.get("finish_date"):
            unscheduled.append(project)
            continue
        scheduled.append(build_item(project, info, today=today))

    def by_days_left(items: list[Any]) -> list[Any]:
        return sorted(
            items, key=lambda i: i.days_left if i.days_left is not None else 9999
        )

    overdue = by_days_left([i for i in scheduled if i.window == "overdue"])
    this_week = by_days_left([i for i in scheduled if i.window in ("today", "week")])
    on_hold = by_days_left([i for i in scheduled if "ON HOLD" in i.flags])
    design_gate = by_days_left(
        [
            i
            for i in scheduled
            if "design gate" in i.risks
            or (i.phase == "Design" and i.days_left is not None and i.days_left <= 14)
        ]
    )
    high_risk = by_days_left([i for i in scheduled if i.risk_level == "high"])
    behind = by_days_left([i for i in scheduled if "behind plan" in i.risks])

    def stage_count(*names: str) -> int:
        return sum(by_stage.get(name.upper(), 0) for name in names)

    return {
        "today": today.isoformat(),
        "sync": sync,
        "total": len(rows),
        "by_division": by_division,
        "by_stage": by_stage,
        "scheduled": scheduled,
        "unscheduled": unscheduled,
        "overdue": overdue,
        "this_week": this_week,
        "on_hold": on_hold,
        "design_gate": design_gate,
        "high_risk": high_risk,
        "behind_plan": behind,
        "assignments": assignments,
        "pr_numbers": {p.pr_number.upper() for p in rows if p.pr_number},
        # Division counts (what the dashboards show) vs workflow-stage counts.
        "active_construction": by_division.get("Construction", 0),
        "in_construction_stage": stage_count("CONSTRUCTION"),
        "icr": stage_count("ICR", "ICR_DONE"),
        "punch_list": stage_count("PUNCH_LIST"),
        "ear_stage": stage_count(
            "INTAKE",
            "MOM_SENT",
            "MOM_CONFIRMED",
            "DISPOSITION",
            "EAR_DRAFT",
            "EAR_REVIEW",
            "EAR_APPROVED",
        ),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _row_line(item: Any, *, with_risk: bool = False) -> str:
    parts = [f"  {item.pr_number} — {(item.title or '')[:70]}"]
    parts.append(f"[{item.phase or '?'} | stage {item.current_stage}]")
    if item.days_left is not None:
        if item.days_left < 0:
            parts.append(f"finish {item.finish_date} ({abs(item.days_left)} days late)")
        else:
            parts.append(f"finish {item.finish_date} (in {item.days_left} days)")
    if item.completion_pct is not None:
        parts.append(f"{item.completion_pct}% complete")
    if item.priority:
        parts.append(f"priority {item.priority}")
    if item.required_hours_per_day:
        parts.append(f"needs {item.required_hours_per_day:g} hrs/day")
    if with_risk and item.risks:
        parts.append("risks: " + ", ".join(item.risks))
    if getattr(item, "assigned_to", None):
        parts.append(f"assigned to {item.assigned_to}")
    return " | ".join(parts)


def render(facts: dict[str, Any]) -> str:
    """The authoritative text block handed to the model."""
    lines: list[str] = [
        f"[Live IHP database — authoritative, read {facts['today']}]",
        "",
        "QUICK ANSWERS (exact values - copy them, never recompute):",
        f"- Total projects: {facts['total']}",
        "- By division: "
        + ", ".join(f"{k} {v}" for k, v in facts["by_division"].most_common()),
        f"- Overdue: {len(facts['overdue'])}",
        f"- Due today or this week: {len(facts['this_week'])}",
        f"- On hold: {len(facts['on_hold'])}",
        f"- Construction division (active field work): {facts['active_construction']}",
        f"- In CONSTRUCTION workflow stage: {facts['in_construction_stage']}",
        f"- ICR / approval stage: {facts['icr']}",
        f"- Punch list stage: {facts['punch_list']}",
        f"- EAR-family stages: {facts['ear_stage']}",
        f"- Scheduled rows in the live Planner: {len(facts['scheduled'])}",
        f"- Without a Planner finish date: {len(facts['unscheduled'])}",
        f"- High delay risk: {len(facts['high_risk'])} | behind plan: {len(facts['behind_plan'])}",
        f"- Rows with an owner (Planner 'Assigned to'): {len(facts['assignments'])}",
        f"- Latest Planner sync: {facts['sync'] or 'n/a'}",
        "",
        "Workflow stages (raw counts): "
        + ", ".join(f"{k} {v}" for k, v in facts["by_stage"].most_common()),
    ]

    if facts["overdue"]:
        lines += ["", f"OVERDUE ({len(facts['overdue'])}):"]
        lines += [_row_line(i, with_risk=True) for i in facts["overdue"][:MAX_ROWS]]
    if facts["this_week"]:
        lines += ["", f"DUE TODAY / THIS WEEK ({len(facts['this_week'])}):"]
        lines += [_row_line(i) for i in facts["this_week"][:MAX_WEEK_ROWS]]
    if facts["on_hold"]:
        lines += ["", f"ON HOLD ({len(facts['on_hold'])}):"]
        lines += [_row_line(i) for i in facts["on_hold"][:MAX_HOLD_ROWS]]
    if facts["assignments"]:
        lines += ["", f"ASSIGNMENTS ({len(facts['assignments'])} live rows carry an owner):"]
        for row in facts["assignments"][:MAX_ROWS]:
            owner = row.get("assigned_to") or "n/a"
            lead = row.get("execution_lead") or "n/a"
            lines.append(
                f"  {row['pr_number']} — {row['title'][:60]} | {row['phase']} | "
                f"assigned to {owner} | execution lead {lead}"
            )
    if facts["design_gate"]:
        lines += [
            "",
            f"DESIGN GATE - Design work finishing within 14 days ({len(facts['design_gate'])}):",
        ]
        lines += [_row_line(i) for i in facts["design_gate"][:MAX_GATE_ROWS]]
    return "\n".join(lines)


def sources(facts: dict[str, Any]) -> list[dict[str, str]]:
    """Citations for the live blocks, so the UI can show where data came from."""
    return [
        {
            "filename": "IHP project database",
            "snippet": (
                f"{facts['total']} projects — "
                + ", ".join(f"{k} {v}" for k, v in facts["by_division"].most_common())
            ),
        },
        {
            "filename": "Planner schedule",
            "snippet": (
                f"live sync {facts['sync'] or 'n/a'}: {len(facts['overdue'])} overdue, "
                f"{len(facts['this_week'])} due today/this week, "
                f"{len(facts['on_hold'])} on hold, {len(facts['high_risk'])} high risk"
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Deterministic answers (no model, cannot drift)
# ---------------------------------------------------------------------------

_ASK_COUNT = re.compile(
    r"\b(how many|how much|count|number of|total)\b", re.I
)
_ASK_LIST = re.compile(r"\b(which|what|list|show|name|who|give me|top)\b", re.I)
_OPEN_ENDED = re.compile(
    r"\b(summari[sz]e|summary|draft|write|explain|why|recommend|suggest|advise|plan|"
    r"analyse|analyze|compare|improve|help|email|memo|minutes|report on|prioriti[sz]e)\b",
    re.I,
)
_OVERDUE = re.compile(r"\b(overdue|past due|late|behind schedule)\b", re.I)
_ON_HOLD = re.compile(r"\b(on[ -]?hold|paused|stopped)\b", re.I)
_THIS_WEEK = re.compile(
    r"\b(this week|due today|today|next 7 days|coming week|due soon)\b", re.I
)
#: Tolerant of typos ("asign To") and of the many ways people ask this.
_ASSIGN_ASK = re.compile(
    r"(\bas+ign(?:ed|ee|ment)?\s*(?:to)?\b|\bowner\b|\bowns\b|"
    r"\bresponsible\b|\bin charge\b|\bpoint of contact\b|\bwho is (?:the )?ear\b)",
    re.I,
)


def _people_in(value: str | None) -> list[str]:
    """Split an "Assigned to" cell: MS Project joins resources with commas."""
    if not value:
        return []
    return [p.strip() for p in re.split(r"[,;/]|\band\b", value) if p.strip()]
_UNSCHEDULED = re.compile(
    r"\b(unscheduled|no finish date|without a finish|missing a finish|not scheduled)\b",
    re.I,
)


def _division_of(question: str) -> str | None:
    q = question.lower()
    for division in DIVISIONS:
        if division.lower() in q:
            return division
    if "close up" in q or "closeup" in q or "close-up" in q:
        return "Close-up"
    return None


def _line(item: Any) -> str:
    bits = [f"**{item.pr_number}** - {(item.title or '')[:80]}"]
    meta = [item.phase or "?", (item.current_stage or "").replace("_", " ").title()]
    if item.days_left is not None:
        meta.append(
            f"{abs(item.days_left)} days late ({item.finish_date})"
            if item.days_left < 0
            else f"due {item.finish_date}"
        )
    if item.completion_pct is not None:
        meta.append(f"{item.completion_pct}% complete")
    if item.priority:
        meta.append(f"priority {item.priority}")
    bits.append(" - " + " - ".join(meta))
    return "- " + "".join(bits)


def _list_answer(
    items: list[Any], label: str, division: str | None
) -> str:
    if division:
        items = [i for i in items if (i.phase or "") == division]
    scope = f" in the {division} division" if division else ""
    if not items:
        return f"**None.** No {label} projects{scope} in the live Planner data."
    header = (
        f"**{len(items)}** {label} project{'s' if len(items) != 1 else ''}"
        f"{scope} in the live data:"
    )
    shown = items[:10]
    body = "\n".join(_line(i) for i in shown)
    more = f"\n_+{len(items) - len(shown)} more_" if len(items) > len(shown) else ""
    return f"{header}\n{body}{more}"


def _count_answer(question: str, facts: dict[str, Any]) -> str | None:
    """One or more live metrics for a counting question.

    A compound question ("total projects, ICR and active construction") gets
    every metric it mentions, each on its own line - never a single number
    picked at random.
    """
    q = question.lower()
    division = _division_of(q)
    asked_total = bool(re.search(r"\b(total|all|overall)\b", q)) or (
        "project" in q and division is None
    )

    lines: list[str] = []
    if re.search(r"\bpunch\b", q):
        lines.append(f"- Punch List stage: **{facts['punch_list']}**")
    if re.search(r"\bicr\b|\bapproval\b", q):
        lines.append(f"- ICR / approval stage: **{facts['icr']}**")
    if "active construction" in q or ("construction" in q and "active" in q):
        lines.append(
            f"- Construction division (active field work): **{facts['active_construction']}** "
            f"(in the CONSTRUCTION workflow stage: **{facts['in_construction_stage']}**)"
        )
    elif division:
        lines.append(
            f"- {division} division: **{facts['by_division'].get(division, 0)}**"
        )
    if "division" in q:
        lines.append(
            "- By division: "
            + ", ".join(f"{k} **{v}**" for k, v in facts["by_division"].most_common())
        )
    if "stage" in q:
        lines.append(
            "- Workflow stages: "
            + ", ".join(f"{k} **{v}**" for k, v in facts["by_stage"].most_common())
        )
    if asked_total:
        lines.insert(0, f"- Total projects: **{facts['total']}**")
    if not lines:
        return None
    if len(lines) == 1:
        return lines[0][2:]
    return "Live totals:\n" + "\n".join(lines)


def named_owner(facts: dict[str, Any], question: str) -> str | None:
    """The owner named in the question, if any ("what is X working on?")."""
    ql = question.lower()
    for row in facts.get("assignments") or []:
        for person in _people_in(row.get("assigned_to")) + _people_in(row.get("execution_lead")):
            if len(person) > 3 and person.lower() in ql:
                return person
    return None


def _assignment_answer(
    facts: dict[str, Any], division: str | None, question: str = ""
) -> str | None:
    """Who holds the work: grouped by person, or one person's projects."""
    rows = facts.get("assignments") or []
    if division:
        rows = [row for row in rows if row["phase"] == division]
    if not rows:
        others = facts.get("assignments") or []
        if division and others:
            # Do not dead-end: say where owner data does exist.
            from collections import Counter as _Counter

            by_division = _Counter(row["phase"] for row in others)
            return (
                f"**None** of the {division}-division rows carry an owner in the "
                'Planner "Assigned to" column. Owners exist for: '
                + ", ".join(f"{k} {v}" for k, v in by_division.most_common())
                + "."
            )
        if division:
            return (
                f"**None.** No live {division}-division project carries an owner in "
                'the Planner "Assigned to" column.'
            )
        return None

    # "what is Assam Hmshw working on?" -> that person's projects.
    ql = question.lower()
    asked: str | None = None
    for row in rows:
        for person in _people_in(row.get("assigned_to")) + _people_in(row.get("execution_lead")):
            if len(person) > 3 and person.lower() in ql:
                asked = person
                break
        if asked:
            break
    if asked:
        mine = [
            row for row in rows
            if asked.lower() in (row.get("assigned_to") or "").lower()
            or asked.lower() in (row.get("execution_lead") or "").lower()
        ]
        lines = [
            f"- **{row['pr_number']}** — {row['title'][:70]} | {row['phase']} | "
            f"{(row.get('stage') or '').replace('_', ' ').title()}"
            for row in mine[:12]
        ]
        extra = f"\n_+{len(mine) - 12} more_" if len(mine) > 12 else ""
        return f"**{asked}** holds **{len(mine)}** live project(s):\n" + "\n".join(lines) + extra

    by_person: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for person in _people_in(row.get("assigned_to")) or [
            row.get("execution_lead") or "unassigned"
        ]:
            by_person.setdefault(str(person), []).append(row)
    lines = []
    for person, items in sorted(by_person.items(), key=lambda kv: -len(kv[1]))[:12]:
        sample = ", ".join(i["pr_number"] for i in items[:4])
        more = f" +{len(items) - 4} more" if len(items) > 4 else ""
        lines.append(f"- **{person}** ({len(items)}): {sample}{more}")
    scope = f" in the {division} division" if division else ""
    return (
        f"**{len(rows)}** live projects{scope} carry an owner in the Planner "
        '(column "Assigned to"):' + "\n" + "\n".join(lines)
    )


def answer(question: str, facts: dict[str, Any]) -> str | None:
    """A deterministic answer for counting/listing questions, else None.

    Only fires on short, closed questions ("which projects are overdue?",
    "how many construction projects are there?"). Open-ended requests
    ("summarise the overdue work") stay with the language model.
    """
    q = question.strip()
    if not q or len(q) > 140 or _OPEN_ENDED.search(q):
        return None

    division = _division_of(q)
    wants_count = bool(_ASK_COUNT.search(q))

    # "Who is the EAR assigned to?" - the Planner's "Assigned to" column.
    # Also fires when the question names a person who owns work, so
    # "what is Assam Hmshw working on?" works without a keyword.
    if _ASSIGN_ASK.search(q) or named_owner(facts, q):
        assigned = _assignment_answer(facts, division, q)
        if assigned:
            return assigned

    if _OVERDUE.search(q):
        return _list_answer(facts["overdue"], "overdue", division)
    if _ON_HOLD.search(q):
        return _list_answer(facts["on_hold"], "on hold", division)
    if _UNSCHEDULED.search(q):
        return f"**{len(facts['unscheduled'])}** project(s) have no Planner finish date."
    if _THIS_WEEK.search(q):
        return _list_answer(facts["this_week"], "due today or this week", division)
    if wants_count:
        counted = _count_answer(q, facts)
        if counted:
            return counted
    if _ASK_LIST.search(q) and division:
        items = [i for i in facts["scheduled"] if (i.phase or "") == division]
        items.sort(key=lambda i: i.days_left if i.days_left is not None else 9999)
        return _list_answer(items, f"{division}-division scheduled", None)
    return None


_PR_PATTERN = re.compile(r"\bPR[-\s]?(\d{3,6})\b", re.I)


def unknown_pr_numbers(text: str, known: set[str]) -> list[str]:
    """PR numbers the model quoted that do not exist in the live database."""
    found = {f"PR-{m.group(1)}" for m in _PR_PATTERN.finditer(text)}
    return sorted(n for n in found if n.upper() not in known)


# ---------------------------------------------------------------------------
# One project (deterministic: "when is this due?", "what is its status?")
# ---------------------------------------------------------------------------

_DATE_ASK = re.compile(
    r"\b(due|finish|finished|deadline|when|end date|closing)\b", re.I
)
_STATUS_ASK = re.compile(
    r"\b(status|stage|where|progress|complete|completion|percent|update|state)\b", re.I
)
_RISK_ASK = re.compile(
    r"\b(overdue|late|risk|risky|behind|on hold|blocked|problem|issue|delayed)\b", re.I
)
_SCHED_ASK = re.compile(
    r"\b(start|schedule|timeline|duration|effort|hours|man.?hours|pace|plan)\b", re.I
)
_PEOPLE_ASK = re.compile(
    r"\b(pi|owner|who|contact|location|where is|trades?|assigned|assignee|"
    r"execution lead|responsible)\b",
    re.I,
)


def project_answer(question: str, project: Any, derived: dict[str, Any]) -> str | None:
    """Deterministic answer to a short factual question about one project.

    A small local model reads a project block badly (the 1B model confused
    "Created" with the Planner finish date), so dates, progress, gates and
    status are answered from the record itself. Open-ended requests still go
    to the model.
    """
    q = question.strip()
    if not q or len(q) > 120 or _OPEN_ENDED.search(q):
        return None
    if not (
        _DATE_ASK.search(q)
        or _STATUS_ASK.search(q)
        or _RISK_ASK.search(q)
        or _SCHED_ASK.search(q)
        or _PEOPLE_ASK.search(q)
    ):
        return None

    item = build_item(project, derived) if derived.get("finish_date") else None
    lines = [f"**{project.pr_number}** - {project.title}"]

    stage = (derived.get("stage") or getattr(project, "stage", "") or "").replace("_", " ")
    if stage:
        lines.append(f"- Stage: {stage} ({derived.get('phase') or 'Unassigned'} division)")
    if derived.get("priority"):
        lines.append(f"- Priority: {derived['priority']}")

    if item is not None:
        if item.finish_date:
            if item.days_left is not None and item.days_left < 0:
                lines.append(
                    f"- Planner finish: {item.finish_date} - **{abs(item.days_left)} days late** "
                    f"(as of {date.today().isoformat()})"
                )
            elif item.days_left == 0:
                lines.append(f"- Planner finish: {item.finish_date} - **due today**")
            else:
                lines.append(f"- Planner finish: {item.finish_date} ({item.days_left} days left)")
        if item.start_date:
            lines.append(f"- Planner start: {item.start_date}")
        if item.completion_pct is not None:
            lines.append(f"- Completion: {item.completion_pct}%")
        if item.effort_hours is not None:
            detail = f"- Effort: {item.effort_hours:g} hours"
            if item.remaining_hours is not None:
                detail += f", {item.remaining_hours:g} hours remaining"
            if item.required_hours_per_day:
                if item.days_left is not None and item.days_left < 0:
                    detail += (
                        f"; the Planner finish date has passed, so "
                        f"{item.required_hours_per_day:g} hrs/day is the recovery pace"
                    )
                else:
                    detail += (
                        f", needs {item.required_hours_per_day:g} hrs/day to finish on time"
                    )
            lines.append(detail)
        if item.next_gate:
            lines.append(f"- Next gate: {item.next_gate}")
        if item.risks:
            lines.append("- Risks: " + ", ".join(item.risks))
        elif item.days_left is not None and item.days_left >= 0:
            lines.append("- Risks: none flagged (on or ahead of the Planner date)")

    if derived.get("latest_status"):
        status = f"- Tracker status: {derived['latest_status']}"
        if derived.get("latest_status_date"):
            status += f" (as of {derived['latest_status_date']})"
        lines.append(status)
    if derived.get("checklist"):
        lines.append(f"- Checklist: {derived['checklist']}")
    if derived.get("flags"):
        lines.append("- Flags: " + ", ".join(derived["flags"]))
    if derived.get("ear_substatus"):
        lines.append(f"- EAR status: {derived['ear_substatus']}")

    if _PEOPLE_ASK.search(q):
        # Planner ownership columns: "Assigned to" is the IHP engineer the task
        # belongs to, "Execution Lead" the delivery lead, "Requestor/PI" the
        # requester (an IHP team member, not the Principal Investigator).
        if derived.get("assigned_to"):
            lines.append(f"- Assigned to (Planner): {derived['assigned_to']}")
        if derived.get("execution_lead"):
            lines.append(f"- Execution lead: {derived['execution_lead']}")
        if derived.get("requestor"):
            lines.append(f"- Requestor/PI column: {derived['requestor']}")
        if getattr(project, "pi_name", None):
            lines.append(f"- PI: {project.pi_name} ({project.pi_email or 'no email on file'})")
        if getattr(project, "location", None):
            lines.append(f"- Location: {project.location}")
        if derived.get("trades"):
            lines.append("- Trades: " + ", ".join(derived["trades"]))

    return "\n".join(lines)


def project_source(project: Any, derived: dict[str, Any]) -> dict[str, str]:
    """Citation for a single-project answer."""
    return {
        "filename": f"Project {project.pr_number}",
        "snippet": (
            f"{project.title} - "
            f"{derived.get('phase') or 'unassigned'} / {derived.get('stage') or project.stage}"
        ),
    }
