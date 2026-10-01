"""MOM (Minutes of Meeting) endpoints: generate, download, agenda, status."""

import copy
from datetime import datetime
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.rbac import (
    CAP_MOM_AGENDA,
    CAP_MOM_MANAGE,
    effective_permissions,
    get_current_user,
    require_capability,
)
from ..db import get_db
from ..models import MomRecord, Project, User
from ..schemas import MomAgendaItem, MomDetails, MomOut, MomStatusUpdate
from ..services import docgen, emailer, storage, workflow
from .projects import _derive_tracker_fields, get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/mom", tags=["mom"])

MOM_TEMPLATE_NAME = "mom_template.docx"

#: RBAC trade code -> trade label used in MOM agenda items.
TRADE_LABELS = {
    "civil_arch": "Civil/Architectural",
    "electrical": "Electrical",
    "low_current": "Low Current",
    "plumbing": "Plumbing",
    "fire_protection": "Fire Protection",
    "hvac": "HVAC",
    "macc": "MACC",  # KAUST FM contractor (custom trade, all-caps)
}


def trade_agenda_label(trade: str) -> str:
    """Agenda label for a trade code; custom trades fall back to a title-cased
    version of the code, keeping short acronyms uppercase
    ('macc' -> 'MACC', 'fire_alarm' -> 'Fire Alarm', 'bms_controls' -> 'BMS Controls')."""
    if trade in TRADE_LABELS:
        return TRADE_LABELS[trade]
    return " ".join(
        word.upper() if len(word) <= 3 else word.capitalize()
        for word in trade.replace("_", " ").split()
    )


def _stage_reached(current: str | None, target: str) -> bool:
    """True when the project has already reached (or passed) `target`.

    The lifecycle order lives in workflow.STAGES; an unknown stage falls back to
    "not reached" so the caller attempts the normal transition and its own
    validation reports the problem.
    """
    try:
        return workflow.STAGES.index(current or "") >= workflow.STAGES.index(target)
    except ValueError:
        return False


def get_mom_or_404(project: Project) -> MomRecord:
    if project.mom is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No MOM record for this project",
        )
    return project.mom


# House order for the agenda table (matches how the minute is read):
# Civil/Architectural -> Plumbing -> HVAC -> Electrical -> General, then any
# other/custom trade in the order it was entered.
TRADE_SORT_ORDER = [
    "civil/architectural",
    "plumbing",
    "hvac",
    "electrical",
    "general",
    "low current",
    "fire protection",
    "mechanical",
]


def _trade_rank(trade: str | None) -> int:
    """Position of a trade in the house order.

    Matches on the base name so qualifiers do not push a row to the end:
    "Civil/Architectural (Equipment Layout)" is still Civil/Architectural, and
    "Electrical:" is still Electrical.
    """
    key = (trade or "").strip().lower().rstrip(":").split("(")[0].strip()
    for index, known in enumerate(TRADE_SORT_ORDER):
        if key == known or key.startswith(known) or known.startswith(key) and key:
            return index
    return len(TRADE_SORT_ORDER)


def _sort_agenda_by_trade(agenda: list[dict]) -> list[dict]:
    def key(index_item):
        index, item = index_item
        return (_trade_rank(item.get("trade")), index)  # stable within a trade

    return [item for _, item in sorted(enumerate(agenda), key=key)]


#: Characters already used as bullets in the house format.
_BULLETS = ("Ø", "•", "-", "*", "▪")


def _agenda_display_scope(item: dict) -> str:
    """The scope cell as it must read in the minute: trade, then the work.

    The template prints a single {{ item.scope }} cell, so the trade name is
    written as the first line and every work item becomes a bullet below it:

        Plumbing:
        Ø Supply and install the 6-bar CDA network.
        Ø Test and commission to KAUST standards.

    docxtpl turns the newlines into real Word line breaks.
    """
    trade = (item.get("trade") or "").strip()
    scope = (item.get("scope") or item.get("description") or "").strip()
    body: list[str] = []
    for raw_line in scope.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        body.append(line if line.startswith(_BULLETS) else f"Ø {line}")
    # House style: bare trades get a colon ("Plumbing:"), a trade that
    # already ends in punctuation or a qualifier ("Civil/Architectural\n    # (Equipment Layout)") is left exactly as the user wrote it.
    heading = trade if not trade or trade.endswith((":", ".", ")")) else trade + ":"
    if heading:
        return heading + "\n" + "\n".join(body) if body else heading
    return "\n".join(body)


