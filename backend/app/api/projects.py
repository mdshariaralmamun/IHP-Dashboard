"""Project endpoints: intake, attachments, detail, audit trail."""

from pathlib import Path
from typing import Any
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..core.rbac import (
    CAP_ATTACHMENTS_DELETE,
    CAP_ATTACHMENTS_UPLOAD,
    CAP_PROJECTS_CREATE,
    CAP_PROJECTS_DELETE,
    CAP_PROJECTS_EDIT,
    CAP_SOW_MANAGE,
    CAP_USERS_MANAGE,
    get_current_user,
    require_capability,
)
from ..db import get_db
from ..models import Attachment, AuditLog, Project, User
from ..schemas import (
    AttachmentOut,
    AuditOut,
    ProjectCreate,
    ProjectDetail,
    ProjectListItem,
    ProjectUpdate,
)
from ..services import storage, workflow

router = APIRouter(prefix="/projects", tags=["projects"])


def get_project_or_404(db: Session, project_id: int) -> Project:
    """Load a Project row or raise 404. Accepts either (db, project_id)
    or (project_id, db) so legacy / unfixed call sites keep working while
    the rest of the codebase converges on the canonical order.
    """
    # If a caller passed the args in the wrong order, swap them.
    if isinstance(db, int) and not isinstance(project_id, int):
        db, project_id = project_id, db
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    return project


def _remove_file_best_effort(stored_path: str) -> None:
    """Delete a stored file from disk; missing/unremovable files are ignored."""
    try:
        Path(stored_path).unlink(missing_ok=True)
    except OSError:
        pass


