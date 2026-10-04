"""Stage 5: Material Take-Off (MTO) and Budget endpoints.

Handles MTO generation, budget suggestions from master pricing,
and Project Budget Summary tracking at MTO stage.
"""

import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..core.rbac import get_current_user, require_capability
from ..db import get_db
from ..models import (
    Project,
    MasterPricing,
    AiMaterialsProposal,
    ProjectBudgetSummary,
    ProjectStageBudget,
    BoqMtoItem,
    ConstructionRecord,
    User,
)
from ..schemas import (
    MasterPricingOut,
    MasterPricingIn,
    ProjectBudgetSummaryOut,
    ProjectStageBudgetOut,
    BoqMtoItemOut,
)
from ..services import ai_materials, workflow


router = APIRouter(prefix="/mto", tags=["mto_budget"])


# ---------------------------------------------------------------------------
# Master Pricing CRUD
# ---------------------------------------------------------------------------


@router.get("/pricing/{item_code}", response_model=MasterPricingOut)
def get_pricing_suggestion(
    item_code: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get unit rate suggestion from master pricing for an MTO item.

    Returns the base_unit_rate from master_pricing table.
    If not found, returns 0.0 with a note to add pricing or use historical.
    """
    pricing = db.scalar(
        select(MasterPricing).where(MasterPricing.item_code == item_code)
    )
    if pricing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pricing not found in master database for item: {item_code}. "
            "Use /api/admin/import-macc-pricing to add, or check historical pricing.",
        )
    return pricing


@router.get("/pricing", response_model=list[MasterPricingOut])
def list_pricing_suggestions(
    trade: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List all master pricing suggestions, optionally filtered by trade.

    Useful for browsing available rates before generating BOQ/MTO.
    """
    query = select(MasterPricing)
    if trade:
        query = query.where(MasterPricing.trade == trade)
    return db.scalars(query).all()


@router.post("/pricing", response_model=MasterPricingOut)
def upsert_pricing_suggestion(
    payload: MasterPricingIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_capability("users.manage")),
):
    """Add or update a master pricing suggestion.

    Requires users.manage capability. Typical use: admin imports MACC data
    or manually adds/updates unit rates.
    """
    from app.models import MasterPricing as MP

    existing = db.scalar(
        select(MP).where(MP.item_code == payload.item_code)
    )
    if existing:
        existing.description = payload.description
        existing.trade = payload.trade
        existing.unit = payload.unit
        existing.base_unit_rate = payload.base_unit_rate
        existing.currency = payload.currency or "SAR"
        existing.notes = payload.notes
        existing.last_updated = datetime.now(timezone.utc)
        db.add(existing)
    else:
        db.add(
            MasterPricing(
                item_code=payload.item_code,
                description=payload.description,
                trade=payload.trade,
                unit=payload.unit,
                base_unit_rate=payload.base_unit_rate,
                currency=payload.currency or "SAR",
                notes=payload.notes,
            )
        )
    db.commit()
    return db.scalar(
        select(MasterPricing).where(MasterPricing.item_code == payload.item_code)
    )




@router.post("/pricing/import", response_model=dict)
async def import_price_master(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_capability("users.manage")),
):
    """Import a price list into the master pricing table.

    Accepts what the Planner and the suppliers actually send: a markdown table
    exported from Excel, a CSV, or a priced workbook (BOQ / quotation). Rows
    are upserted on their REF and scoped to the file, so re-importing an
    updated list never touches MACC or manually entered prices.
    """
    from ..services import price_master

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty file."
        )
    name = file.filename or "price-list.md"
    suffix = Path(name).suffix.lower()
    with tempfile.TemporaryDirectory(prefix="ihp-price-") as work:
        path = Path(work) / name
        path.write_bytes(data)
        try:
            if suffix in {".xlsx", ".xlsm"}:
                rows = price_master.parse_xlsx_table(path)
            elif suffix in {".csv", ".tsv"}:
                rows = price_master.parse_csv_table(path)
            elif suffix in {".md", ".txt"}:
                rows = price_master.parse_markdown_table(path)
                if not rows:
                    rows = price_master.parse_csv_table(path)
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unsupported price list: {suffix or name}",
                )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not read the price list: {exc}",
            ) from exc
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No priced rows found (need REF, DESCRIPTION, Unit and a price column).",
            )
        result = price_master.sync_rows(db, rows, name)
    workflow.log_action(db, user, "pricing:import", None, result)
    db.commit()
    return result


