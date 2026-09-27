"""MOM email draft building + optional SMTP sending.

When SMTP_HOST is not configured the platform is draft-only: drafts are
stored on the MomRecord and nothing is sent.
"""

import smtplib
from email.message import EmailMessage

from ..core.config import get_settings
from ..models import Project


def mom_recipients(project: Project, details: dict | None = None) -> list[str]:
    """Every participant email for a MOM, plus the PI (deduplicated).

    The MOM goes to the meeting participants; the PI is added because they own
    the request. Order is preserved so the organiser stays first.
    """
    details = details or {}
    emails: list[str] = []

    def add(value: str | None) -> None:
        candidate = (value or "").strip().strip(";,<>")
        if candidate and "@" in candidate and candidate.lower() not in [
            e.lower() for e in emails
        ]:
            emails.append(candidate)

    for attendee in details.get("attendees") or []:
        if isinstance(attendee, dict):
            add(attendee.get("email"))
    add(project.pi_email)
    return emails


def build_mom_draft(
    project: Project,
    items: list[str],
    details: dict | None = None,
    context: dict | None = None,
    include_attachments: bool = True,
) -> tuple[str, str]:
    """Return (subject, body) for the MOM email.

    When the meeting details are supplied the body carries the same structure as
    the minute itself: when/where it took place, who attended and the agenda with
    its Action by / ETC columns.
    """
    subject = f"PR {project.pr_number} – {project.title} – Request confirmation"
    lines = [
        f"Dear {project.pi_name or 'Principal Investigator'},",
        "",
        "please find below the Minutes of Meeting summary for your project "
        "request and confirm its accuracy.",
        "",
        f"PR Number:      {project.pr_number}",
        f"Title:          {project.title}",
        f"Location:       {project.location or '-'}",
        f"PI Name:        {project.pi_name or '-'}",
        f"PI Email:       {project.pi_email or '-'}",
        f"Funding Source: {project.funding_source or '-'}",
        "",
        "Description:",
        project.description or "-",
    ]

    details = details or {}
    meeting = []
    if details.get("meeting_title"):
        meeting.append(f"Meeting:        {details['meeting_title']}")
    if details.get("meeting_number"):
        meeting.append(f"Meeting number: {details['meeting_number']}")
    if details.get("meeting_date") or details.get("meeting_time"):
        when = " ".join(
            part for part in (details.get("meeting_date"), details.get("meeting_time")) if part
        )
        meeting.append(f"Date & time:    {when}")
    if details.get("meeting_location"):
        meeting.append(f"Venue:          {details['meeting_location']}")
    if meeting:
        lines += ["", "Meeting details:", *meeting]

    invitation = str(details.get("invitation") or "").strip()
    if invitation:
        lines += ["", "Invitation:", *[f"  {line}" for line in invitation.splitlines()]]

    attendees = details.get("attendees") or []
    if attendees:
        lines += ["", f"Participants ({len(attendees)}):"]
        for person in attendees:
            if not isinstance(person, dict):
                continue
            name = person.get("name") or "-"
            title_text = person.get("title") or ""
            email = person.get("email") or ""
            suffix = " - ".join(part for part in (title_text, email) if part)
            lines.append(f"  - {name}" + (f" ({suffix})" if suffix else ""))

    agenda = (context or {}).get("items") or details.get("agenda") or []
    if agenda:
        lines += [
            "",
            "Agenda - Preliminary Scope of Work",
            "",
            "Sn.#  Scope of Work  |  Action by  |  ETC",
        ]
        for index, item in enumerate(agenda, start=1):
            if not isinstance(item, dict):
                continue
            trade = (item.get("trade") or "").strip()
            scope = (item.get("scope") or item.get("description") or "").strip()
            action_by = (item.get("action") or "").strip() or "-"
            etc = (item.get("etc") or "").strip() or "-"
            lines.append(f"{index}. {trade or 'General'}")
            for chunk in scope.splitlines() or [scope]:
                lines.append(f"     {chunk.strip()}")
            lines.append(f"     Action by: {action_by}    ETC: {etc}")
            lines.append("")

    if include_attachments:
        lines += ["Attachments:"]
        if items:
            lines.extend(f"  - {name}" for name in items)
        else:
            lines.append("  - none")
    lines += [
        "",
        "Kind regards,",
        "IHP Project Delivery Platform",
    ]
    return subject, "\n".join(lines)


def send_email(to: str | None, subject: str, body: str) -> bool:
    """Send an email via SMTP. Returns False when SMTP is not configured
    (draft-only mode) or no recipient is available."""
    settings = get_settings()
    if not settings.smtp_configured or not to:
        return False
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER or "ihp@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as smtp:
        smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
        smtp.send_message(msg)
    return True
