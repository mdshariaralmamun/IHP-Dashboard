"""Tracker upload + mismatch endpoints (admin).

These endpoints are the HTTP surface for the import workflow:

* POST /api/admin/import/planner  — upload the MS Project xlsx, run the
  planner importer in-memory, return the per-PR write plan, then apply
  the writes (or just dry-run if ?dry_run=true).
* POST /api/admin/import/om       — upload the O&M xlsx, parse, return
  the parsed rows. No DB writes (the O&M is used only for cross-checking).
* GET  /api/admin/import/mismatches — read the last cached mismatch
  report (or recompute if not present).
* POST /api/admin/import/mismatches/recompute — explicitly rebuild the
  report from the latest cached uploads.

Uploads are accepted as multipart/form-data with a single `file` field.
The server stores the uploaded xlsx in backend/data/imports/ and caches
the parsed result in process memory. (For a single-tenant dev tool this
is fine; multi-tenant needs a proper per-user file store.)
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import CAP_USERS_MANAGE, require_capability
from ..db import get_db
from ..models import Project, User
from ..services import tracker_import
from ..services.tracker_import import (
    PlannerRow, OmRow, PrMismatch, compare, parse_om, parse_planner, summarise,
)
# import_planner exists as a script; reuse its core logic.
import sys
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import import_planner  # type: ignore
_run_planner_import = import_planner.import_xlsx
_planner_map_stage = import_planner.map_stage


router = APIRouter(prefix="/admin/import", tags=["admin_import"])


def _trackers_status():
    """What the trackers folder currently resolves to (newest dated file)."""
    from ..core.config import get_settings
    from ..services import runtime_settings, tracker_files

    s = get_settings()
    overrides = runtime_settings.read_overrides()
    return tracker_files.tracker_status(
        overrides.get("TRACKERS_DIR") or s.TRACKERS_DIR,
        overrides.get("PR_REQUEST_DIR") or s.PR_REQUEST_DIR,
    )

#: Where uploaded tracker files live on disk. Cleared by --recompute.
IMPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "imports"
IMPORT_DIR.mkdir(parents=True, exist_ok=True)

#: In-process cache of the latest parsed tracker state.
#: Multi-process deployments would need a shared cache (e.g. Redis).
_cache: dict[str, Any] = {
    "planner_path": None,
    "om_path": None,
    "planner_parsed_at": None,
    "om_parsed_at": None,
    "mismatches_computed_at": None,
    "mismatches": None,
    "mismatch_summary": None,
}


def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    """Stream an UploadFile to disk and return the saved path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Use the original filename, sanitized
    safe = Path(upload.filename or "upload.xlsx").name
    # Stamp with epoch to avoid clobbering on repeat uploads
    target = dest_dir / f"{int(time.time())}_{safe}"
    with target.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return target


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