def _with_contributor(item: dict) -> dict:
    """Append the contributor mark to the action text (MOM document only).

    Returns a copy — the stored details keep action/added_by_* separate.
    """
    item = dict(item)
    name = item.get("added_by_name") or ""
    if name:
        title = item.get("added_by_title") or ""
        by = f"By: {name}" + (f", {title}" if title else "")
        action = (item.get("action") or "").strip()
        item["action"] = f"{action}\n{by}" if action else by
    return item


def build_mom_context(project: Project, details: dict, version: int) -> dict:
    """Template context for the KAUST MOM layout.

    Revision number is derived from the generation count (00, 01, ...) and
    the document code is a unique per-revision identifier.
    """
    revision_no = f"{version - 1:02d}"
    attendees = details.get("attendees") or []
    if not attendees and project.pi_name:
        attendees = [
            {
                "name": project.pi_name,
                "title": "Requester / PI",
                "email": project.pi_email or "",
            }
        ]
    agenda = details.get("agenda") or [
        {
            "scope": project.description or project.title,
            "action": "IHP",
            "etc": "",
        }
    ]
    agenda = _sort_agenda_by_trade(agenda)
    # Contributor mark ("By: name, title") — rendered in the MOM document only.
    agenda = [_with_contributor(item) for item in agenda]
    # The scope cell carries the trade heading followed by the work items.
    agenda = [{**item, "scope": _agenda_display_scope(item)} for item in agenda]
    # Outlook invitation pasted by the user (one entry per line, optional).
    invitation_lines = [
        line.strip()
        for line in str(details.get("invitation") or "").splitlines()
        if line.strip()
    ]
    return {
        "invitation_lines": invitation_lines,
        "pr_number": project.pr_number,
        "title": project.title,
        "revision_no": revision_no,
        "document_code": f"IHP-MOM-{project.pr_number}-R{revision_no}",
        "meeting_title": details.get("meeting_title")
        or f"{project.pr_number} — {project.title}",
        "meeting_location": details.get("meeting_location") or project.location or "",
        "meeting_number": details.get("meeting_number") or "01",
        "meeting_date": details.get("meeting_date")
        or datetime.now().strftime("%Y-%m-%d"),
        "meeting_time": details.get("meeting_time") or "",
        "attendees": attendees,
        "agenda": agenda,
        "funding_source": project.funding_source or "",
        "description": project.description or "",
        "items": [a.filename for a in project.attachments],
    }


