"""Stage 1 intake helpers: parse an uploaded PR form export into intake fields."""

import base64

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from ..core.rbac import CAP_PROJECTS_CREATE, require_capability
from ..models import User
from ..services import pr_form_parser

router = APIRouter(prefix="/intake", tags=["intake"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".msg"}


@router.post("/parse-pr-form")
async def parse_pr_form(
    file: UploadFile,
    _user: User = Depends(require_capability(CAP_PROJECTS_CREATE)),
):
    """Parse a KAUST PR form export; returns intake fields, writes nothing.

    Accepts the PR form itself (PDF/DOCX/TXT) or an Outlook .msg (the PR
    form is usually attached inside the email). Any supported attachments
    found inside a .msg are returned as base64 `carried_files` so the caller
    can attach them to the created project.
    """
    filename = file.filename or ""
    ext = f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{ext or 'none'}' — upload the PR form as PDF, DOCX, TXT, or an Outlook .msg.",
        )
    content = await file.read()
    try:
        fields, carried = pr_form_parser.parse_any(filename, content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read the file: {exc}") from exc
    if not fields.get("pr_number"):
        raise HTTPException(
            status_code=422,
            detail="No PR number found — this doesn't look like a KAUST PR form or PR email.",
        )
    return {
        "project": pr_form_parser.to_intake(fields),
        "fields": fields,
        "carried_files": [
            {"filename": name, "content_base64": base64.b64encode(data).decode("ascii")}
            for name, data in carried
        ],
    }
