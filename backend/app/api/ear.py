"""EAR (Engineering Assessment Report) endpoints (/api/projects/{id}/ear).

Supports:
- Multi-trade technical proposals & conflict resolution (per-discipline RBAC)
- High-level budget calculations (materials + manpower + markups)
- AI standards & code compliance review gate
- Word & PDF document generation and download
"""

from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import provider, retrieval
from ..core.config import get_settings
from ..core.rbac import (
    CAP_EAR_INPUT,
    CAP_EAR_MANAGE,
    get_current_user,
    require_capability,
)
from ..db import get_db
from ..models import EarRecord, EarTradeInput, Project, User
from ..schemas import (
    EarBudgetUpdate,
    EarOut,
    EarTradeInputCreate,
    EarTradeInputOut,
    EarUpdate,
)
from ..services import ear_docgen, storage, workflow
from .projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/ear", tags=["ear"])


def get_or_create_ear(project: Project, db: Session, user: User) -> EarRecord:
    """Retrieve existing EarRecord or create initial draft.

    ICR-classified projects skip EAR entirely (per disposition decision); an
    EAR record must never be created for them, even defensively.
    """
    if project.ear is not None:
        return project.ear
    if project.disposition == "ICR":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="EAR is not part of the ICR fast-track workflow; this project routes to MTO only.",
        )

    settings = get_settings()
    rates = settings.budget_markup_rates or {
        "overhead": 0.10,
        "contingency": 0.15,
        "profit": 0.05,
        "escalation": 0.03,
    }
    ear = EarRecord(
        project_id=project.id,
        version=1,
        status="draft",
        summary=f"Engineering Assessment for {project.title} ({project.pr_number}) located at {project.location or 'KAUST Campus'}.",
        recommendations="Review trade proposals and proceed to detailed design (SOW / BOQ).",
        budget_data={
            "rates": rates,
            "trade_budgets": {},
            "billing_type": "pi_baseline"
            if project.funding_source != "ASEPC/IHP"
            else "asepc_ihp",
        },
        ai_review_findings=[],
        updated_by_id=user.id,
    )
    db.add(ear)
    db.commit()
    db.refresh(ear)
    return ear


@router.get("", response_model=EarOut)
def get_ear(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Fetch the EAR record for a project, creating a draft if it doesn't exist."""
    project = get_project_or_404(project_id, db)
    return get_or_create_ear(project, db, user)


@router.patch("", response_model=EarOut)
def update_ear(
    project_id: int,
    body: EarUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_EAR_MANAGE)),
):
    """Update EAR executive summary, recommendations, or status (planning/admin)."""
    project = get_project_or_404(project_id, db)
    ear = get_or_create_ear(project, db, user)

    if body.summary is not None:
        ear.summary = body.summary
    if body.recommendations is not None:
        ear.recommendations = body.recommendations
    if body.status is not None:
        ear.status = body.status
        if body.status == "under_review" and project.stage == workflow.EAR_DRAFT:
            project.stage = workflow.EAR_REVIEW
            workflow.log_action(db, user, "stage:EAR_REVIEW", project)
        elif body.status == "approved" and project.stage in (
            workflow.EAR_DRAFT,
            workflow.EAR_REVIEW,
        ):
            project.stage = workflow.EAR_APPROVED
            workflow.log_action(db, user, "stage:EAR_APPROVED", project)

    ear.updated_by_id = user.id
    ear.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ear)
    return ear