@router.post("/planner")
def upload_planner(
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Upload a MS Project tracker xlsx and import it.

    The script `import_planner.import_xlsx()` runs the same logic as the
    CLI. We pass it the saved path. After import, we re-parse via
    `parse_planner()` and cache the rows for the mismatch endpoint.
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".md")):
        raise HTTPException(status_code=400, detail="File must be .xlsx or .md")

    saved = _save_upload(file, IMPORT_DIR)
    _cache["planner_path"] = saved

    # Run the importer (creates / updates projects, writes audit logs)
    processed = _run_planner_import(saved, dry_run=dry_run)

    # Reparse for the cache (cheap; the importer just did the work)
    rows = parse_planner(saved)
    _cache["planner_parsed_at"] = time.time()
    _cache["planner_rows"] = rows

    # Auto-recompute mismatches if the O&M is already cached
    if _cache.get("om_path"):
        _recompute(db)

    return {
        "saved_to": str(saved),
        "rows_processed": processed,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# O&M
# ---------------------------------------------------------------------------

@router.post("/om")
def upload_om(
    file: UploadFile = File(...),
    sheet: str = Form(" In House Projects"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Upload an O&M tracker xlsx and cache the parsed result.

    No DB writes — the O&M is the secondary source used for
    cross-checking only. Mismatches against the planner + DB are
    recomputed on demand (and on subsequent planner uploads).
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".md")):
        raise HTTPException(status_code=400, detail="File must be .xlsx or .md")
    saved = _save_upload(file, IMPORT_DIR)
    _cache["om_path"] = saved
    try:
        rows = parse_om(saved, sheet=sheet)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _cache["om_parsed_at"] = time.time()
    _cache["om_rows"] = rows
    _recompute(db)
    return {
        "saved_to": str(saved),
        "rows_parsed": len(rows),
        "sheet": sheet,
    }


# ---------------------------------------------------------------------------
# Mismatches
# ---------------------------------------------------------------------------

def _recompute(db: Session) -> None:
    """Rebuild the cached mismatch report from current cache state."""
    planner = _cache.get("planner_rows") or []
    om = _cache.get("om_rows") or []
    db_rows = [{
        "pr_number": p.pr_number, "title": p.title, "stage": p.stage,
        "location": p.location, "pi_name": p.pi_name, "division": None,
    } for p in db.scalars(select(Project)).all()]
    mismatches = compare(planner, om, db_rows)
    _cache["mismatches"] = [m.to_dict() for m in mismatches]
    _cache["mismatches_computed_at"] = time.time()
    _cache["mismatch_summary"] = summarise(mismatches)


@router.get("/mismatches")
def get_mismatches(
    limit: int = Query(100, ge=1, le=1000),
    only_conflicts: bool = Query(False),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Return the cached mismatch report. If the cache is empty (e.g.
    the server just restarted), rebuild it from the latest uploaded
    files. If nothing has been uploaded, return an empty report.
    """
    if _cache.get("mismatches") is None:
        # Try to rebuild from any uploaded files
        planner_path = _cache.get("planner_path")
        om_path = _cache.get("om_path")
        if planner_path and Path(planner_path).exists():
            _cache["planner_rows"] = parse_planner(Path(planner_path))
        if om_path and Path(om_path).exists():
            _cache["om_rows"] = parse_om(Path(om_path))
        _recompute(db)
    items = _cache.get("mismatches") or []
    if only_conflicts:
        items = [m for m in items if m.get("mismatches")]
    return {
        "summary": _cache.get("mismatch_summary") or {},
        "computed_at": _cache.get("mismatches_computed_at"),
        "planner_path": str(_cache.get("planner_path") or ""),
        "om_path": str(_cache.get("om_path") or ""),
        "items": items[:limit],
        "total": len(items),
    }


@router.post("/mismatches/recompute")
def recompute_mismatches(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    planner_path = _cache.get("planner_path")
    om_path = _cache.get("om_path")
    if planner_path and Path(planner_path).exists():
        _cache["planner_rows"] = parse_planner(Path(planner_path))
    if om_path and Path(om_path).exists():
        _cache["om_rows"] = parse_om(Path(om_path))
    _recompute(db)
    return {"ok": True, "summary": _cache.get("mismatch_summary") or {}}


@router.post("/mismatches/resolve")
def resolve_mismatch(
    pr_key: str = Form(...),
    field: str = Form(...),
    source: str = Form(...),  # "planner" or "om"
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Apply a single conflict resolution: write the chosen source's
    value into the DB. This is how the user 'finalizes which is the
    real data'.
    """
    if source not in ("planner", "om"):
        raise HTTPException(400, "source must be 'planner' or 'om'")
    # Find the value
    value: Any = None
    if source == "planner":
        rows: list[PlannerRow] = _cache.get("planner_rows") or []
        for r in rows:
            if r.pr_key == pr_key:
                value = getattr(r, _planner_attr(field), None)
                break
    else:
        rows2: list[OmRow] = _cache.get("om_rows") or []
        for r in rows2:
            if r.pr_key == pr_key:
                value = getattr(r, _om_attr(field), None)
                break
    if value is None:
        raise HTTPException(404, f"No value for {pr_key}.{field} in {source}")
    # Find the project
    project = db.scalar(select(Project).where(Project.pr_number == pr_key))
    if project is None:
        raise HTTPException(404, f"Project {pr_key} not in DB")
    # Map the field to a Project column
    db_col = _db_column_for(field)
    if db_col is None:
        raise HTTPException(400, f"Field {field!r} cannot be written to Project")
    setattr(project, db_col, value)
    from ..models import AuditLog
    db.add(AuditLog(
        project_id=project.id, user_id=_admin.id,
        action=f"import:resolve:{source}",
        detail={"field": field, "value": str(value)[:200]},
    ))
    db.commit()
    return {"ok": True, "pr_key": pr_key, "field": field, "new_value": str(value)}


# Field-mapping helpers --------------------------------------------------

_FIELD_TO_PLANNER = {
    "location": "building",
    "division": "division",
    "pi_name": "pi_name",
    "start": "start",
    "finish": "finish",
}
_FIELD_TO_OM = {
    "location": "location",
    "division": "division",
    # "pi_name" is NOT mapped to O&M requestor — the O&M requestor field
    # contains IHP team members, not the Principal Investigator. The PI
    # comes from the PR intake form and is stored directly in the DB.
    "start": "plan_start",
    "finish": "plan_finish",
}
_FIELD_TO_DB = {
    "location": "location",
    "pi_name": "pi_name",
    # "division" / "start" / "finish" have no native column on Project
    # and are stored in description — resolving those is v2.
}


def _planner_attr(field: str) -> str:
    return _FIELD_TO_PLANNER.get(field, field)


def _om_attr(field: str) -> str:
    return _FIELD_TO_OM.get(field, field)


def _db_column_for(field: str) -> str | None:
    return _FIELD_TO_DB.get(field)


# ---------------------------------------------------------------------------
# Auto mode — track the newest dated file, no manual upload
# ---------------------------------------------------------------------------

@router.get("/sources")
def tracker_sources(
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Which tracker files the system resolves to RIGHT NOW.

    Always the newest ``_DDMMYYYY`` version of each tracker, considering
    both the .xlsx and .md exports. This is what powers the "Synced from"
    banner on the dashboard.
    """
    return _trackers_status()


@router.post("/auto")
def auto_import(
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Import the NEWEST dated planner tracker and cache the newest O&M one.

    No file upload needed: the trackers folder is scanned and the latest
    ``_DDMMYYYY`` export of each file is used (a newer `.md` export beats an
    older `.xlsx`, which is the normal Planner pattern). Read-only when
    ``?dry_run=true``.
    """
    status = _trackers_status()
    planner_path = status.get("planner_path")
    om_path = status.get("om_path")

    if not planner_path:
        raise HTTPException(
            404,
            f"No planner tracker found in {status.get('trackers_dir')}. "
            "Expected a file starting with 'IHP- Construction Projects' "
            "ending in _DDMMYYYY.xlsx or .md.",
        )

    saved = Path(planner_path)
    processed = _run_planner_import(saved, dry_run=dry_run)

    _cache["planner_path"] = saved
    _cache["planner_rows"] = parse_planner(saved)
    _cache["planner_parsed_at"] = time.time()

    om_rows = 0
    if om_path:
        try:
            _cache["om_path"] = Path(om_path)
            _cache["om_rows"] = parse_om(Path(om_path))
            _cache["om_parsed_at"] = time.time()
            om_rows = len(_cache["om_rows"])
        except Exception:  # noqa: BLE001 — O&M is a secondary cross-check
            _cache["om_rows"] = []

    _recompute(db)
    return {
        "ok": True,
        "dry_run": dry_run,
        "planner_file": Path(planner_path).name,
        "planner_date": status.get("planner_date"),
        "rows_processed": processed,
        "om_file": Path(om_path).name if om_path else None,
        "om_date": status.get("om_date"),
        "om_rows": om_rows,
        "mismatch_summary": _cache.get("mismatch_summary") or {},
    }
