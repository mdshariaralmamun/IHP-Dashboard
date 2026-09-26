"""MOM email draft building + optional SMTP sending.

When SMTP_HOST is not configured the platform is draft-only: drafts are
stored on the MomRecord and nothing is sent.
"""

import smtplib
from email.message import EmailMessage

from ..core.config import get_settings
from ..models import Project


def build_mom_draft(project: Project, items: list[str]) -> tuple[str, str]:
    """Return (subject, body) for the MOM confirmation email to the PI."""
    subject = f"PR {project.pr_number} \u2013 {project.title} \u2013 Request confirmation"
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
        "",
        "Attachments:",
    ]
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