@router.post("/pricing/sync", response_model=dict)
def sync_price_master(
    db: Session = Depends(get_db),
    user: User = Depends(require_capability("users.manage")),
):
    """Sync master pricing from the Planner's price-master markdown file.

    The file (PRICE_MASTER_PATH — env default, runtime-overridable in
    Settings) is the Planner's frequently-updated materials cost list.
    Rows are upserted keyed by the file's REF (the same item_code the
    budget generator matches BOQ items on); rows removed from the file
    are deactivated, never deleted. MACC/manual pricing rows are never
    touched. Re-run any time the Planner updates the file.
    """
    from ..core.config import get_settings
    from ..services import price_master, runtime_settings

    path = runtime_settings.effective(
        "PRICE_MASTER_PATH", get_settings().PRICE_MASTER_PATH
    )
    result = price_master.sync_from_file(db, path)
    if "error" in result:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result["error"])
    workflow.log_action(
        db, user, "pricing:sync", None,
        {k: v for k, v in result.items() if k != "note"},
    )
    db.commit()
    return result


# ---------------------------------------------------------------------------
# AI-coordinated materials proposals (assessment budget + MTO drafts)
# ---------------------------------------------------------------------------


class MaterialsProposalIn(BaseModel):
    """Body for POST /mto/project/{id}/materials-proposal."""

    #: "EAR" = assessment budget section, "MTO" = MTO draft
    stage_target: str = "MTO"
    #: optional trade filter (master codes: electrical, plumbing, hvac,
    #: civil_arch, low_current, fire_protection)
    trades: list[str] | None = None


class MaterialsProposalOut(BaseModel):
    id: int
    project_id: int
    stage_target: str
    status: str
    mode: str
    items: list
    subtotal_sar: float
    vat_sar: float
    total_sar: float
    model: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


def _proposal_or_404(db: Session, project_id: int, proposal_id: int):
    proposal = db.get(AiMaterialsProposal, proposal_id)
    if proposal is None or proposal.project_id != project_id:
        raise HTTPException(404, detail="Materials proposal not found")
    return proposal


@router.post(
    "/project/{project_id}/materials-proposal",
    response_model=MaterialsProposalOut,
    status_code=201,
)
def draft_materials_proposal(
    project_id: int,
    body: MaterialsProposalIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability("mto.manage")),
):
    """AI-coordinated draft of the trade-wise materials list + initial budget.

    Reads the project request + assessment (EAR) + SOW scope, matches the
    materials master list trade-wise, and asks the AI coordinator to pick
    items and estimate quantities. With the provider offline the
    deterministic keyword engine stands in (mode=keyword). Every item is a
    SUGGESTION (§3 ASSUMPTION) until accepted — the AI never writes to a BOQ.
    """
    if body.stage_target not in ("EAR", "MTO"):
        raise HTTPException(422, detail="stage_target must be EAR or MTO")
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(404, detail="Project not found")
    proposal = ai_materials.generate_proposal(
        db, project, user,
        stage_target=body.stage_target, trades=body.trades,
    )
    return proposal


