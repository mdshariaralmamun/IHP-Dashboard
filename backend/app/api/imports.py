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

An upload is PUBLISHED: the file is saved into the app's tracker store
(`<DATA_DIR>/trackers`, on the persisted data volume) under its own dated
name, so the resolver in `services/tracker_sources` immediately treats it
as the newest version of that tracker and every consumer — the register,
the consistency check, the O&M active-PR list, the Project Summary / SOW /
MOM context, the dashboard banner — reads the file that was just uploaded.
Re-uploading the same dated export replaces the earlier copy, so the store
holds exactly one file per version and never grows without bound.

A dry run (`?dry_run=true`) is staged in the scratch folder instead: it is
parsed for the mismatch report but never becomes the version the app reads.

Uploads are accepted as multipart/form-data with a single `file` field.
The parsed rows are additionally cached in process memory for the mismatch
report. (For a single-tenant dev tool this is fine; multi-tenant needs a
proper per-user file store.)
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.rbac import CAP_USERS_MANAGE, require_capability
from ..db import get_db
from ..models import Project, User
from ..services import tracker_files, tracker_import, tracker_sources
from ..services.tracker_import import (
    PlannerRow, OmRow, PrMismatch, compare, parse_om, parse_planner, summarise,
)
# import_planner exists as a script; reuse its core logic.
# Imported defensively: a missing scripts/ directory must degrade this one
# endpoint, not crash the entire API at startup.
import sys

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
try:  # pragma: no cover - depends on the deployment layout
    import import_planner  # type: ignore

    _run_planner_import = import_planner.import_xlsx
    _planner_map_stage = import_planner.map_stage
    IMPORTER_AVAILABLE = True
except Exception:  # noqa: BLE001 - report clearly instead of dying
    _run_planner_import = None  # type: ignore[assignment]
    _planner_map_stage = None  # type: ignore[assignment]
    IMPORTER_AVAILABLE = False


router = APIRouter(prefix="/admin/import", tags=["admin_import"])


def _require_importer() -> None:
    """Fail this endpoint clearly when the importer module is not deployed."""
    if not IMPORTER_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail=(
                "The planner importer is not available in this deployment: "
                "scripts/import_planner.py was not included in the image."
            ),
        )


def _trackers_status() -> dict[str, Any]:
    """What the app resolves to right now (newest dated file per tracker).

    Spans the upload store and the Planner's drop folder; see
    `services.tracker_sources`.
    """
    return tracker_sources.status()


#: Scratch folder for in-flight and dry-run uploads. Deliberately NOT one of
#: the folders `tracker_sources` searches: a file only becomes the version
#: the app reads once it has been parsed successfully and published.
IMPORT_DIR = Path(get_settings().DATA_DIR) / "imports"
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


def _canonical_name(filename: str, prefix: str) -> str:
    """A store name the resolver can actually match for `prefix`.

    A correctly named export — `IHP- Construction Projects_30092026.xlsx`,
    `O&M Project Progress Tracking Sheet Sep 2025_30092026.xlsx` — is kept
    as it is. Anything else (`planner.xlsx`, a "Copy of ..." download, a
    renamed file) is stored as `<prefix>_<DDMMYYYY>`, keeping the date the
    original name carried and using today's when it carried none.

    Without this, an upload could sit in the store forever and still never
    be resolved: resolution matches on the tracker's filename prefix.
    """
    path = Path(Path(filename or "").name)
    if path.stem.lower().startswith(prefix.lower()):
        return path.name
    suffix = path.suffix.lower() or ".xlsx"
    date = tracker_files.suffix_date(path.stem) or datetime.now()
    return f"{prefix}_{date.strftime('%d%m%Y')}{suffix}"


def _save_upload(upload: UploadFile, prefix: str) -> Path:
    """Stream an uploaded tracker into the scratch folder; return its path.

    The stored name is the canonical, dated one the resolver matches on, so
    publishing it later keeps the date that decides which version wins.
    Written to `<name>.part` and renamed, so a reader never sees a
    half-written workbook.
    """
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = tracker_files.ensure_dated(
        _canonical_name(upload.filename or "", prefix)
    )
    target = IMPORT_DIR / name
    staging = target.with_name(target.name + ".part")
    with staging.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    staging.replace(target)
    return target


def _publish(staged: Path) -> Path:
    """Promote a staged upload into the tracker store the app resolves.

    This is what "the upload synchronised" actually means: the file joins
    `<DATA_DIR>/trackers` under its dated name, so the newest-date resolver
    picks it for every consumer from this request onwards. A store copy is
    replaced in place when the same version is uploaded again.
    """
    dest_dir = tracker_sources.upload_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / staged.name
    staging = target.with_name(target.name + ".part")
    shutil.copyfile(staged, staging)
    staging.replace(target)
    # The published copy is the one that matters; don't leave the scratch
    # file behind (a dry run stops here, so it keeps its staged copy).
    staged.unlink(missing_ok=True)
    return target