@router.get("/defaults")
def mom_defaults(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Suggested meeting details for this project (KAUST template fields).

    Every value comes from the project itself so the MOM editor opens already
    filled: the title from the PR number + project name, the location from the
    register plus the O&M "Project Location Details" column, the meeting
    number from how many MOMs already exist, and today's date.
    """
    from datetime import date as _date

    from ..services import tracker_sources
    from ..services.tracker_import import parse_om

    project = get_project_or_404(db, project_id)

    # Location: register + O&M "Project Location Details".
    location = project.location or ""
    try:
        om_path = tracker_sources.om_path()
        if om_path:
            for row in parse_om(om_path):
                if row.pr_key == project.pr_number:
                    parts = [p for p in (row.location, row.location_details) if p]
                    if parts:
                        # Avoid repeating the building twice.
                        seen: list[str] = []
                        for p in parts:
                            if p not in seen:
                                seen.append(p)
                        location = " - ".join(seen)
                    break
    except Exception:  # noqa: BLE001 - defaults are best-effort
        pass

    existing = db.query(MomRecord).filter(MomRecord.project_id == project.id).count()
    number = f"{existing + 1:02d}"

    return {
        "meeting_title": f"{project.pr_number} {project.title}".strip(),
        "meeting_location": location,
        "meeting_number": number,
        "meeting_date": _date.today().isoformat(),
        "meeting_time": "10:00",
        "project_pr": project.pr_number,
        "project_title": project.title,
        "pi_name": project.pi_name,
        "pi_email": project.pi_email,
        "existing_moms": existing,
    }


@router.post("/generate", response_model=MomOut)
def generate_mom(
    project_id: int,
    payload: MomDetails | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_MOM_MANAGE)),
):
    project = get_project_or_404(db, project_id)

    # The MOM may be generated (and re-issued) at ANY stage.
    #
    # It used to be restricted to INTAKE / MOM_SENT, which made the screen
    # unusable for every project that arrives from the Planner tracker already
    # at EAR / Design / Construction: those projects still need their minutes
    # (and a corrected revision). Generating only records a document and an
    # audit entry - it never moves the stage - so there is nothing to protect
    # here. Stage changes remain guarded in workflow.transition().
    mom = project.mom
    version = (mom.version + 1) if mom else 1
    # A payload with actual content wins; an empty payload ({}) or no body
    # reuses the stored details so regeneration keeps the same meeting data.
    incoming = (
        {k: v for k, v in payload.model_dump().items() if v not in (None, [], {})}
        if payload is not None
        else {}
    )
    details = incoming or (mom.details if mom and mom.details else {})

    context = build_mom_context(project, details, version)

    mom_dir = storage.project_dir(project.pr_number, "mom")
    docx_name = f"MOM_{storage.safe_name(project.pr_number)}_v{version}.docx"
    docx_path = docgen.render_docx(MOM_TEMPLATE_NAME, context, mom_dir / docx_name)
    pdf_path = docgen.docx_to_pdf(docx_path)

    subject, body = emailer.build_mom_draft(
        project, context["items"], details=details, context=context
    )
    if mom is None:
        mom = MomRecord(project_id=project.id, version=version)
        db.add(mom)
    else:
        mom.version = version
    mom.status = "draft"
    mom.docx_filename = docx_path.name
    mom.pdf_filename = pdf_path.name if pdf_path else None
    mom.email_subject = subject
    mom.email_body = body
    mom.details = details
    mom.updated_by_id = user.id

    workflow.log_action(
        db, user, "mom:generate", project, {"version": version, "docx": docx_path.name}
    )
    db.commit()
    db.refresh(mom)
    return mom


@router.get("/download")
def download_mom(
    project_id: int,
    fmt: str = Query("docx", pattern="^(docx|pdf)$"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    mom = get_mom_or_404(project)
    if fmt == "pdf":
        if not mom.pdf_filename:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PDF was not generated for this MOM",
            )
        filename = mom.pdf_filename
        media_type = "application/pdf"
    else:
        filename = mom.docx_filename
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    path = storage.project_dir(project.pr_number, "mom") / filename
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MOM file missing on disk"
        )
    return FileResponse(path, filename=filename, media_type=media_type)


def _mom_html_body(project: Project, mom: MomRecord, details: dict) -> str | None:
    """The minute as HTML - what makes the email read like a web page."""
    from ..services import mom_html

    try:
        context = build_mom_context(project, details, mom.version)
        return mom_html.render_html(
            mom_html.build_html_context(
                project=project,
                details=details,
                derived=_derive_tracker_fields(project),
                version=mom.version,
                context=context,
                base_url=None,
                for_email=True,
            )
        )
    except Exception as exc:  # noqa: BLE001 - never block the email on formatting
        print(f"MOM html body failed: {exc}")
        return None


@router.get("/view", response_class=HTMLResponse)
def mom_web_view(
    project_id: int,
    base_url: str | None = Query(default=None, description="Where the logo is served from"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The minute as a self-contained HTML document.

    Used for the in-app preview (and downloadable as a web page). The same
    renderer produces the HTML body of the MOM email, so what the team reviews
    here is exactly what the recipient sees.
    """
    from ..services import mom_html

    project = get_project_or_404(db, project_id)
    mom = get_mom_or_404(project)
    details = mom.details or {}
    context = build_mom_context(project, details, mom.version)
    html = mom_html.render_html(
        mom_html.build_html_context(
            project=project,
            details=details,
            derived=_derive_tracker_fields(project),
            version=mom.version,
            context=context,
            base_url=base_url,
        )
    )
    return HTMLResponse(content=html)


@router.get("/email-link")
def mom_email_link(
    project_id: int,
    to: str | None = Query(default=None),
    cc: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """A mailto: link that opens the MOM directly in the local mail client.

    Nothing is attached (the minute is inline), which is what the desktop
    workflow wants: the sender reviews it in Outlook and attaches their own
    images or files before sending. Long bodies can be truncated by some
    handlers, so the .eml export stays available as the full-fidelity option.
    """
    from urllib.parse import quote

    project = get_project_or_404(db, project_id)
    mom = get_mom_or_404(project)
    details = mom.details or {}

    def _split(value: str | None) -> list[str]:
        return [
            part.strip()
            for part in (value or "").replace(";", ",").split(",")
            if part.strip()
        ]

    recipients = _split(to) or emailer.mom_recipients(project, details)
    context = build_mom_context(project, details, mom.version)
    _, body = emailer.build_mom_draft(
        project,
        context["items"],
        details=details,
        context=context,
        include_attachments=False,
    )
    subject = mom.email_subject or f"{emailer.pr_label(project)} - {project.title}"
    params = [f"subject={quote(subject)}", f"body={quote(body)}"]
    copied = _split(cc)
    if copied:
        params.append(f"cc={quote(','.join(copied))}")
    mailto = f"mailto:{quote(','.join(recipients))}?" + "&".join(params)
    return {
        "to": recipients,
        "cc": copied,
        "subject": subject,
        "body": body,
        "mailto": mailto,
        "body_chars": len(body),
        "note": (
            "Long emails can be truncated by mailto links; use the email file "
            "option if the text is cut off."
            if len(body) > 2400
            else None
        ),
    }


@router.get("/email.eml")
def mom_email_draft(
    project_id: int,
    to: str | None = Query(default=None, description="Comma separated recipients"),
    cc: str | None = Query(default=None),
    attach: bool = Query(default=True, description="Attach the MOM DOCX/PDF"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """A ready-to-send email file for the MOM (opens in Outlook on the desktop).

    The platform has no access to a mailbox, so instead of sending from the
    server this returns an .eml message: recipients, subject, body and the MOM
    attached. Opening it (double-click on Windows) gives a compose window in the
    user's own Outlook - it is sent from their account, and the sent copy stays
    in their Sent Items.

    `X-Unsent: 1` is what makes Outlook treat the file as an editable draft
    rather than a received message, and no From header is written so Outlook
    fills in the user's default account.
    """
    project = get_project_or_404(db, project_id)
    mom = get_mom_or_404(project)
    details = mom.details or {}

    def _split(value: str | None) -> list[str]:
        return [part.strip() for part in (value or "").replace(";", ",").split(",") if part.strip()]

    recipients = _split(to) or emailer.mom_recipients(project, details)
    if not recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No recipients: add participants to the MOM or pass ?to=email@example.com",
        )

    message = EmailMessage()
    message["Subject"] = mom.email_subject or f"PR {project.pr_number} - {project.title}"
    message["To"] = ", ".join(recipients)
    copied = _split(cc)
    if copied:
        message["Cc"] = ", ".join(copied)
    message["X-Unsent"] = "1"
    if attach:
        message.set_content(mom.email_body or "")
        html_body = _mom_html_body(project, mom, details)
        if html_body:
            message.add_alternative(html_body, subtype="html")
    else:
        # No document attached: the minute travels inside the email body instead,
        # so the sender can attach their own images/files in Outlook.
        fresh = build_mom_context(project, details, mom.version)
        _, body = emailer.build_mom_draft(
            project,
            fresh["items"],
            details=details,
            context=fresh,
            include_attachments=False,
        )
        message.set_content(body)
        html_body = _mom_html_body(project, mom, details)
        if html_body:
            message.add_alternative(html_body, subtype="html")

    mom_dir = storage.project_dir(project.pr_number, "mom")
    # The PDF needs LibreOffice, so it may be absent; the DOCX always exists.
    attachments = [
        (
            mom_dir / mom.docx_filename if mom.docx_filename else None,
            "application",
            "vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            mom_dir / mom.pdf_filename if mom.pdf_filename else None,
            "application",
            "pdf",
        ),
    ]
    if attach:
        for path, maintype, subtype in attachments:
            if path and path.exists():
                message.add_attachment(
                    path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
                )

    filename = f"MOM_{storage.safe_name(project.pr_number)}_v{mom.version}.eml"
    return Response(
        content=message.as_bytes(),
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


SUGGEST_SYSTEM = (
    "You are the KAUST IHP (In-House Projects) assistant. You draft the scope of "
    "work for a Minutes-of-Meeting from a lab-modification request. Be specific, "
    "practical and concise. Never invent a PR number or a person."
)

SUGGEST_PROMPT = """Draft the MOM agenda for this request.

Project: {pr} - {title}
Location: {location}
Requested work (PR request text): {description}
{attachments}{documents}
Rules:
- Group the work by trade, in EXACTLY this order, and skip a trade only when it
  has no work: Civil/Architectural, Plumbing, HVAC, Electrical, General.
- The General trade holds items another party (the proponent/PI) must do, e.g.
  toxic-gas purging and decommissioning by the Proponent.
- Each trade gets 2 to 6 short work items, one per line, written the way an IHP
  scope of work reads ("Supply and install ...", "Dismantle ...", "Testing &
  Commissioning as per KAUST Standards."). No bullet characters, no numbering.
- Action is "IHP" for work IHP executes and "PI" for work the proponent does.
- ETC stays "" unless the text gives a duration.

Reply with JSON only: a list of objects with keys trade, scope, action, etc.
Example: [{{"trade": "Plumbing", "scope": "Supply and install (1) new 6-bar CDA stainless-steel piping network.\nDismantle the existing gas networks.", "action": "IHP", "etc": ""}}]"""


@router.post("/suggest")
def suggest_mom_agenda(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_MOM_MANAGE)),
):
    """Let the AI agent draft the trade-wise agenda from the PR request.

    Returns suggestions only: nothing is stored until the user applies them, so
    the Planner keeps control of the minutes.
    """
    from ..ai import provider, retrieval
    from ..services.ai_materials import _extract_json_array

    project = get_project_or_404(db, project_id)
    if not provider.available()[0]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI provider is offline. Configure it in Settings and retry.",
        )

    # Ground the draft on the project's own uploaded documents when there are any.
    try:
        hits = retrieval.search(
            f"{project.title} scope of work", db, k=3, project_id=project.id, max_chars=700
        )
    except Exception:  # noqa: BLE001 — retrieval is best effort
        hits = []
    documents = ""
    if hits:
        documents = "\nUploaded documents (use them for the technical detail):\n" + "\n".join(
            f"- {hit['filename']}: {hit['text']}" for hit in hits
        )

    attachment_names = [a.filename for a in project.attachments]
    prompt = SUGGEST_PROMPT.format(
        pr=project.pr_number,
        title=project.title,
        location=project.location or "-",
        description=(project.description or project.title)[:4000],
        attachments=(
            "Attachments: " + ", ".join(attachment_names) + "\n" if attachment_names else ""
        ),
        documents=documents,
    )

    reply = provider.chat(
        [{"role": "user", "content": prompt}], system=SUGGEST_SYSTEM
    )
    if not reply:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI provider did not answer. Try again or add the items manually.",
        )
    items = _extract_json_array(reply) or []

    order = {name: index for index, name in enumerate(TRADE_SORT_ORDER)}
    cleaned: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("scope") or "").strip()
        if not scope:
            continue
        trade = str(item.get("trade") or "General").strip()
        cleaned.append(
            {
                "trade": trade,
                "scope": scope,
                "action": "PI" if str(item.get("action", "")).strip().upper() == "PI" else "IHP",
                "etc": str(item.get("etc") or "").strip(),
            }
        )
    cleaned.sort(key=lambda row: order.get(row["trade"].strip().lower(), len(order)))

    workflow.log_action(
        db,
        user,
        "mom:suggest",
        project,
        {"items": len(cleaned), "provider": provider.effective_provider(get_settings())},
    )
    db.commit()
    return {
        "items": cleaned,
        "count": len(cleaned),
        "raw": reply[:600],
    }