@router.get("", response_model=list[ProjectListItem])
def list_projects(
    stage: str | None = None,
    disposition: str | None = None,
    search: str | None = None,
    source: str | None = None,
    bucket: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List projects, optionally filtered.

    Supported query params:
      * `stage`     exact match, repeatable in future via comma split
      * `disposition` exact match
      * `search`   substring match against pr_number/title/pi_name/location
      * `source`   "planner" | "om" | "manual" | "demo" — set on each
                   project based on which import path created it.
      * `bucket`   IHP planner Bucket (EAR, DESIGN, PTW/WICF, CONSTRUCTION,
                   QUALITY INSPECTION, WCH, WCC, ...) — exact match,
                   case-insensitive.
    """
    stmt = select(Project)
    if stage:
        stmt = stmt.where(Project.stage == stage)
    if disposition:
        stmt = stmt.where(Project.disposition == disposition)
    if bucket:
        stmt = stmt.where(Project.planner_bucket == bucket.strip().upper())
    if search:
        pat = f"%{search}%"
        stmt = stmt.where(
            (Project.pr_number.ilike(pat))
            | (Project.ear_number.ilike(pat))
            | (Project.title.ilike(pat))
            | (Project.pi_name.ilike(pat))
            | (Project.location.ilike(pat))
        )
    if source:
        # Source is stored in description; the filter is post-load
        # (SQLite can't easily query JSON in description text).
        pass
    stmt = stmt.order_by(Project.id.desc())
    items = db.scalars(stmt).all()

    # The newest Planner snapshot date decides which rows are CURRENT.
    # A PR that disappeared from the tracker (cancelled, or moved to the
    # O&M equipment branch) keeps its older sync date and is flagged stale
    # so it never inflates the live division counts.
    derived_all = [(p, _derive_tracker_fields(p)) for p in items]
    snapshot = max(
        (d["planner_sync_date"] for _, d in derived_all if d["planner_sync_date"]),
        default=None,
    )

    out = []
    for p, derived in derived_all:
        if source and derived["source"] != source:
            continue
        current = (
            derived["planner_sync_date"] is not None
            and derived["planner_sync_date"] == snapshot
        )
        out.append(ProjectListItem(
            id=p.id, pr_number=p.pr_number, title=p.title,
            pi_name=p.pi_name, location=p.location,
            funding_source=p.funding_source, stage=p.stage,
            disposition=p.disposition, created_at=p.created_at,
            planner_bucket=p.planner_bucket,
            in_latest_planner=current,
            **derived,
        ))
    return out


def _derive_tracker_fields(p) -> dict:
    """Parse tracker-imported fields out of p.description.

    Returns a dict matching the new ProjectListItem fields.
    """
    desc = p.description or ""
    out = {
        "project_type": None, "trades": [], "division": None,
        "priority": None, "completion_pct": None, "source": None,
        # Notes/Labels analysis (services/planner_status.py)
        "latest_status": None, "latest_status_date": None,
        "status_timeline": [], "flags": [], "checklist": None,
        "phase": None, "planner_sync_date": None, "ear_substatus": None,
        "ear_approved_date": None,
        # Who the Planner assigned the task to, plus the execution lead and
        # the requestor/PI column (all three are separate people/roles).
        "assigned_to": None, "execution_lead": None, "requestor": None,
        # Planner schedule fields (drive the construction dashboard)
        "start_date": None, "finish_date": None, "effort": None, "duration": None,
    }
    if not desc:
        return out
    for line in desc.splitlines():
        if line.startswith("Type: "):
            out["project_type"] = line[6:].strip() or None
        elif line.startswith("Trades: "):
            out["trades"] = [t.strip() for t in line[8:].split(",") if t.strip()]
        elif line.startswith("Division: "):
            out["division"] = line[10:].strip() or None
        elif line.startswith("Priority: "):
            prio = line[10:].strip()
            # A few Planner rows are column-shifted, so the "Priority" cell
            # can hold a whole note; only accept real priority words.
            out["priority"] = (
                prio if prio.lower() in {"urgent", "important", "medium", "low", "high", "normal"}
                else None
            )
        elif line.startswith("Latest Status: "):
            out["latest_status"] = line[15:].strip() or None
        elif line.startswith("Status Date: "):
            out["latest_status_date"] = line[13:].strip() or None
        elif line.startswith("Status Timeline: "):
            out["status_timeline"] = [
                s.strip() for s in line[17:].split("->") if s.strip()
            ]
        elif line.startswith("Flags: "):
            out["flags"] = [s.strip() for s in line[7:].split(",") if s.strip()]
        elif line.startswith("Checklist: "):
            out["checklist"] = line[11:].strip() or None
        elif line.startswith("Phase: "):
            out["phase"] = line[7:].strip() or None
        elif line.startswith("Planner Sync: "):
            out["planner_sync_date"] = line[14:].strip() or None
        elif line.startswith("Assigned To: "):
            out["assigned_to"] = line[13:].strip() or None
        elif line.startswith("Execution Lead: "):
            out["execution_lead"] = line[16:].strip() or None
        elif line.startswith("Requestor: "):
            out["requestor"] = line[11:].strip() or None
        elif line.startswith("EAR Status: "):
            out["ear_substatus"] = line[12:].strip() or None
        elif line.startswith("EAR Approved Date: "):
            out["ear_approved_date"] = line[19:].strip() or None
        elif line.startswith("Start: "):
            out["start_date"] = line[7:].strip() or None
        elif line.startswith("Finish: "):
            out["finish_date"] = line[8:].strip() or None
        elif line.startswith("Effort: "):
            out["effort"] = line[8:].strip() or None
        elif line.startswith("Duration: "):
            out["duration"] = line[10:].strip() or None
        elif line.startswith("Completion: "):
            try:
                out["completion_pct"] = int(line[12:].rstrip("%").strip())
            except ValueError:
                pass
    # Division falls back to bucket/flag/stage resolution when the row
    # predates the analyzer (e.g. a project created by hand).
    if out["phase"] is None:
        from ..services.planner_status import phase_for
        out["phase"] = phase_for(
            bucket=p.planner_bucket, stage=p.stage, flags=out["flags"]
        )
    # Source: planner imports always carry "Type:" in the description
    # (seeded/manual ones do not). Check for any structured tracker key.
    if out["project_type"] or out["trades"] or out["division"] or out["priority"]:
        out["source"] = "planner"
    return out


#: Consistency runs re-parse the whole O&M workbook, so the result is
#: cached briefly: the dashboard polls it on every page load.
_consistency_cache: dict[str, Any] = {"at": 0.0, "path": None, "payload": None}
_CONSISTENCY_TTL_SECONDS = 120


@router.get("/construction-live")
def construction_live(
    include_closed: bool = False,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Planner-driven construction schedule board.

    Groups the active work by how close it is to its Planner finish date
    (overdue / today / this week / 2 weeks / 3 weeks / this month), with the
    urgency, the stage gate still to be finished, the prorated man-hours per
    day needed, and the delay risks (overdue, on hold, behind plan, or
    blocked by a late Design / MTO / Procore gate).
    """
    from datetime import date as _date

    from ..services.schedule import (
        WINDOWS, WINDOW_LABELS, build_item,
    )

    rows = db.scalars(select(Project)).all()
    derived_all = [(p, _derive_tracker_fields(p)) for p in rows]
    snapshot = max(
        (d["planner_sync_date"] for _, d in derived_all if d["planner_sync_date"]),
        default=None,
    )
    today = _date.today()

    items = []
    unscheduled = 0
    for p, d in derived_all:
        if snapshot and d["planner_sync_date"] != snapshot:
            continue
        if not include_closed and d.get("phase") == "Close-up":
            continue
        if not d.get("finish_date"):
            unscheduled += 1
            continue
        items.append(build_item(p, d, today=today))

    windows: dict[str, list] = {w: [] for w in WINDOWS}
    for it in items:
        if it.window:
            windows[it.window].append(it.to_dict())
    for w in WINDOWS:
        windows[w].sort(key=lambda x: (x.get("days_left") if x.get("days_left") is not None else 9999))

    risk_high = [i.to_dict() for i in items if i.risk_level == "high"]
    risk_medium = [i.to_dict() for i in items if i.risk_level == "medium"]
    design_blockers = [
        i.to_dict() for i in items if "design gate" in i.risks or i.phase == "Design"
    ]
    design_blockers.sort(key=lambda x: x.get("days_left") if x.get("days_left") is not None else 9999)

    return {
        "today": today.isoformat(),
        "window_labels": WINDOW_LABELS,
        "summary": {w: len(windows[w]) for w in WINDOWS},
        "total_scheduled": len(items),
        "unscheduled": unscheduled,
        "risk": {
            "high": len(risk_high),
            "medium": len(risk_medium),
            "design_blockers": len(design_blockers),
            "high_items": risk_high[:40],
        },
        "windows": windows,
        "design_blockers": design_blockers[:40],
    }


@router.get("/consistency")
def consistency_report(
    refresh: bool = False,
    _user: User = Depends(get_current_user),
):
    """Cross-check the Planner against the O&M tracker and list every
    disagreement (missing PRs, type conflicts, completion conflicts).

    The dashboard raises a blinking alert whenever `summary.errors` or
    `summary.warnings` is non-zero.
    """
    import time as _time

    from ..core.config import get_settings
    from ..services import runtime_settings, tracker_files
    from ..services.consistency import check
    from ..services.tracker_import import (
        parse_om, parse_om_active_prs, parse_planner,
    )

    s = get_settings()
    overrides = runtime_settings.read_overrides()
    status = tracker_files.tracker_status(
        overrides.get("TRACKERS_DIR") or s.TRACKERS_DIR,
        overrides.get("PR_REQUEST_DIR") or s.PR_REQUEST_DIR,
    )
    planner_path = status.get("planner_path")
    om_path = status.get("om_path")
    if not planner_path or not om_path:
        return {
            "ok": False,
            "error": "Both a Planner and an O&M tracker are required for the check.",
            "summary": {},
            "issues": [],
        }

    key = f"{planner_path}|{om_path}"
    fresh = (_time.time() - float(_consistency_cache["at"] or 0)) < _CONSISTENCY_TTL_SECONDS
    if (
        not refresh
        and fresh
        and _consistency_cache["path"] == key
        and _consistency_cache["payload"] is not None
    ):
        return _consistency_cache["payload"]

    report = check(
        parse_planner(planner_path),
        parse_om(om_path),
        parse_om_active_prs(om_path),
    )
    payload = {
        "ok": True,
        "planner_file": status.get("planner_latest"),
        "planner_date": status.get("planner_date"),
        "om_file": status.get("om_latest"),
        "om_date": status.get("om_date"),
        **report.to_dict(),
    }
    _consistency_cache.update({"at": _time.time(), "path": key, "payload": payload})
    return payload


@router.get("/om-active")
def om_active_prs(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Active PRs from the O&M tracker, split by IHP classification.

    The O&M workbook classifies every active request. Only
    "Construction Project" counts as IHP active work: the equipment branch
    (equipment installation / lab-equipment assessment, ICR) is a separate
    stream that adds no construction modification or utility tie-in, so it
    is reported separately and never merged into the IHP counts.
    """
    from ..core.config import get_settings
    from ..services import runtime_settings, tracker_files
    from ..services.tracker_import import parse_om_active_prs, summarise_active_prs

    s = get_settings()
    overrides = runtime_settings.read_overrides()
    status = tracker_files.tracker_status(
        overrides.get("TRACKERS_DIR") or s.TRACKERS_DIR,
        overrides.get("PR_REQUEST_DIR") or s.PR_REQUEST_DIR,
    )
    om_path = status.get("om_path")
    if not om_path:
        return {
            "ok": False,
            "error": "No O&M tracker found in the trackers folder.",
            "source": None,
            "summary": {},
            "items": [],
        }

    rows = parse_om_active_prs(om_path)
    summary = summarise_active_prs(rows)

    # Which of these PRs already exist in the register at all. Anything the
    # Planner has not picked up yet is tagged: assessment-stage requests
    # become "Upcoming EAR"; equipment work stays in its own branch.
    known = {
        pr for (pr,) in db.execute(select(Project.pr_number)).all()
    }
    equipment = {"EQUIPMENT_INSTALLATION", "EQUIPMENT_ASSESSMENT", "ICR"}
    items = []
    upcoming_ear = 0
    for r in rows:
        d = r.to_dict()
        d["in_planner"] = d["pr_key"] in known
        if d["category"] in equipment:
            d["tag"] = "Equipment installation"
        elif d["category"] == "ASEPC_PROPOSAL":
            d["tag"] = "Upcoming EAR"
            upcoming_ear += 1
        elif not d["in_planner"] and r.source_tab == "Active Project Assessment PRs":
            d["tag"] = "Upcoming EAR"
            upcoming_ear += 1
        elif d["in_planner"]:
            d["tag"] = "In Planner"
        else:
            d["tag"] = "New (not in Planner)"
        items.append(d)

    summary["upcoming_ear_count"] = upcoming_ear
    return {
        "ok": True,
        "source": status.get("om_latest"),
        "source_date": status.get("om_date"),
        "summary": summary,
        "items": items,
    }


#: Where the archived project folders live. Overridable at runtime; falls
#: back to the standard ENGINEERING_DATA layout.
def _archive_projects_root() -> Path | None:
    from ..core.config import get_settings
    from ..services import runtime_settings

    s = get_settings()
    overrides = runtime_settings.read_overrides()
    candidates = [
        overrides.get("ARCHIVE_PROJECTS_PATH"),
        r"E:\ENGINEERING_DATA\IHP_Projects",
        overrides.get("ARCHIVE_PATH"),
    ]
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if p.is_dir():
            return p
        if (p / "IHP_Projects").is_dir():
            return p / "IHP_Projects"
    return None


def _archive_index_file() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "archive_index.json"


@router.get("/archive/search")
def archive_search(
    q: str,
    limit: int = 8,
    _user: User = Depends(get_current_user),
):
    """Search the indexed project archive (similar work done before)."""
    from ..services import archive_index as ai_idx

    idx = ai_idx.load_index(_archive_index_file())
    hits = ai_idx.similar(idx, q, limit=limit)
    return {
        "q": q,
        "indexed": (idx or {}).get("count", 0),
        "built_at": (idx or {}).get("built_at"),
        "results": hits,
    }


@router.post("/archive/reindex")
def archive_reindex(
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Re-scan the project archive folder and rebuild the index."""
    from ..services import archive_index as ai_idx

    root = _archive_projects_root()
    if root is None:
        raise HTTPException(404, "Project archive folder not found on this machine.")
    summary = ai_idx.build_index(root, _archive_index_file())
    return summary


@router.post("/archive/ingest")
def archive_ingest_start(
    path: str | None = None,
    max_files: int = 5000,
    embed: bool = True,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Index documents into the AI corpus (background job).

    Defaults to the configured ARCHIVE_PATH; `path` overrides it for one run.
    Text from every supported document is chunked, embedded and stored, which
    is what makes "how did we do this before?" answerable with citations.
    """
    from ..core.config import get_settings
    from ..services import ai_ingest_jobs, runtime_settings

    overrides = runtime_settings.read_overrides()
    settings = get_settings()
    target = (
        path
        or overrides.get("ARCHIVE_PATH")
        or str(getattr(settings, "ARCHIVE_PATH", "") or "")
    )
    if not target:
        raise HTTPException(400, "No archive path configured (set ARCHIVE_PATH).")
    if not Path(target).is_dir():
        raise HTTPException(400, f"Archive path is not a directory on the server: {target}")
    return ai_ingest_jobs.start_archive_scan(
        target, admin.id, max_files=max_files, embed=embed
    )


@router.get("/archive/ingest/status")
def archive_ingest_status(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Progress of the background archive scan + current corpus size."""
    from ..ai import retrieval
    from ..services import ai_ingest_jobs, archive_ingest

    status = ai_ingest_jobs.read_status()
    return {
        "archive": status.get("archive"),
        "backfill": status.get("backfill"),
        "attachments": status.get("attachments"),
        "corpus": retrieval.stats(db),
        "last_scan": archive_ingest.archive_status().get("last_scan"),
    }


@router.post("/archive/embeddings/backfill")
def archive_embedding_backfill(
    limit: int = 5000,
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Embed corpus chunks that were ingested while the AI provider was offline."""
    from ..services import ai_ingest_jobs

    return ai_ingest_jobs.start_backfill(limit=limit)


@router.post("/archive/jobs/stop")
def archive_jobs_stop(
    kind: str = "backfill",
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Ask the archive scan or the embedding backfill to stop.

    Long jobs share the CPU with the chat model, and a slow chat answer is cut
    off by the ~100 s Cloudflare proxy limit, so being able to pause them (and
    resume later - both are resumable) matters operationally.
    """
    from ..services import ai_ingest_jobs

    if kind not in ("archive", "backfill", "attachments"):
        raise HTTPException(400, "kind must be 'archive', 'backfill' or 'attachments'")
    return ai_ingest_jobs.stop(kind)


@router.post("/attachments/reindex")
def attachments_reindex(
    project_id: int | None = None,
    limit: int = 5000,
    admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Index stored project attachments into the AI corpus (background job).

    The assistant answers from platform data only: the live database plus the
    documents teams upload to projects.
    """
    from ..services import ai_ingest_jobs

    return ai_ingest_jobs.start_attachment_index(admin.id, project_id, limit)


@router.get("/archive/status")
def archive_status(
    _user: User = Depends(get_current_user),
):
    """Index freshness + root resolution, for the dashboard badge."""
    from ..services import archive_index as ai_idx

    idx = ai_idx.load_index(_archive_index_file())
    return {
        "root": str(_archive_projects_root() or ""),
        "indexed": (idx or {}).get("count", 0),
        "built_at": (idx or {}).get("built_at"),
    }


@router.get("/{project_id}/summary")
def project_summary_data(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """The Project Summary as structured data, for the in-app web view."""
    from datetime import date as _date

    from ..core.config import get_settings
    from ..services.schedule import build_item as _sched_item
    from ..services.summary_docgen import _weeks_between, _trade_items, _match_trade, TRADE_ORDER

    project = get_project_or_404(db, project_id)
    d = _derive_tracker_fields(project)

    om_row = None
    s = get_settings()
    # location details merge (same logic as document-context)
    from ..services.tracker_files import latest_dated as _ld
    from ..services.tracker_import import parse_om as _pom
    p_om = _ld(s.TRACKERS_DIR, "O&M Project Progress Tracking")
    if p_om:
        try:
            for row in _pom(p_om):
                if row.pr_key == project.pr_number:
                    om_row = row
                    break
        except Exception:  # noqa: BLE001
            om_row = None

    by_trade = _trade_items(db, project.id)
    scope: list[dict] = []
    for label, _keys in TRADE_ORDER:
        lines = [ln for tr, ls in by_trade.items() if _match_trade(tr) == label for ln in ls]
        if lines:
            scope.append({"trade": label, "items": lines[:20]})
    for tr, ls in by_trade.items():
        if _match_trade(tr) is None:
            scope.append({"trade": tr, "items": ls[:20]})

    total_weeks = _weeks_between(d.get("start_date"), d.get("finish_date"))
    if total_weeks:
        design, delivery = max(total_weeks // 3, 1), max(total_weeks // 2, 1)
        works, hand = max(total_weeks // 4, 1), 1
        total = design + delivery + works + hand
    else:
        design, delivery, works, hand, total = 1, 8, 2, 1, 12

    return {
        "date": _date.today().strftime("%d %B %Y"),
        "to": project.pi_name or (om_row.requestor if om_row else None),
        "info": {
            "project_reference": f"{project.pr_number} {project.title}",
            "division": (om_row.division if om_row else None) or d.get("division") or "-",
            "customer": project.pi_name or "-",
            "contact": project.pi_email or "-",
            "location": (project.location or (om_row.location if om_row else "-"))
            + (f" - {om_row.location_details}" if om_row and om_row.location_details else ""),
        },
        "scope": scope,
        "schedule": {
            "Detailed Design": design,
            "Materials Order and Delivery": delivery,
            "Construction Works": works,
            "Handing over": hand,
            "Total": total,
        },
    }


@router.get("/{project_id}/generate/summary")
def download_project_summary(
    project_id: int,
    format: str = "docx",
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Download the Project Summary as Word or PDF (house format, with logo)."""
    return generate_project_summary(
        project_id=project_id, style="standard", db=db, user=_user, format=format,
    )


@router.post("/{project_id}/generate/summary")
def generate_project_summary(
    project_id: int,
    style: str = "standard",
    format: str = "docx",
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_SOW_MANAGE)),
):
    """Generate the Project Summary (Word) in the official IHP house format.

    Every field - project reference, division, proponent, contact, location
    (including the O&M Project Location Details) and the trade scope - is
    filled from the project context, so the document is project-specific.
    """
    from ..core.config import get_settings
    from ..services.summary_docgen import generate_project_summary_docx
    from ..services.archive_index import load_index, similar as archive_similar

    project = get_project_or_404(db, project_id)

    # Reuse the document-context assembler for PI / location / details.
    from ..services.tracker_files import latest_dated
    from ..services.tracker_import import parse_om

    s = get_settings()
    om_row = None
    om_path = latest_dated(s.TRACKERS_DIR, "O&M Project Progress Tracking")
    if om_path:
        try:
            for row in parse_om(om_path):
                if row.pr_key == project.pr_number:
                    om_row = row
                    break
        except Exception:  # noqa: BLE001
            om_row = None

    context = {
        "pi_name": project.pi_name or (om_row.requestor if om_row else None),
        "pi_email": project.pi_email,
        "location": project.location or (om_row.location if om_row else None),
        "location_details": om_row.location_details if om_row else None,
        "division": om_row.division if om_row else None,
    }
    if style == "premium":
        from ..services.summary_premium import generate_project_summary_premium

        idx = load_index(
            Path(__file__).resolve().parents[2] / "data" / "archive_index.json"
        )
        derived = _derive_tracker_fields(project)
        similar_hits = archive_similar(
            idx, project.title, trades=derived.get("trades"),
            division=derived.get("phase"), exclude_pr=project.pr_number, limit=5,
        )
        base_url = ""
        path = generate_project_summary_premium(
            project, context, db=db, similar=similar_hits,
            tracking_base_url=base_url,
        )
    else:
        path = generate_project_summary_docx(project, context, db=db)
    workflow.log_action(
        db, user, "docgen:summary", project, {"file": path.name, "format": format},
    )
    db.commit()

    if format == "pdf":
        from ..services.sow_boq_mto_docgen import _pdf_convert

        pdf = _pdf_convert(path, path.parent)
        if pdf is None:
            raise HTTPException(
                500,
                "PDF conversion needs LibreOffice (soffice) on the server; "
                "the Word file was generated instead.",
            )
        return FileResponse(pdf, filename=pdf.name, media_type="application/pdf")

    return FileResponse(
        path,
        filename=path.name,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
    )


@router.get("/{project_id}/document-context")
def document_context(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Everything the MOM / Project Summary / SOW / BOQ / MTO generators need.

    Merges three sources by PR number:
      * the register row  (name, PI, funding, stage, division),
      * the O&M register  (requestor email fallback + Project Location Details),
      * the PR request    (parsed PI name / email / location when present),
    and adds similar ARCHIVE projects so the drafts can lean on how the same
    kind of work was delivered before.
    """
    from datetime import date as _date

    from ..core.config import get_settings
    from ..services import archive_index as ai_idx
    from ..services import schedule as sched
    from ..services.tracker_files import latest_dated
    from ..services.tracker_import import parse_om

    project = get_project_or_404(db, project_id)
    d = _derive_tracker_fields(project)

    # ---- O&M register row: location details + requestor -------------------
    om_row = None
    s = get_settings()
    om_path = latest_dated(s.TRACKERS_DIR, "O&M Project Progress Tracking")
    if om_path:
        try:
            for row in parse_om(om_path):
                if row.pr_key == project.pr_number:
                    om_row = row
                    break
        except Exception:  # noqa: BLE001 - the register is best-effort context
            om_row = None

    location = project.location or (om_row.location if om_row else None)
    location_details = (om_row.location_details if om_row else None) or None

    # ---- similar archived projects ----------------------------------------
    idx = ai_idx.load_index(_archive_index_file())
    similar_hits = ai_idx.similar(
        idx, project.title, trades=d.get("trades"), division=d.get("phase"),
        exclude_pr=project.pr_number, limit=5,
    )

    item = sched.build_item(project, d, today=_date.today())
    return {
        "project": {
            "id": project.id,
            "pr_number": project.pr_number,
            "ear_number": project.ear_number,
            "project_name": project.title,
            "pi_name": project.pi_name or (om_row.requestor if om_row else None),
            "pi_email": project.pi_email,
            "location": location,
            "location_details": location_details,
            "division": om_row.division if om_row else None,
            "funding_source": project.funding_source,
            "stage": project.stage,
            "phase": d.get("phase"),
            "planner_bucket": project.planner_bucket,
            "trades": d.get("trades"),
            "project_type": d.get("project_type"),
            "priority": d.get("priority"),
            "completion_pct": d.get("completion_pct"),
            "latest_status": d.get("latest_status"),
            "status_timeline": d.get("status_timeline"),
            "finish_date": d.get("finish_date"),
            "effort": d.get("effort"),
            "required_hours_per_day": item.required_hours_per_day,
        },
        "om_register": {
            "status": om_row.status if om_row else None,
            "manager": om_row.manager if om_row else None,
            "execution_lead": om_row.execution_lead if om_row else None,
            "cost_estimate_usd": om_row.cost_estimate_usd if om_row else None,
            "remarks": om_row.remarks if om_row else None,
        } if om_row else None,
        "similar_archive_projects": similar_hits,
        "sources": {
            "om_file": om_path.name if om_path else None,
            "archive_indexed": (idx or {}).get("count", 0),
        },
    }


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """Return metrics for the PowerBI-style dashboard."""
    # 1. Base counts
    total_projects = db.scalar(select(func.count(Project.id))) or 0
    total_ear = db.scalar(select(func.count(Project.id)).where(Project.ear_number.is_not(None))) or 0
    
    # 2. Stage Breakdown
    stage_counts = {}
    for stage, count in db.execute(select(Project.stage, func.count(Project.id)).group_by(Project.stage)).all():
        stage_counts[stage or "unknown"] = count
        
    # 3. Disposition Breakdown (e.g. Under Progress, Required Site Visit, Waiting for ASEPC, etc)
    disposition_counts = {}
    for disp, count in db.execute(select(Project.disposition, func.count(Project.id)).group_by(Project.disposition)).all():
        if disp:
            disposition_counts[disp] = count

    # 4. Construction vs Design Breakdown
    # Construction phase = projects that have reached the field-execution stages.
    construction_stages = ["PROCUREMENT", "WORK_PERMIT", "CONSTRUCTION", "CLOSEOUT"]
    procore_count = db.scalar(
        select(func.count(Project.id)).where(Project.stage.in_(construction_stages))
    ) or 0
    design_count = total_projects - procore_count
            
    return {
        "totals": {
            "projects": total_projects,
            "ear": total_ear,
            "design": design_count,
            "procore": procore_count
        },
        "by_stage": stage_counts,
        "by_disposition": disposition_counts,
    }


@router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_CREATE)),
):
    existing = db.scalar(select(Project).where(Project.pr_number == payload.pr_number))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project with pr_number '{payload.pr_number}' already exists",
        )
    project = Project(
        pr_number=payload.pr_number,
        ear_number=payload.ear_number,
        tracking_token=uuid.uuid4().hex,
        title=payload.title,
        description=payload.description or "",
        location=payload.location,
        pi_name=payload.pi_name,
        pi_email=payload.pi_email,
        funding_source=payload.funding_source,
        stage=workflow.INTAKE,
        created_by_id=user.id,
    )
    db.add(project)
    db.flush()
    workflow.log_action(
        db,
        user,
        "project:create",
        project,
        {"pr_number": project.pr_number, "title": project.title},
    )
    db.commit()
    db.refresh(project)
    return project


@router.put("/{project_id}", response_model=ProjectDetail)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    project = get_project_or_404(db, project_id)
    data = payload.model_dump(exclude_unset=True)
    changed = [
        field for field, value in data.items() if getattr(project, field) != value
    ]
    for field, value in data.items():
        setattr(project, field, value)
    if changed:
        workflow.log_action(db, user, "project:edit", project, {"fields": changed})
    db.commit()
    db.refresh(project)
    return project

from pydantic import BaseModel

class PromoteToEarInput(BaseModel):
    new_pr_number: str


class StageUpdateInput(BaseModel):
    """Set a project's workflow stage from the dashboard."""

    stage: str
    note: str | None = None


def _transition_path(from_stage: str, to_stage: str) -> list[str] | None:
    """Shortest legal path through the state machine, or None if unreachable.

    Lets the dashboard set a status like CONSTRUCTION on a project sitting at
    EAR_REVIEW by walking the intermediate stages (each hop is audited), while
    still refusing genuinely illegal jumps (e.g. into an ICR-only stage).
    """
    if from_stage == to_stage:
        return []
    from collections import deque

    queue: deque[tuple[str, list[str]]] = deque([(from_stage, [])])
    seen = {from_stage}
    while queue:
        current, path = queue.popleft()
        for nxt in sorted(workflow.ALLOWED_TRANSITIONS.get(current, set())):
            if nxt in seen:
                continue
            new_path = path + [nxt]
            if nxt == to_stage:
                return new_path
            seen.add(nxt)
            queue.append((nxt, new_path))
    return None


@router.post("/{project_id}/stage", response_model=ProjectDetail)
def set_project_stage(
    project_id: int,
    payload: StageUpdateInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    """Set the workflow stage/status of a project (audited, guard-checked)."""
    project = get_project_or_404(db, project_id)
    target = (payload.stage or "").strip().upper()
    if target not in workflow.STAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown stage {payload.stage!r}. "
                   f"Valid stages: {sorted(workflow.STAGES)}",
        )
    if project.stage == target:
        return project
    path = _transition_path(project.stage, target)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No legal workflow path from {project.stage} to {target}.",
        )
    detail = {"note": payload.note} if payload.note else None
    for step in path:
        workflow.transition(project, step, user, db, detail=detail)
    db.commit()
    db.refresh(project)
    return project

@router.post("/{project_id}/promote-to-ear", response_model=ProjectDetail)
def promote_to_ear(
    project_id: int,
    payload: PromoteToEarInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_PROJECTS_EDIT)),
):
    project = get_project_or_404(db, project_id)
    
    # Check if the new PR number is already taken
    existing = db.scalar(select(Project).where(Project.pr_number == payload.new_pr_number))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project with pr_number '{payload.new_pr_number}' already exists",
        )
    
    # Shift old PR to EAR, set new PR
    old_pr = project.pr_number
    project.ear_number = old_pr
    project.pr_number = payload.new_pr_number
    
    workflow.log_action(db, user, "project:promote_to_ear", project, {"old_pr": old_pr, "new_pr": payload.new_pr_number})
    db.commit()
    db.refresh(project)
    return project