@router.post("/trade-input", response_model=EarTradeInputOut)
def upsert_trade_input(
    project_id: int,
    body: EarTradeInputCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_EAR_INPUT)),
):
    """Submit or update a trade proposal. Non-admins may only edit their assigned trade."""
    if user.role != "admin" and user.trade and user.trade != body.trade:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You can only submit input for your assigned trade ({user.trade}).",
        )

    project = get_project_or_404(project_id, db)
    ear = get_or_create_ear(project, db, user)

    # Check for existing trade input
    existing = db.scalar(
        select(EarTradeInput).where(
            EarTradeInput.ear_id == ear.id, EarTradeInput.trade == body.trade
        )
    )

    if existing:
        existing.proposal = body.proposal
        existing.comments = body.comments
        existing.missing_info = body.missing_info
        existing.has_conflict = body.has_conflict
        existing.conflict_reason_code = body.conflict_reason_code
        existing.conflict_resolution_note = body.conflict_resolution_note
        existing.estimated_materials_cost = body.estimated_materials_cost
        existing.estimated_manpower_cost = body.estimated_manpower_cost
        existing.updated_by_id = user.id
        existing.updated_at = datetime.now(timezone.utc)
        target = existing
    else:
        target = EarTradeInput(
            ear_id=ear.id,
            trade=body.trade,
            proposal=body.proposal,
            comments=body.comments,
            missing_info=body.missing_info,
            has_conflict=body.has_conflict,
            conflict_reason_code=body.conflict_reason_code,
            conflict_resolution_note=body.conflict_resolution_note,
            estimated_materials_cost=body.estimated_materials_cost,
            estimated_manpower_cost=body.estimated_manpower_cost,
            updated_by_id=user.id,
        )
        db.add(target)

    # Sync budget entry for this trade
    budget = dict(ear.budget_data or {})
    trade_budgets = dict(budget.get("trade_budgets", {}))
    trade_budgets[body.trade] = {
        "materials": body.estimated_materials_cost,
        "manpower": body.estimated_manpower_cost,
    }
    budget["trade_budgets"] = trade_budgets
    ear.budget_data = budget
    ear.updated_by_id = user.id

    workflow.log_action(
        db,
        user,
        f"ear:trade_input:{body.trade}",
        project,
        {
            "trade": body.trade,
            "has_conflict": body.has_conflict,
            "materials": body.estimated_materials_cost,
            "manpower": body.estimated_manpower_cost,
        },
    )

    db.commit()
    db.refresh(target)
    return target


@router.post("/budget", response_model=EarOut)
def update_budget(
    project_id: int,
    body: EarBudgetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_EAR_MANAGE)),
):
    """Update high-level budget rates and funding billing distribution."""
    project = get_project_or_404(project_id, db)
    ear = get_or_create_ear(project, db, user)

    budget = dict(ear.budget_data or {})
    if body.rates:
        budget["rates"] = body.rates
    if body.trade_budgets:
        budget["trade_budgets"] = body.trade_budgets
    budget["billing_type"] = body.billing_type

    ear.budget_data = budget
    ear.updated_by_id = user.id
    workflow.log_action(
        db,
        user,
        "ear:budget_updated",
        project,
        {"billing_type": body.billing_type},
    )
    db.commit()
    db.refresh(ear)
    return ear