@router.post("/agenda", response_model=MomOut)
def add_agenda_item(
    project_id: int,
    payload: MomAgendaItem,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Append a scope item to the stored MOM agenda.

    Users with `mom.manage` may set any trade on the item; users with
    `mom.agenda` (trade users) can only add items for their own trade (the
    trade label is forced server-side). The item lands in the generated
    document on the next MOM regeneration.
    """
    if not payload.scope.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Scope text is required",
        )
    project = get_project_or_404(db, project_id)
    mom = get_mom_or_404(project)

    perms = effective_permissions(user)
    if CAP_MOM_MANAGE in perms:
        item_trade = payload.trade
    elif CAP_MOM_AGENDA in perms:
        if not user.trade:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your user has no trade assigned",
            )
        item_trade = trade_agenda_label(user.trade)
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission: mom.manage or mom.agenda",
        )

    details = copy.deepcopy(mom.details or {})
    agenda = list(details.get("agenda") or [])
    agenda.append(
        {
            "scope": payload.scope.strip(),
            "action": payload.action.strip(),
            "etc": payload.etc.strip(),
            "trade": item_trade,
            # Contributor mark: shown in the MOM document only.
            "added_by_name": user.full_name,
            "added_by_title": user.title or "",
        }
    )
    details["agenda"] = agenda
    mom.details = details
    mom.updated_by_id = user.id
    workflow.log_action(
        db,
        user,
        "mom:agenda_add",
        project,
        {"trade": item_trade, "scope": payload.scope.strip()[:80]},
    )
    db.commit()
    db.refresh(mom)
    return mom


def _agenda_at(mom: MomRecord, index: int) -> tuple[dict, list, dict]:
    details = copy.deepcopy(mom.details or {})
    agenda = list(details.get("agenda") or [])
    if index < 0 or index >= len(agenda):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No agenda item at index {index}",
        )
    return details, agenda, agenda[index]


def _check_item_access(user: User, item: dict) -> None:
    """mom.manage users modify any item; mom.agenda users only their own trade's."""
    perms = effective_permissions(user)
    if CAP_MOM_MANAGE in perms:
        return
    if (
        CAP_MOM_AGENDA in perms
        and user.trade
        and item.get("trade") == trade_agenda_label(user.trade)
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You can only modify your own trade's agenda items",
    )


@router.put("/agenda/{index}", response_model=MomOut)
def update_agenda_item(
    project_id: int,
    index: int,
    payload: MomAgendaItem,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Edit an agenda item. mom.agenda users edit only their own trade's items
    (trade and contributor are preserved); mom.manage users may also change
    the trade."""
    if not payload.scope.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Scope text is required",
        )
    project = get_project_or_404(db, project_id)
    mom = get_mom_or_404(project)
    details, agenda, item = _agenda_at(mom, index)
    _check_item_access(user, item)

    item["scope"] = payload.scope.strip()
    item["action"] = payload.action.strip()
    item["etc"] = payload.etc.strip()
    if CAP_MOM_MANAGE in effective_permissions(user) and payload.trade:
        item["trade"] = payload.trade
    agenda[index] = item
    details["agenda"] = agenda
    mom.details = details
    mom.updated_by_id = user.id
    workflow.log_action(db, user, "mom:agenda_edit", project, {"index": index})
    db.commit()
    db.refresh(mom)
    return mom


@router.delete("/agenda/{index}", response_model=MomOut)
def delete_agenda_item(
    project_id: int,
    index: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete an agenda item. mom.agenda users delete only their own trade's items."""
    project = get_project_or_404(db, project_id)
    mom = get_mom_or_404(project)
    details, agenda, item = _agenda_at(mom, index)
    _check_item_access(user, item)

    agenda.pop(index)
    details["agenda"] = agenda
    mom.details = details
    mom.updated_by_id = user.id
    workflow.log_action(
        db, user, "mom:agenda_delete", project, {"index": index, "scope": item.get("scope", "")[:80]}
    )
    db.commit()
    db.refresh(mom)
    return mom


@router.post("/status", response_model=MomOut)
def update_mom_status(
    project_id: int,
    payload: MomStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_MOM_MANAGE)),
):
    project = get_project_or_404(db, project_id)
    mom = get_mom_or_404(project)
    detail = {"note": payload.note} if payload.note else {}

    if payload.status == "sent":
        if mom.status not in ("draft", "disputed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot mark MOM as sent from status '{mom.status}'",
            )
        sent = emailer.send_email(project.pi_email, mom.email_subject, mom.email_body)
        if sent:
            detail["email_sent"] = True
        mom.status = "sent"
        if _stage_reached(project.stage, workflow.MOM_SENT):
            # Already at (or past) MOM_SENT - a Planner-imported project can be
            # at EAR_REVIEW here. Never move the stage backwards; just record it.
            workflow.log_action(db, user, "mom:sent", project, detail)
        else:
            workflow.transition(project, workflow.MOM_SENT, user, db, detail,
                                action="mom:sent")

    elif payload.status == "acknowledged":
        if mom.status != "sent":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot acknowledge MOM from status '{mom.status}'",
            )
        mom.status = "acknowledged"
        if _stage_reached(project.stage, workflow.MOM_CONFIRMED):
            workflow.log_action(db, user, "mom:acknowledged", project, detail)
        else:
            workflow.transition(project, workflow.MOM_CONFIRMED, user, db, detail,
                                action="mom:acknowledged")

    else:  # disputed
        if mom.status != "sent":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot dispute MOM from status '{mom.status}'",
            )
        if not payload.note:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A note is required when disputing a MOM",
            )
        mom.status = "disputed"
        mom.note = payload.note
        # Stage intentionally stays MOM_SENT.
        workflow.log_action(db, user, "mom:disputed", project, detail)

    mom.updated_by_id = user.id
    db.commit()
    db.refresh(mom)
    return mom