def _om_sheet_present(path: Path, sheet: str) -> bool:
    """Does the workbook carry the O&M sheet?

    Reads sheet NAMES only (read-only mode), so it costs milliseconds even
    for the 2 MB / 277-row O&M workbook — cheap enough to run before
    publishing, unlike the full row parse.
    """
    if path.suffix.lower() == ".md":
        return True
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        return sheet in wb.sheetnames
    finally:
        wb.close()


def _active(prefix: str) -> dict[str, Any]:
    """The live version of one tracker (`planner_latest` / `om_latest`)."""
    status = tracker_sources.status()
    key = "planner" if prefix == tracker_sources.PLANNER_PREFIX else "om"
    return {
        "active_file": status.get(f"{key}_latest"),
        "active_date": status.get(f"{key}_date"),
        "active_source": status.get(f"{key}_source"),
        "active_path": status.get(f"{key}_path"),
        "sources": status,
    }


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

    staged = _save_upload(file, tracker_sources.PLANNER_PREFIX)

    # Validate first: a workbook the parser cannot read must never reach the
    # store, or a broken file would become the version every consumer reads.
    try:
        rows = parse_planner(staged)
    except Exception as e:  # noqa: BLE001 - report a 400, not a 500
        staged.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"Could not read the planner export: {e}"
        ) from e
    _cache["planner_parsed_at"] = time.time()
    _cache["planner_rows"] = rows

    # Publish BEFORE importing. Publishing is a file copy; the import walks
    # every row and writes the register, which can outlive Cloudflare's
    # ~100 s proxy limit. The upload has to become the live version even if
    # the browser never receives this response — worst case the user presses
    # "Sync latest tracker" afterwards to apply the DB writes.
    saved = staged if dry_run else _publish(staged)
    _cache["planner_path"] = saved

    # Run the importer (creates / updates projects, writes audit logs)
    _require_importer()
    processed = _run_planner_import(saved, dry_run=dry_run)

    # Auto-recompute mismatches if the O&M is already cached
    if _cache.get("om_path"):
        _recompute(db)

    return {
        "saved_to": str(saved),
        "published": not dry_run,
        "rows_processed": processed,
        "dry_run": dry_run,
        **_active(tracker_sources.PLANNER_PREFIX),
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
    staged = _save_upload(file, tracker_sources.OM_PREFIX)

    # Never publish a workbook the parser rejects: that would make a broken
    # file the newest version the whole app reads. The sheet check is cheap
    # (sheet names only) so the publish below stays instant; reading all 277
    # rows is the slow part and happens after the file is already live.
    try:
        sheet_present = _om_sheet_present(staged, sheet)
    except Exception as e:  # noqa: BLE001 - unreadable/corrupt workbook
        staged.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"Could not read the O&M workbook: {e}"
        ) from e
    if not sheet_present:
        staged.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"O&M sheet {sheet!r} not found in the workbook.",
        )

    saved = _publish(staged)
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
        "published": True,
        "rows_parsed": len(rows),
        "sheet": sheet,
        **_active(tracker_sources.OM_PREFIX),
    }


# ---------------------------------------------------------------------------
# Mismatches
# ---------------------------------------------------------------------------

def _load_cached_trackers() -> None:
    """Parse the trackers the app currently resolves into the report cache.

    Runs whenever the cache is cold — a fresh worker, or the first request
    after a restart — so the mismatch report describes the live tracker
    versions instead of coming back empty. An explicit dry-run staging path
    already in the cache is left alone.
    """
    planner_path = _cache.get("planner_path") or tracker_sources.planner_path()
    om_path = _cache.get("om_path") or tracker_sources.om_path()
    if planner_path and Path(planner_path).exists():
        _cache["planner_path"] = Path(planner_path)
        _cache["planner_rows"] = parse_planner(Path(planner_path))
        _cache["planner_parsed_at"] = time.time()
    if om_path and Path(om_path).exists():
        _cache["om_path"] = Path(om_path)
        _cache["om_rows"] = parse_om(Path(om_path))
        _cache["om_parsed_at"] = time.time()


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
        _load_cached_trackers()
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
    _load_cached_trackers()
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
    # The Planner's PI column is "Requestor/PI" (col 27); "Assigned to"
    # (col 3) is the IHP engineer, never a Principal Investigator.
    "pi_name": "requestor",
    "assigned_to": "assigned_to",
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
def tracker_sources_status(
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
    _require_importer()
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
