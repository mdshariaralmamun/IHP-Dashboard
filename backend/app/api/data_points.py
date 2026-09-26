"""Source-tagged data points — the §3 traceability engine.

Every project data point carries a source tag (DOC / PLANNER / SITE / TBC /
ASSUMPTION). The CONFIRM action promotes a pending point (TBC / ASSUMPTION)
to PLANNER — Planner-only via the data.confirm capability — and every
create / update / confirm / delete is written to the audit log.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import (
    CAP_DATA_CONFIRM,
    CAP_DATA_MANAGE,
    get_current_user,
    require_capability,
)
from ..db import get_db
from ..models import DataPoint, Project, User, utcnow
from ..schemas import DataPointCreate, DataPointOut, DataPointUpdate
from ..services import workflow
from .projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/data-points", tags=["data-points"])

SourceTagParam = Literal["DOC", "PLANNER", "SITE", "TBC", "ASSUMPTION"]


def _get_point_or_404(project: Project, point_id: int, db: Session) -> DataPoint:
    dp = db.scalar(
        select(DataPoint).where(
            DataPoint.id == point_id, DataPoint.project_id == project.id
        )
    )
    if dp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data point {point_id} not found on project {project.id}",
        )
    return dp


def _require_doc_source(tag: str | None, source_file: str | None) -> None:
    """A DOC-tagged point must cite the file it was extracted from."""
    if tag == "DOC" and not source_file:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="DOC-tagged data points must cite a source_file.",
        )


@router.get("", response_model=list[DataPointOut])
def list_data_points(
    project_id: int,
    source_tag: SourceTagParam | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the project's tagged data points, optionally filtered by tag."""
    project = get_project_or_404(project_id, db)
    stmt = (
        select(DataPoint)
        .where(DataPoint.project_id == project.id)
        .order_by(DataPoint.category, DataPoint.field_key, DataPoint.id)
    )
    if source_tag is not None:
        stmt = stmt.where(DataPoint.source_tag == source_tag)
    return [DataPointOut.from_dp(dp) for dp in db.scalars(stmt)]


@router.post("", response_model=DataPointOut, status_code=status.HTTP_201_CREATED)
def create_data_point(
    project_id: int,
    body: DataPointCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_DATA_MANAGE)),
):
    """Register a tagged data point (any stage, any panel, or AI extraction)."""
    project = get_project_or_404(project_id, db)
    _require_doc_source(body.source_tag, body.source_file)
    dp = DataPoint(
        **body.model_dump(),
        project_id=project.id,
        created_by_id=user.id,
    )
    db.add(dp)
    db.flush()  # assign dp.id before the audit entry
    workflow.log_action(
        db,
        user,
        "datapoint:create",
        project,
        {
            "data_point_id": dp.id,
            "field_key": dp.field_key,
            "source_tag": dp.source_tag,
            "value": dp.value,
        },
    )
    db.commit()
    db.refresh(dp)
    return DataPointOut.from_dp(dp)


@router.patch("/{point_id}", response_model=DataPointOut)
def update_data_point(
    project_id: int,
    point_id: int,
    body: DataPointUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_DATA_MANAGE)),
):
    """Edit a data point. Changing `value` (or returning to a pending tag)
    voids the confirmation stamp — a confirmed value must be re-confirmed."""
    project = get_project_or_404(project_id, db)
    dp = _get_point_or_404(project, point_id, db)

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return DataPointOut.from_dp(dp)

    _require_doc_source(
        changes.get("source_tag", dp.source_tag),
        changes.get("source_file", dp.source_file),
    )

    before = {key: getattr(dp, key) for key in changes}
    for key, value in changes.items():
        setattr(dp, key, value)

    # Void the confirmation when the confirmed content is no longer current:
    # a changed value reverts the point to TBC (pending) until re-confirmed,
    # so no stale value ever reads as Planner-confirmed.
    value_changed = "value" in changes and changes["value"] != before["value"]
    went_pending = changes.get("source_tag") in ("TBC", "ASSUMPTION")
    voided = False
    if value_changed or went_pending:
        dp.confirmed_by_id = None
        dp.confirmed_at = None
        voided = True
        if value_changed:
            dp.source_tag = "TBC"

    workflow.log_action(
        db,
        user,
        "datapoint:update",
        project,
        {
            "data_point_id": dp.id,
            "field_key": dp.field_key,
            "old": before,
            "new": changes,
            "voided_confirmation": voided,
        },
    )
    db.commit()
    db.refresh(dp)
    return DataPointOut.from_dp(dp)


@router.post("/{point_id}/confirm", response_model=DataPointOut)
def confirm_data_point(
    project_id: int,
    point_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_DATA_CONFIRM)),
):
    """CONFIRM (§3): a Planner promotes a pending point (TBC / ASSUMPTION)
    to PLANNER, taking ownership of the value. Stamped + audited."""
    project = get_project_or_404(project_id, db)
    dp = _get_point_or_404(project, point_id, db)

    if dp.source_tag == "PLANNER" and dp.confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Already confirmed by {dp.confirmed_by.username if dp.confirmed_by else 'unknown'}"
            ),
        )
    if dp.source_tag not in ("TBC", "ASSUMPTION"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Only pending points (TBC / ASSUMPTION) can be confirmed; "
                f"this point is tagged {dp.source_tag}."
            ),
        )

    previous_tag = dp.source_tag
    dp.source_tag = "PLANNER"
    dp.confirmed_by_id = user.id
    dp.confirmed_at = utcnow()
    workflow.log_action(
        db,
        user,
        "datapoint:confirm",
        project,
        {
            "data_point_id": dp.id,
            "field_key": dp.field_key,
            "from": previous_tag,
            "to": "PLANNER",
            "value": dp.value,
        },
    )
    db.commit()
    db.refresh(dp)
    return DataPointOut.from_dp(dp)


@router.delete("/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_data_point(
    project_id: int,
    point_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_DATA_MANAGE)),
):
    """Delete a data point (audited — the value survives in the log entry)."""
    project = get_project_or_404(project_id, db)
    dp = _get_point_or_404(project, point_id, db)
    workflow.log_action(
        db,
        user,
        "datapoint:delete",
        project,
        {
            "data_point_id": dp.id,
            "field_key": dp.field_key,
            "source_tag": dp.source_tag,
            "value": dp.value,
        },
    )
    db.delete(dp)
    db.commit()
