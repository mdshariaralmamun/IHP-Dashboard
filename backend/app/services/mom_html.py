"""HTML renderer for the Minutes of Meeting (web view + HTML email body).

The Word document stays the archival format; this module produces the same
minute as a single self-contained HTML document so it can be:

  * previewed/embedded in the app (GET /api/projects/{id}/mom/view), and
  * used as the HTML body of the MOM email, which is what makes the message
    read like a web page inside Outlook instead of a plain-text dump.

The template lives in templates/mom_template.html and is data-driven: swapping
the context renders any project.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..core.config import get_settings

_TEMPLATE_NAME = "mom_template.html"

#: Values that mean "still waiting" / "done" / "attention" - used to colour the
#: status badges in the document.
_BADGE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("approved", "accepted", "complete", "completed", "closed", "done", "wcc", "wch", "handover"), "badge-green"),
    (("overdue", "late", "rejected", "disputed", "cancelled", "on hold", "blocked"), "badge-red"),
    (("pending", "awaiting", "waiting", "in review", "review", "submitted", "draft"), "badge-amber"),
    (("in progress", "ongoing", "active", "construction", "execution"), "badge-blue"),
)


def badge_class(value: str | None) -> str:
    """Colour for a status word ("TBD", "Pending", "Awaiting Summary", ...)."""
    text = (value or "").strip().lower()
    if not text:
        return "badge-gray"
    for needles, css in _BADGE_RULES:
        if any(needle in text for needle in needles):
            return css
    return "badge-gray"


def _environment() -> Environment:
    templates = Path(get_settings().TEMPLATES_DIR)
    env = Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


def _value(value: Any) -> str:
    """Render a value, showing N/A for anything empty."""
    if value is None:
        return "N/A"
    text = str(value).strip()
    return text if text else "N/A"


def _brief(value: Any, limit: int = 160) -> str:
    text = _value(value)
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def build_html_context(
    *,
    project: Any,
    details: dict[str, Any],
    derived: dict[str, Any],
    version: int,
    context: dict[str, Any] | None = None,
    base_url: str | None = None,
    for_email: bool = False,
) -> dict[str, Any]:
    """Everything the template needs, from one project and its MOM details."""
    context = context or {}
    version_label = f"{version - 1:02d}"

    # Logos: absolute URL for email, the app's own asset in the browser.
    kaust_logo = ""
    if base_url:
        kaust_logo = base_url.rstrip("/") + "/kaust_logo.png"

    meeting_when = " ".join(
        part for part in (details.get("meeting_date"), details.get("meeting_time")) if part
    )
    organizer = next(
        (
            person.get("name")
            for person in (details.get("attendees") or [])
            if isinstance(person, dict) and "organi" in str(person.get("title", "")).lower()
        ),
        None,
    )

    attendees = []
    for person in details.get("attendees") or []:
        if not isinstance(person, dict):
            continue
        attendees.append(
            {
                "name": person.get("name") or "",
                "title": person.get("title") or "",
                "email": person.get("email") or "",
                "organizer": "organi" in str(person.get("title", "")).lower(),
            }
        )

    meeting_rows = [
        ("Meeting Number", _value(details.get("meeting_number"))),
        ("Date & Time", _value(meeting_when)),
        ("Venue", _value(details.get("meeting_location") or project.location)),
        ("Organizer", _value(organizer)),
        ("Invitation Subject", _value(details.get("meeting_title") or project.title)),
    ]

    project_rows = [
        ("PR Number", _value(project.pr_number)),
        ("Title", _value(project.title)),
        ("Location", _value(project.location)),
        ("PI Name", _value(project.pi_name)),
        ("Division", _value(derived.get("phase") or derived.get("division"))),
        (
            "Type / Trades",
            _value(
                " / ".join(
                    part
                    for part in (
                        derived.get("project_type"),
                        ", ".join(derived.get("trades") or []) or None,
                    )
                    if part
                )
            ),
        ),
        ("Priority", _value(derived.get("priority"))),
        ("Sprint", _value(derived.get("sprint"))),
        ("Completion", f"{derived['completion_pct']}%" if derived.get("completion_pct") is not None else "N/A"),
        (
            "Effort / Duration",
            _value(
                " / ".join(
                    part
                    for part in (derived.get("effort"), derived.get("duration"))
                    if part
                )
            ),
        ),
        ("Assigned To", _value(derived.get("assigned_to"))),
        ("Execution Lead", _value(derived.get("execution_lead"))),
        (
            "Start / Finish",
            _value(
                " / ".join(
                    part
                    for part in (derived.get("start_date"), derived.get("finish_date"))
                    if part
                )
            ),
        ),
        ("Planner Sync", _value(derived.get("planner_sync_date"))),
        ("Document Code", _value(context.get("document_code"))),
    ]

    latest_status = derived.get("latest_status")
    ear_status = derived.get("ear_substatus")
    status_rows = [
        ("Latest Status", _value(latest_status), badge_class(latest_status)),
        ("Status Date", _value(derived.get("latest_status_date")), None),
        ("Phase", _value(derived.get("phase")), badge_class(derived.get("phase"))),
        ("EAR Status", _value(ear_status), badge_class(ear_status)),
        (
            "Tracker Flags",
            _value(", ".join(derived.get("flags") or [])),
            "badge-red" if "ON HOLD" in [str(f).upper() for f in (derived.get("flags") or [])] else None,
        ),
        ("Revision", f"v{version} (R{version_label})", None),
    ]

    # Agenda: an item is a trade heading plus its work lines (the same shape the
    # Word document prints).
    agenda = []
    for item in context.get("agenda") or details.get("agenda") or []:
        if not isinstance(item, dict):
            continue
        trade = (item.get("trade") or "").strip()
        raw = (item.get("scope") or item.get("description") or "").strip()
        lines: list[str] = []
        for raw_line in raw.splitlines():
            line = raw_line.strip().lstrip("\u00d8\u2022-* ").strip()
            if line:
                lines.append(line)
        if not lines and trade:
            lines = [trade]
            trade = ""
        agenda.append(
            {
                "trade": trade.rstrip(":") if trade else "",
                "lines": lines,
                "action": (item.get("action") or "").strip(),
                "etc": (item.get("etc") or "").strip(),
            }
        )

    # Action items come from the agenda responsibilities…
    action_items = []
    for item in agenda:
        responsible = item["action"] or "IHP"
        status = "Completed" if item["etc"] and item["etc"].strip().lower() in ("done", "completed") else "Pending"
        text = (" ".join(item["lines"]))[:300]
        if item["trade"]:
            text = f"{item['trade']}: {text}"
        action_items.append(
            {
                "text": text or "N/A",
                "responsible": responsible,
                "status": "N/A" if not item["etc"] else status,
                "badge_class": badge_class(item["etc"] or status),
            }
        )
    # …and the tracker checklist, when the Planner recorded one.
    checklist = derived.get("checklist")
    if checklist:
        action_items.append(
            {
                "text": f"Tracker checklist status: {checklist}",
                "responsible": derived.get("assigned_to") or "IHP",
                "status": "Pending",
                "badge_class": "badge-amber",
            }
        )

    return {
        "pr_number": _value(project.pr_number),
        "title": _value(project.title),
        "revision_no": version_label,
        "document_code": context.get("document_code") or "",
        "kaust_logo": kaust_logo,
        "for_email": for_email,
        "meeting_rows": meeting_rows,
        "attendees": attendees,
        "invitation_lines": [
            line.strip()
            for line in str(details.get("invitation") or "").splitlines()
            if line.strip()
        ],
        "project_rows": project_rows,
        "status_rows": status_rows,
        "status_timeline": [str(step) for step in (derived.get("status_timeline") or [])],
        "agenda": agenda,
        "action_items": action_items,
        "generated_at": f"{date.today().isoformat()} ({_brief(project.pr_number, 40)})",
    }


def render_html(context: dict[str, Any]) -> str:
    """Render templates/mom_template.html with the given context."""
    template = _environment().get_template(_TEMPLATE_NAME)
    return template.render(**context)
