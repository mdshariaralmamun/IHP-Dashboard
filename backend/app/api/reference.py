"""The site's master reference, as data and as a location decoder."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.rbac import get_current_user
from ..db import get_db
from ..models import User
from ..services import reference

router = APIRouter(prefix="/reference", tags=["reference"])


@router.get("")
def reference_overview(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Buildings, lot codes and the LFO directory, plus corpus freshness."""
    reference.ensure_reference_indexed(db)
    return {
        "buildings": len(reference.buildings()),
        "lot_codes": len(reference.lot_codes()),
        "lfos": len(reference.lfos()),
        "note": "the AI corpus carries these as its site reference",
    }


@router.get("/buildings")
def list_buildings(_user: User = Depends(get_current_user)):
    return list(reference.buildings())


@router.get("/lot-codes")
def list_lot_codes(
    search: str | None = Query(default=None, description="Filter by text"),
    _user: User = Depends(get_current_user),
):
    rows = list(reference.lot_codes())
    if search:
        needle = search.strip().lower()
        rows = [r for r in rows if needle in r["description"].lower() or needle in r["code"]]
    return rows


@router.get("/lfos")
def list_lfos(_user: User = Depends(get_current_user)):
    return list(reference.lfos())


@router.get("/decode")
def decode(
    code: str = Query(..., description="5-3610, or B7 L2 A3"),
    _user: User = Depends(get_current_user),
):
    """Decode a room code or shorthand location against the master list."""
    decoded = reference.decode_location(code)
    if not decoded:
        return {"ok": False, "error": f"Could not decode {code!r}"}
    return {"ok": True, "input": code, **decoded,
            "described": reference.describe_location(code)}
