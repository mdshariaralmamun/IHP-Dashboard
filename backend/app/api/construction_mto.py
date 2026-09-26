"""Construction MTO endpoints (/api/projects/{id}/construction-mto).

Per v2 spec Section 2: the Construction MTO is a separate, trackable
document that reconciles against the Design MTO (boq_mto_items) and flags
variances (quantity, spec substitutions, added/removed items).

Endpoint summary:
  GET    /                  List construction MTO items for the project.
  POST   /                  Add a construction MTO line (typically as-awarded).
  PATCH  /{item_id}         Update a construction MTO line + delivery status.
  DELETE /{item_id}         Remove a construction MTO line.
  POST   /reconcile         Compute variance_qty by matching item_code against
                            the design BOQ and recording a single audit row.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import CAP_MTO_MANAGE, get_current_user, require_capability
from ..db import get_db
from ..models import BoqMtoItem, ConstructionMtoItem, Project, User
from ..schemas import (
    ConstructionMtoItemCreate,
    ConstructionMtoItemOut,
    ConstructionMtoItemUpdate,
)
from ..services import workflow
from .projects import get_project_or_404

router = APIRouter(
    prefix="/projects/{project_id}/construction-mto", tags=["construction_mto"]
)


@router.get("", response_model=list[ConstructionMtoItemOut])
def list_construction_mto(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    return db.scalars(
        select(ConstructionMtoItem)
        .where(ConstructionMtoItem.project_id == project.id)
        .order_by(ConstructionMtoItem.trade, ConstructionMtoItem.item_code)
    ).all()


@router.post("", response_model=ConstructionMtoItemOut)
def add_construction_mto_item(
    project_id: int,
    body: ConstructionMtoItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_MTO_MANAGE)),
):
    project = get_project_or_404(db, project_id)
    total = float(body.quantity) * float(body.unit_rate)
    item = ConstructionMtoItem(
        project_id=project.id,
        trade=body.trade,
        item_code=body.item_code,
        description=body.description,
        unit=body.unit,
        quantity=body.quantity,
        unit_rate=body.unit_rate,
        total_rate=total,
        material_spec=body.material_spec,
        delivery_status="pending",
    )
    db.add(item)
    workflow.log_action(
        db,
        user,
        "construction_mto:item_added",
        project,
        {
            "trade": body.trade,
            "item_code": body.item_code,
            "total": total,
        },
    )
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=ConstructionMtoItemOut)
def update_construction_mto_item(
    project_id: int,
    item_id: int,
    body: ConstructionMtoItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_MTO_MANAGE)),
):
    project = get_project_or_404(db, project_id)
    item = db.get(ConstructionMtoItem, item_id)
    if not item or item.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Construction MTO item not found",
        )

    if body.description is not None:
        item.description = body.description
    if body.quantity is not None:
        item.quantity = body.quantity
    if body.unit_rate is not None:
        item.unit_rate = body.unit_rate
    if body.material_spec is not None:
        item.material_spec = body.material_spec
    if body.delivery_status is not None:
        item.delivery_status = body.delivery_status

    item.total_rate = float(item.quantity) * float(item.unit_rate)
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_construction_mto_item(
    project_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_MTO_MANAGE)),
):
    project = get_project_or_404(db, project_id)
    item = db.get(ConstructionMtoItem, item_id)
    if not item or item.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Construction MTO item not found",
        )
    db.delete(item)
    workflow.log_action(
        db,
        user,
        "construction_mto:item_deleted",
        project,
        {"trade": item.trade, "item_code": item.item_code},
    )
    db.commit()


@router.post("/reconcile")
def reconcile_against_design_mto(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_MTO_MANAGE)),
):
    """Compute variance_qty against the design BOQ (BoqMtoItem, mto_kind='design').

    For each construction MTO line, look up the matching design line by
    item_code and set:
        variance_qty   = construction.qty - design.qty
        variance_reason= (if abs(variance_qty) > 0) a default note that the
                         human engineer can edit afterwards.

    Lines on either side without a counterpart are recorded as variance
    entries in the audit log so the project team can review.
    """
    project = get_project_or_404(db, project_id)
    design_by_code: dict[str, BoqMtoItem] = {
        b.item_code: b
        for b in db.scalars(
            select(BoqMtoItem).where(
                BoqMtoItem.project_id == project.id,
                BoqMtoItem.mto_kind == "design",
            )
        ).all()
    }
    construction_lines = db.scalars(
        select(ConstructionMtoItem).where(ConstructionMtoItem.project_id == project.id)
    ).all()

    matched = 0
    variances = 0
    orphans: list[dict] = []
    for c in construction_lines:
        d = design_by_code.get(c.item_code)
        if d is None:
            orphans.append(
                {"kind": "construction_only", "item_code": c.item_code, "qty": c.quantity}
            )
            continue
        matched += 1
        diff = float(c.quantity) - float(d.quantity)
        c.variance_qty = diff
        if abs(diff) > 0:
            variances += 1
            c.variance_reason = c.variance_reason or (
                f"Construction qty {c.quantity} vs design {d.quantity} "
                f"(delta {diff:+}); review and edit if intentional."
            )
        c.updated_at = datetime.now(timezone.utc)

    design_codes = set(design_by_code.keys())
    construction_codes = {c.item_code for c in construction_lines}
    for code in design_codes - construction_codes:
        orphans.append(
            {
                "kind": "design_only",
                "item_code": code,
                "qty": design_by_code[code].quantity,
            }
        )

    workflow.log_action(
        db,
        user,
        "construction_mto:reconciled",
        project,
        {"matched": matched, "variances": variances, "orphans": len(orphans)},
    )
    db.commit()

    return {
        "matched": matched,
        "variances": variances,
        "orphans": orphans,
    }