@router.get("/track/{token}", response_model=ProjectListItem)
def get_public_tracker(token: str, db: Session = Depends(get_db)):
    project = db.scalar(select(Project).where(Project.tracking_token == token))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or invalid token")
    
    derived = _derive_tracker_fields(project)
    return ProjectListItem(
        id=project.id, pr_number=project.pr_number, ear_number=project.ear_number,
        tracking_token=project.tracking_token, title=project.title,
        pi_name=project.pi_name, location=project.location,
        funding_source=project.funding_source, stage=project.stage,
        disposition=project.disposition, created_at=project.created_at,
        **derived,
    )



@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_capability(CAP_PROJECTS_DELETE)),
):
    """Hard-delete a project and everything tied to it (audit rows included —
    auditing the deletion itself is pointless once the trail is gone)."""
    project = get_project_or_404(db, project_id)
    for log in db.scalars(
        select(AuditLog).where(AuditLog.project_id == project.id)
    ).all():
        db.delete(log)
    if project.mom is not None:
        db.delete(project.mom)
    for attachment in project.attachments:
        _remove_file_best_effort(attachment.stored_path)
        db.delete(attachment)
    db.delete(project)
    db.commit()


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return get_project_or_404(db, project_id)


@router.post("/{project_id}/attachments", response_model=list[AttachmentOut])
async def upload_attachments(
    project_id: int,
    files: list[UploadFile] = File(...),
    stage: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_ATTACHMENTS_UPLOAD)),
):
    project = get_project_or_404(db, project_id)
    target_stage = stage or project.stage
    created: list[Attachment] = []
    for upload in files:
        filename = upload.filename or "file"
        data = await upload.read()
        stored_path, version = storage.store_upload(
            project.pr_number, target_stage, filename, data
        )
        attachment = Attachment(
            project_id=project.id,
            stage=target_stage,
            filename=filename,
            stored_path=str(stored_path),
            content_type=upload.content_type,
            size_bytes=len(data),
            version=version,
            uploaded_by_id=user.id,
        )
        db.add(attachment)
        db.flush()
        workflow.log_action(
            db,
            user,
            "attachment:upload",
            project,
            {"filename": filename, "version": version, "stage": target_stage},
        )
        created.append(attachment)
    db.commit()
    for attachment in created:
        db.refresh(attachment)

    # Index the uploaded documents into the AI corpus (text only: uploads stay
    # fast, and the embedding backfill job adds vectors later).
    from ..services import app_documents

    for attachment in created:
        try:
            app_documents.index_attachment(db, attachment, user.id, embed=False)
        except Exception:  # noqa: BLE001 — indexing must never fail an upload
            db.rollback()
    return created