@router.get(
    "/project/{project_id}/materials-proposals",
    response_model=list[MaterialsProposalOut],
)
def list_materials_proposals(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Proposal history for the project (drafts, accepts, rejects)."""
    return db.scalars(
        select(AiMaterialsProposal)
        .where(AiMaterialsProposal.project_id == project_id)
        .order_by(AiMaterialsProposal.id.desc())
    ).all()


@router.post(
    "/project/{project_id}/materials-proposals/{proposal_id}/accept",
    response_model=dict,
)
def accept_materials_proposal(
    project_id: int,
    proposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability("ai.proposal.accept")),
):
    """Accept a draft: suggestion lines become design BOQ/MTO rows priced
    from the master list. Requires the ai.proposal.accept capability."""
    proposal = _proposal_or_404(db, project_id, proposal_id)
    if proposal.status != "draft":
        raise HTTPException(409, detail=f"Proposal is already {proposal.status}")
    try:
        created = ai_materials.accept_proposal(db, proposal, user)
    except ValueError as e:
        raise HTTPException(409, detail=str(e))
    return {
        "proposal_id": proposal.id,
        "status": proposal.status,
        "boq_items_created": len(created),
        "item_codes": [c.item_code for c in created],
    }


@router.post(
    "/project/{project_id}/materials-proposals/{proposal_id}/reject",
    response_model=MaterialsProposalOut,
)
def reject_materials_proposal(
    project_id: int,
    proposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability("ai.proposal.accept")),
):
    """Reject a draft (kept in history for the audit trail)."""
    proposal = _proposal_or_404(db, project_id, proposal_id)
    if proposal.status != "draft":
        raise HTTPException(409, detail=f"Proposal is already {proposal.status}")
    try:
        return ai_materials.reject_proposal(db, proposal, user)
    except ValueError as e:
        raise HTTPException(409, detail=str(e))


# ---------------------------------------------------------------------------
# Project Budget Summary at MTO Stage
# ---------------------------------------------------------------------------


@router.get(
    "/project/{project_id}/budget-summary",
    response_model=ProjectBudgetSummaryOut,
)
def get_project_budget_summary(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get the budget summary snapshot for a project at its current MTO stage.

    Returns the most recent ProjectBudgetSummary row for the project,
    or creates one if none exists (for new projects).
    """
    from sqlalchemy import desc

    summary = (
        db.scalar(
            select(ProjectBudgetSummary)
            .where(ProjectBudgetSummary.project_id == project_id)
            .order_by(desc(ProjectBudgetSummary.snapshot_date))
        )
    )

    if summary is None:
        # Create initial summary at INTAKE/MOT stage
        from app.models import Project as P
        project = db.scalar(select(P).where(P.id == project_id))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        summary = ProjectBudgetSummary(
            project_id=project_id,
            stage_at_snapshot=project.stage or "INTAKE",
            snapshot_date=datetime.now(timezone.utc),
        )
        db.add(summary)
        db.commit()
        db.refresh(summary)

    return summary


@router.post(
    "/project/{project_id}/budget-summary",
    response_model=ProjectBudgetSummaryOut,
)
def create_project_budget_summary(
    project_id: int,
    stage: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_capability("users.manage")),
):
    """Create or overwrite a budget summary snapshot.

    Used when advancing to a new stage (e.g., moving from EAR to MTO).
    The stage parameter specifies the workflow stage at which this budget
    is being captured.
    """
    from app.models import Project as P

    project = db.scalar(select(P).where(P.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if summary already exists for this stage
    existing = db.scalar(
        select(ProjectBudgetSummary)
        .where(
            ProjectBudgetSummary.project_id == project_id,
            ProjectBudgetSummary.stage_at_snapshot == stage,
        )
    )

    if existing:
        # Refresh with current data
        db.delete(existing)
        db.commit()

    summary = ProjectBudgetSummary(
        project_id=project_id,
        stage_at_snapshot=stage or project.stage or "INTAKE",
        snapshot_date=datetime.now(timezone.utc),
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary


# ---------------------------------------------------------------------------
# Project Stage Budget Tracking
# ---------------------------------------------------------------------------


@router.get(
    "/project/{project_id}/stage-budget",
    response_model=list[ProjectStageBudgetOut],
)
def get_project_stage_budgets(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get all stage budget tracking rows for a project.

    Shows budget progression through the workflow stages.
    """
    rows = db.scalars(
        select(ProjectStageBudget).where(
            ProjectStageBudget.project_id == project_id
        )
    ).all()
    return rows


@router.post(
    "/project/{project_id}/stage-budget",
    response_model=ProjectStageBudgetOut,
)
def upsert_project_stage_budget(
    project_id: int,
    stage: str,
    budget_sar: float | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_capability("users.manage")),
):
    """Upsert a stage budget tracking row.

    Called when a project advances to a new workflow stage.
    Budget values can be auto-calculated from BOQ/MTO items.
    """
    from app.models import Project as P

    project = db.scalar(select(P).where(P.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check existing
    existing = db.scalar(
        select(ProjectStageBudget).where(
            ProjectStageBudget.project_id == project_id,
            ProjectStageBudget.stage == stage,
        )
    )

    if existing:
        row = existing
        if budget_sar is not None:
            row.budget_sar = budget_sar
    else:
        row = ProjectStageBudget(
            project_id=project_id,
            stage=stage,
            budget_sar=budget_sar or 0.0,
        )

    # Calculate committed/remaining if BOQ items exist
    boq_items = db.scalars(
        select(BoqMtoItem).where(BoqMtoItem.project_id == project_id)
    ).all()
    if boq_items and budget_sar is None:
        # Auto-calculate from BOQ using master pricing
        total = 0.0
        for item in boq_items:
            # Try master pricing first
            pricing = db.scalar(
                select(MasterPricing).where(
                    MasterPricing.item_code == item.item_code
                )
            )
            rate = pricing.base_unit_rate if pricing else item.unit_rate or 0.0
            total += rate * float(item.quantity or 0)
        row.committed_sar = total
        # Simple remaining = budget - committed (if budget known)
        if existing and existing.budget_sar:
            row.remaining_sar = max(0, existing.budget_sar - total)

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# MTO Budget Generation from Master Pricing
# ---------------------------------------------------------------------------


@router.post(
    "/project/{project_id}/generate-budget",
    response_model=dict,
)
def generate_mto_budget_from_pricing(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_capability("construction.manage")),
):
    """Generate MTO budget summary from master pricing.

    Steps:
    1. Fetch all BoqMtoItem rows for the project (design-kind only)
    2. Look up master pricing for each item_code
    3. Calculate subtotal, VAT, totals in SAR and USD
    4. Create/update ProjectBudgetSummary at MTO stage
    5. Return the budget breakdown

    This is the core endpoint for "suggesting" budget based on
    the imported MACC price list.
    """
    from sqlalchemy import desc

    from app.models import Project as P

    project = db.scalar(select(P).where(P.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 1. Fetch all design MTO items for this project
    boq_items = db.scalars(
        select(BoqMtoItem).where(
            BoqMtoItem.project_id == project_id,
            BoqMtoItem.mto_kind == "design",
        )
    ).all()

    if not boq_items:
        raise HTTPException(
            status_code=400,
            detail=f"No design MTO items found for project {project.pr_number}. "
            "Run /api/boq or /api/mto first.",
        )

    # 2. Calculate using master pricing
    subtotal_sar = 0.0
    items_detail = []

    for item in boq_items:
        # Look up master pricing
        pricing = db.scalar(
            select(MasterPricing).where(
                MasterPricing.item_code == item.item_code
            )
        )

        if pricing and pricing.base_unit_rate > 0:
            unit_rate = pricing.base_unit_rate
            source = "master_pricing"
        else:
            # Fall back to item's stored unit_rate
            unit_rate = float(item.unit_rate or 0.0)
            source = "item_stored"

        line_total = unit_rate * float(item.quantity or 0)

        items_detail.append(
            {
                "item_code": item.item_code,
                "description": item.description,
                "trade": item.trade,
                "unit": item.unit,
                "quantity": item.quantity,
                "unit_rate": unit_rate,
                "line_total": round(line_total, 2),
                "pricing_source": source,
            }
        )
        subtotal_sar += line_total

    # 3. VAT + totals — rates are admin-tunable at runtime
    # (Settings → Project Variables), KAUST standards by default.
    from ..services.runtime_settings import project_variables

    pvar = project_variables()
    vat_rate = pvar["VAT_RATE"]
    usd_sar_rate = pvar["USD_SAR_RATE"]
    vat_sar = round(subtotal_sar * vat_rate, 2)

    # 4. Totals
    total_sar = round(subtotal_sar + vat_sar, 2)
    total_usd = round(total_sar / usd_sar_rate, 2)

    # 5. Create/Update Budget Summary at MTO stage
    stage = project.stage or "INTAKE"
    summary = (
        db.scalar(
            select(ProjectBudgetSummary)
            .where(
                ProjectBudgetSummary.project_id == project_id,
                ProjectBudgetSummary.stage_at_snapshot == "MTO",
            )
            .limit(1)
        )
    )

    if summary is None:
        summary = ProjectBudgetSummary(
            project_id=project_id,
            stage_at_snapshot="MTO",
            subtotal_sar=subtotal_sar,
            vat_sar=vat_sar,
            total_sar=total_sar,
            total_usd=total_usd,
            items_count=len(boq_items),
        )
        db.add(summary)
    else:
        # Update existing
        summary.subtotal_sar = subtotal_sar
        summary.vat_sar = vat_sar
        summary.total_sar = total_sar
        summary.total_usd = total_usd
        summary.items_count = len(boq_items)
        summary.snapshot_date = datetime.now(timezone.utc)

    db.add(summary)

    # 6. Also update project_stage_budget for MTO stage
    stage_budget = (
        db.scalar(
            select(ProjectStageBudget)
            .where(
                ProjectStageBudget.project_id == project_id,
                ProjectStageBudget.stage == "MTO",
            )
            .limit(1)
        )
    )

    if stage_budget is None:
        stage_budget = ProjectStageBudget(
            project_id=project_id,
            stage="MTO",
            budget_sar=subtotal_sar,
            estimated_sar=total_sar,
            committed_sar=total_sar,
            remaining_sar=0.0,
        )
        db.add(stage_budget)
    else:
        stage_budget.budget_sar = subtotal_sar
        stage_budget.estimated_sar = total_sar
        stage_budget.committed_sar = total_sar
        # remaining = total - (previous committed if any)
        if stage_budget.budget_sar:
            stage_budget.remaining_sar = max(
                0, stage_budget.budget_sar - total_sar
            )
        else:
            stage_budget.remaining_sar = 0.0
        stage_budget.updated_date = datetime.now(timezone.utc)

    db.add(stage_budget)
    db.commit()
    db.refresh(summary)
    db.refresh(stage_budget)

    return {
        "project_id": project_id,
        "pr_number": project.pr_number,
        "stage": stage,
        "budget_generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary.to_dict(),
        "stage_budget": stage_budget.to_dict(),
        "items_detail": items_detail,
        "rates": {"vat_rate": vat_rate, "usd_sar_rate": usd_sar_rate},
        "pricing_source": "master_pricing_imported_from_MACC",
        "macc_file": "MACC - Items Price List - Quotation.xlsx",
    }