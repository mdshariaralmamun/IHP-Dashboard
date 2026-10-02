"""Labelled pins on a project's floor-plan drawings.

The workflow this serves: the drawing arrives as a PDF attachment (an export
of the AutoCAD plan), the engineer places pins on it - one per room or area -
and labels each with the PI and PR. When a PI changes, the label is edited;
when a location is divided between two PIs, it becomes two pins. What the
site looked like at any time is the trail of edits, not someone's memory.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import CAP_PROJECTS_EDIT, get_current_user, require_capability
from ..db import get_db
from ..models import Attachment, PlanMarker, Project, User
from .projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/markers", tags=["markers"])


class MarkerIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    pi_name: str | None = None
    pr_ref: str | None = None
    notes: str | None = None
    attachment_id: int | None = None
    page: int = 1
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)


class MarkerPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    pi_name: str | None = None
    pr_ref: str | None = None
    notes: str | None = None
    attachment_id: int | None = None
    page: int | None = None
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)


def _out(marker: PlanMarker) -> dict:
    return {
        "id": marker.id,
        "label": marker.label,
        "pi_name": marker.pi_name,
        "pr_ref": marker.pr_ref,
        "notes": marker.notes,
        "attachment_id": marker.attachment_id,
        "page": marker.page,
        "x": round(marker.x, 3),
        "y": round(marker.y, 3),
        "created_by": marker.created_by_id,
        "created_at": marker.created_at.isoformat() if marker.created_at else None,
        "updated_at": marker.updated_at.isoformat() if marker.updated_at else None,
    }


@router.get("")
def list_markers(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = get_project_or_404(db, project_id)
    rows = db.scalars(
        select(PlanMarker)
        .where(PlanMarker.project_id == project.id)
        .order_by(PlanMarker.id)
    ).all()
    return [_out(row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_marker(
    project_id: int,
    payload: MarkerIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    project = get_project_or_404(db, project_id)
    marker = PlanMarker(
        project_id=project.id,
        created_by_id=user.id,
        **payload.model_dump(),
    )
    db.add(marker)
    db.commit()
    db.refresh(marker)
    return _out(marker)


def _marker_or_404(db: Session, project: Project, marker_id: int) -> PlanMarker:
    marker = db.scalar(
        select(PlanMarker).where(
            PlanMarker.id == marker_id, PlanMarker.project_id == project.id
        )
    )
    if marker is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Marker not found")
    return marker


@router.patch("/{marker_id}")
def update_marker(
    project_id: int,
    marker_id: int,
    payload: MarkerPatch,
    db: Session = Depends(get_db),
    _user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    """Edit a pin: retitle it, move the PI, reposition it, re-point the note.

    Editing rather than deleting is the point - 'this area used to be one PI
    and was divided' must stay visible.
    """
    project = get_project_or_404(db, project_id)
    marker = _marker_or_404(db, project, marker_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(marker, field, value)
    db.commit()
    db.refresh(marker)
    return _out(marker)


@router.delete("/{marker_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_marker(
    project_id: int,
    marker_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    project = get_project_or_404(db, project_id)
    marker = _marker_or_404(db, project, marker_id)
    db.delete(marker)
    db.commit()


@router.get("/plan/{attachment_id}.png")
def plan_png(
    project_id: int,
    attachment_id: int,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """A floor-plan attachment rendered to PNG, for placing pins on.

    Pins are percent-of-page coordinates, so this render is only the canvas -
    any resolution shows them in the right spot. Cached beside the file.
    """
    project = get_project_or_404(db, project_id)
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.project_id == project.id,
        )
    )
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    source = Path(attachment.stored_path)
    if not source.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing on disk")
    if source.suffix.lower() != ".pdf":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Markers sit on PDF plans - export the drawing from AutoCAD as PDF.",
        )

    cached = source.with_suffix(f".p{page}.png")
    if not cached.exists():
        try:
            import fitz  # PyMuPDF

            document = fitz.open(source)
            if page > document.page_count:
                document.close()
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Page {page} is beyond the {document.page_count} this plan has.",
                )
            # Cap the render: a site plan is A0 and a fixed 2x would produce a
            # 11000px-wide PNG (tens of MB) for a canvas that is only ever
            # displayed at screen size. Pins are percent-of-page, so a smaller
            # render costs nothing.
            page_rect = document[page - 1].rect
            zoom = min(2.0, 4000.0 / max(page_rect.width, page_rect.height))
            pixmap = document[page - 1].get_pixmap(
                matrix=fitz.Matrix(max(zoom, 0.2), max(zoom, 0.2))
            )
            pixmap.save(cached)
            document.close()
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"This plan could not be rendered: {exc}",
            ) from exc
    return Response(
        content=cached.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400"},
    )