@router.post("/ai-review")
def run_ai_compliance_review(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Run AI cross-check of EAR trade proposals against KAUST standards, codes, and precedent."""
    project = get_project_or_404(project_id, db)
    ear = get_or_create_ear(project, db, user)

    trade_texts = []
    for ti in ear.trade_inputs:
        trade_texts.append(
            f"Trade: {ti.trade}\nProposal: {ti.proposal}\nComments: {ti.comments}\nMissing info: {ti.missing_info}"
        )
    combined_scope = "\n\n".join(trade_texts) if trade_texts else project.description

    findings = []
    chat_available, _ = provider.available()

    if chat_available and combined_scope:
        # Retrieve standards & code precedents
        hits = retrieval.search(f"KAUST standards design criteria code requirements for {combined_scope[:300]}", db, k=5)
        context = "\n\n".join(f"[{h['filename']}] {h['text']}" for h in hits)
        prompt = (
            f"Review this engineering proposal for {project.title} (Location: {project.location}):\n\n"
            f"{combined_scope}\n\n"
            f"Applicable reference context:\n{context}\n\n"
            f"Identify any technical conflicts, code citations (NFPA, ASHRAE, IBC, Saudi Building Code), "
            f"or omissions. Return a JSON list of objects with keys: "
            f"['trade', 'type' (conflict/omission/code_reference/suggestion), 'description', 'citation', 'resolution']."
        )
        ai_resp = provider.chat(
            [{"role": "user", "content": prompt}],
            system="You are the KAUST IHP Senior Review Engineer. Return ONLY a valid JSON list of finding objects."
        )
        if ai_resp:
            try:
                # Clean code blocks if present
                clean_json = ai_resp.strip()
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                parsed = json.loads(clean_json)
                if isinstance(parsed, list):
                    findings = parsed
            except Exception:
                pass

    if not findings:
        # Heuristic rules when AI is offline or returns empty
        for ti in ear.trade_inputs:
            if ti.has_conflict:
                findings.append({
                    "trade": ti.trade,
                    "type": "conflict",
                    "description": f"Trade conflict logged: {ti.conflict_reason_code or 'Unspecified reason'}",
                    "citation": "KAUST IHP Project Delivery Framework Sec. 3.2",
                    "resolution": ti.conflict_resolution_note or "Requires trade alignment meeting."
                })
            if "exhaust" in ti.proposal.lower() and "chilled" not in combined_scope.lower():
                findings.append({
                    "trade": "hvac",
                    "type": "suggestion",
                    "description": "Lab exhaust modification detected — verify makeup air balance and chilled water capacity.",
                    "citation": "ASHRAE Lab Design Guide / KAUST Design Criteria Div 23",
                    "resolution": "Cross-check utility matrix with Facility Operations."
                })
            if "electrical" in ti.trade.lower() and "ups" not in ti.proposal.lower():
                findings.append({
                    "trade": "electrical",
                    "type": "code_reference",
                    "description": "Sensitive equipment power feed — verify clean ground and UPS backup compliance.",
                    "citation": "NFPA 70 / SBC 401 Electrical Installations",
                    "resolution": "Confirm isolated ground receptacle specifications."
                })

    ear.ai_review_findings = findings
    ear.updated_by_id = user.id
    workflow.log_action(
        db,
        user,
        "ear:ai_review",
        project,
        {"finding_count": len(findings)},
    )
    db.commit()
    db.refresh(ear)
    return {"findings": findings, "count": len(findings)}


@router.post("/generate", response_model=EarOut)
def generate_ear_doc(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_EAR_MANAGE)),
):
    """Render the official EAR Word document and PDF via template."""
    project = get_project_or_404(project_id, db)
    ear = get_or_create_ear(project, db, user)

    out_docx = (
        storage.project_dir(project.pr_number, "ear")
        / f"EAR_{project.pr_number}_Rev{ear.version:02d}.docx"
    )
    docx_filename, pdf_filename = ear_docgen.generate_ear_document(
        project, ear, out_docx
    )

    ear.docx_filename = docx_filename
    ear.pdf_filename = pdf_filename
    ear.updated_by_id = user.id
    ear.updated_at = datetime.now(timezone.utc)

    workflow.log_action(
        db,
        user,
        "ear:generated",
        project,
        {"docx": docx_filename, "pdf": pdf_filename, "version": ear.version},
    )

    db.commit()
    db.refresh(ear)
    return ear


@router.get("/download")
def download_ear(
    project_id: int,
    fmt: str = Query("docx", pattern="^(docx|pdf)$"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Download the generated EAR document in Word (.docx) or PDF format."""
    project = get_project_or_404(project_id, db)
    if project.ear is None or not project.ear.docx_filename:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="EAR document has not been generated yet.",
        )

    filename = (
        project.ear.pdf_filename
        if fmt == "pdf" and project.ear.pdf_filename
        else project.ear.docx_filename
    )
    path = storage.project_dir(project.pr_number, "ear") / filename
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File {filename} not found on server disk.",
        )

    media_type = (
        "application/pdf"
        if fmt == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(path=path, media_type=media_type, filename=filename)