@router.delete(
    "/{project_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_attachment(
    project_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAP_ATTACHMENTS_DELETE)),
):
    project = get_project_or_404(db, project_id)
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        )
    workflow.log_action(
        db, user, "attachment:delete", project, {"filename": attachment.filename}
    )
    # The AI corpus keeps a text copy of the file; drop it with the file.
    from ..services import app_documents

    try:
        app_documents.remove_attachment_index(db, attachment)
    except Exception:  # noqa: BLE001 — never block a delete on corpus upkeep
        db.rollback()
    _remove_file_best_effort(attachment.stored_path)
    db.delete(attachment)
    db.commit()


@router.get("/{project_id}/attachments/{attachment_id}/download")
def download_attachment(
    project_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        )
    path = Path(attachment.stored_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment file missing on disk",
        )
    return FileResponse(
        path,
        filename=attachment.filename,
        media_type=attachment.content_type or "application/octet-stream",
    )


@router.get("/{project_id}/audit", response_model=list[AuditOut])
def get_audit_trail(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    get_project_or_404(db, project_id)
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.project_id == project_id)
        .order_by(AuditLog.id)
    ).all()
    usernames = {
        user.id: user.username
        for user in db.scalars(
            select(User).where(User.id.in_({log.user_id for log in logs}))
        ).all()
    } if logs else {}
    return [
        AuditOut(
            id=log.id,
            user=usernames.get(log.user_id, str(log.user_id)),
            action=log.action,
            detail=log.detail,
            created_at=log.created_at,
        )
        for log in logs
    ]
