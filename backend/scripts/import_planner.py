"""Import a Microsoft Project tracker export into the IHP dev database.

The live source of truth for project status is a Microsoft Project export
saved as xlsx in `E:\\ENGINEERING_DATA\\trackers\\`. This script reads the
"Project tasks" sheet, parses each row as a project, and writes the result
to `dev.db` via the same SQLAlchemy models the API uses.

Idempotent / re-runnable
------------------------
Keyed on `Project.pr_number`. Re-running on a newer snapshot:
  * New rows  -> create + walk forward to the tracker stage
  * Same data -> log `import:planner_no_change`, no DB write
  * Stage moved forward in tracker -> workflow.transition() (writes audit)
  * Stage moved backward in tracker -> leave IHP stage alone (don't
    downgrade) but log it. The IHP is the system of record for "what
    stage is this project at", the tracker is the schedule snapshot.

Usage
-----
    cd backend
    .venv\\Scripts\\python.exe -m scripts.import_planner \\
        "E:/ENGINEERING_DATA/trackers/IHP- Construction Projects_07092026.xlsx" \\
        [--dry-run] [--from-row N] [--only-bucket WCH] [--limit N]

Run with --dry-run first to see the parsed table before committing.
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Make `app.*` importable when running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.models import Project, User  # noqa: E402
from app.services import workflow  # noqa: E402


# ---------------------------------------------------------------------------
# Stage mapping (tracker Bucket -> IHP stage + disposition)
# ---------------------------------------------------------------------------

#: Allowed Bucket values from the tracker, after .strip().upper()
BUCKET_TO_STAGE: dict[str, tuple[str, str | None]] = {
    # bucket      ->  (IHP stage,         disposition)
    "WCH":                ("CLOSEOUT",      "PROJECT"),
    "WCC":                ("CLOSEOUT",      "PROJECT"),
    "CONSTRUCTION":       ("CONSTRUCTION",  "PROJECT"),
    "PTW/WICF":           ("WORK_PERMIT",   "PROJECT"),
    "PTW":                ("WORK_PERMIT",   "PROJECT"),
    "WICF":               ("WORK_PERMIT",   "PROJECT"),
    "QUALITY INSPECTION": ("CONSTRUCTION",  "PROJECT"),
    "DESIGN":             ("SOW_APPROVED",  "PROJECT"),
    # Procore = SOW/BOQ approved and the quotation/PO being processed.
    "PROCORE":            ("PROCUREMENT",   "PROJECT"),
    # Shutdown = physical work during an outage window.
    "SHUTDOWN":           ("CONSTRUCTION",  "PROJECT"),
    "EAR":                ("EAR_REVIEW",    "PROJECT"),
    "MOM":                ("MOM_CONFIRMED", "PROJECT"),
    "INTAKE":             ("INTAKE",        None),
}

#: Forward-only stage chain used when a project is first created. We
#: walk from INTAKE to the target stage so the audit log shows the
#: realistic transition history.
STAGE_CHAIN: list[str] = [
    workflow.INTAKE,
    workflow.MOM_SENT,
    workflow.MOM_CONFIRMED,
    workflow.DISPOSITION,
    workflow.EAR_DRAFT,
    workflow.EAR_REVIEW,
    workflow.EAR_APPROVED,
    workflow.SOW_DRAFT,
    workflow.SOW_REVIEW,
    workflow.SOW_APPROVED,
    workflow.MTO_DRAFT,
    workflow.MTO_APPROVED,
    workflow.PROCUREMENT,
    workflow.WORK_PERMIT,
    workflow.CONSTRUCTION,
    workflow.CLOSEOUT,
]


def _stage_index(stage: str) -> int:
    """Index of `stage` in STAGE_CHAIN; -1 if not present."""
    try:
        return STAGE_CHAIN.index(stage)
    except ValueError:
        return -1


# ---------------------------------------------------------------------------
# Row parsing
# ---------------------------------------------------------------------------

#: Matches both "PR 9160 ..." and "19152 ..." (bare 5-digit) PR numbers
#: at the start of a Name. Captures the digits only.
_PR_HEAD = re.compile(r"^(?:PR[\s\-]*)?(\d{4,6})\b", re.IGNORECASE)

#: Recognised trade tokens in the Labels column. Order is the priority
#: when joining them into a description note.
_TRADE_TOKENS: tuple[str, ...] = (
    "CIVIL", "MECH", "ELEC", "PLUMB", "HVAC", "LC", "FIRE", "ARCH",
)

#: Project type tokens in the Labels column.
_TYPE_TOKENS: tuple[str, ...] = ("BASELINE", "ASEPC")


def _clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _percent(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date(v):
    """Parse a date cell from either an .xlsx (datetime) or .md (string)."""
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and len(v) >= 10:
        try:
            return datetime.fromisoformat(v[:19])
        except ValueError:
            return None
    return None


def _labels_to_tokens(label_str: str) -> tuple[list[str], list[str]]:
    """Split a Labels cell like 'BASELINE;ELEC;Walkthrough Completed '
    into (trades, types) by scanning for known tokens.
    """
    if not label_str:
        return [], []
    parts = [p.strip().upper() for p in label_str.split(";") if p.strip()]
    trades = [t for t in parts if t in _TRADE_TOKENS]
    types_ = [t for t in parts if t in _TYPE_TOKENS]
    return trades, types_


def parse_row(row: tuple) -> dict:
    """Map a single MS Project row (tuple of 28 cells) to a normalized dict.

    Keys: pr_number, title, pi_name, location, building, division,
    bucket, percent, start, finish, milestone, checklist, labels,
    priority, sprint, effort, duration, design_etc, execution_lead,
    requestor, type, trades.
    """
    # Index by 0-based position to mirror the column headers we verified
    # (Task number=1, Name=3, Assigned to=4, Bucket=5, Design ETC=6,
    #  Division=7, Finish=8, Planned Finish=9, Start=10, Depends on=11,
    #  % complete=12, ..., Milestone=18, Notes=19, Completed=20,
    #  Checklist Items=21, Labels=22, Priority=23, Sprint=24, Goal=25,
    #  Building=26, Execution Lead=27, Requestor/PI=28)
    name = _clean(row[2])
    m = _PR_HEAD.match(name)
    if not m:
        return {"pr_number": None, "_skip": True, "name": name}
    pr_number = f"PR-{m.group(1)}"
    # Title = the rest of the Name after the PR token
    title = name[m.end():].strip(" -–—:") or name
    if len(title) > 295:
        title = title[:292] + "..."

    bucket_raw = _clean(row[4]).upper()
    bucket = bucket_raw  # already uppercased, .strip()'d
    labels = _clean(row[21])
    trades, types_ = _labels_to_tokens(labels)

    # Prefer Requestor/PI for the PI name; fall back to Assigned to
    pi = _clean(row[27]) or _clean(row[3])
    return {
        "pr_number": pr_number,
        "title": title,
        "name": name,
        "pi_name": pi or None,
        "building": _clean(row[25]) or None,
        "division": _clean(row[6]) or None,
        "bucket_raw": bucket_raw,
        "bucket": bucket,
        "percent": _percent(row[11]),
        "start": _date(row[9]),
        "finish": _date(row[7]),
        "milestone": _clean(row[17]),
        # Notes = the chronological progress log; "Completed" holds the
        # "3/6" checklist ratio; Checklist Items holds the item names.
        "notes": _clean(row[18]),
        "completed": _clean(row[19]),
        "checklist": _clean(row[20]),
        "labels": labels,
        "priority": _clean(row[22]) or None,
        "sprint": _clean(row[23]) or None,
        "effort": _clean(row[13]) or None,
        "duration": _clean(row[16]) or None,
        "design_etc": _date(row[5]),
        # Header row 9: ... | Assigned to | ... | Execution Lead | Requestor/PI
        # "Assigned to" is the IHP engineer the task is assigned to (e.g. the
        # EAR owner). It used to be dropped entirely, so the assistant could
        # not answer "who is the EAR assigned to?".
        "assigned_to": _clean(row[3]) or None,
        "execution_lead": _clean(row[26]) or None,
        "requestor": _clean(row[27]) or None,
        "type": types_[0] if types_ else None,
        "trades": trades,
        "_skip": False,
    }


def build_description(r: dict, sync_date: str | None = None) -> str:
    """Compose a structured Project.description from the parsed row.

    Order is fixed so re-runs produce the same string (idempotency).
    Free-text fields are truncated to keep the column under TEXT limits.
    """
    parts: list[str] = []
    if r.get("type"):
        parts.append(f"Type: {r['type']}")
    if r.get("trades"):
        parts.append(f"Trades: {', '.join(r['trades'])}")
    if r.get("division"):
        parts.append(f"Division: {r['division']}")
    if r.get("priority"):
        parts.append(f"Priority: {r['priority']}")
    if r.get("sprint"):
        parts.append(f"Sprint: {r['sprint']}")
    if r.get("percent") is not None:
        parts.append(f"Completion: {int(r['percent'] * 100)}%")
    if r.get("effort"):
        parts.append(f"Effort: {r['effort']}")
    if r.get("duration"):
        parts.append(f"Duration: {r['duration']}")
    if r.get("assigned_to"):
        parts.append(f"Assigned To: {r['assigned_to']}")
    if r.get("execution_lead"):
        parts.append(f"Execution Lead: {r['execution_lead']}")
    if r.get("requestor"):
        parts.append(f"Requestor: {r['requestor']}")
    if r.get("start"):
        parts.append(f"Start: {r['start'].strftime('%Y-%m-%d')}")
    if r.get("finish"):
        parts.append(f"Finish: {r['finish'].strftime('%Y-%m-%d')}")
    if r.get("labels"):
        parts.append(f"Labels: {r['labels']}")
    # Which Planner snapshot this row came from. Rows absent from the newest
    # snapshot keep their older date, so the dashboards can tell current
    # Planner data apart from stale/removed PRs (and count only the former).
    if sync_date:
        parts.append(f"Planner Sync: {sync_date}")

    # ---- Notes/Labels analysis: the CURRENT status of the project ----
    # The Planner writes the progress log chronologically, so the last
    # milestone in the Notes is the live status. Stored as structured lines
    # so the API and dashboards can read it back without re-parsing.
    from app.services.planner_status import analyze as _analyze
    a = _analyze(notes=r.get("notes"), labels=r.get("labels"),
                 checklist=r.get("completed"), bucket=r.get("bucket"),
                 priority=r.get("priority"))
    if a.latest_status:
        parts.append(f"Latest Status: {a.latest_status}")
    if a.latest_status_date:
        parts.append(f"Status Date: {a.latest_status_date}")
    if a.timeline:
        parts.append("Status Timeline: " + " -> ".join(a.timeline[-6:]))
    if a.flags:
        parts.append("Flags: " + ", ".join(a.flags))
    if a.checklist_done is not None and a.checklist_total:
        parts.append(f"Checklist: {a.checklist_done}/{a.checklist_total}")
    if a.phase:
        parts.append(f"Phase: {a.phase}")
    if a.ear_substatus:
        parts.append(f"EAR Status: {a.ear_substatus}")
    if a.ear_approved_date:
        parts.append(f"EAR Approved Date: {a.ear_approved_date}")

    body = "\n".join(parts)
    extras: list[str] = []
    if r.get("milestone"):
        ms = r["milestone"]
        extras.append(f"Milestone history:\n{ms[:500]}")
    if r.get("checklist"):
        ck = r["checklist"]
        extras.append(f"Checklist:\n{ck[:500]}")
    if extras:
        body = body + "\n\n" + "\n\n".join(extras)
    return body.strip()


def map_stage(bucket: str) -> tuple[str, str | None]:
    """Return (stage, disposition) for a normalized bucket value."""
    if not bucket:
        return workflow.INTAKE, None
    return BUCKET_TO_STAGE.get(bucket, (workflow.INTAKE, None))


# ---------------------------------------------------------------------------
# DB import
# ---------------------------------------------------------------------------

def _walk_to_stage(p: Project, target_stage: str, db, admin: User) -> None:
    """Walk `p` forward through the stage chain until it reaches
    `target_stage`. Idempotent: a no-op if already there.
    """
    target_idx = _stage_index(target_stage)
    if target_idx < 0:
        # target is not a chain stage (e.g. CLOSEOUT is the last one,
        # which IS in the chain, but be defensive)
        return
    current_idx = _stage_index(p.stage)
    if current_idx < 0:
        # Project was created with a non-chain stage (e.g. legacy).
        # Snap to the chain by calling transition() from current.
        # If the current->target transition is not allowed, this raises
        # WorkflowError and the caller decides what to do.
        try:
            workflow.transition(p, target_stage, admin, db,
                                action="import:planner_sync",
                                detail={"source_bucket": "(unknown)"})
            db.commit()
        except workflow.WorkflowError:
            db.rollback()
        return
    if current_idx >= target_idx:
        return
    for idx in range(current_idx + 1, target_idx + 1):
        next_stage = STAGE_CHAIN[idx]
        try:
            workflow.transition(p, next_stage, admin, db,
                                action="import:planner_sync",
                                detail={"source_bucket": "(initial walk)"})
            db.commit()
        except workflow.WorkflowError as e:
            # Allowed-transitions graph is the source of truth; if a hop
            # is blocked (e.g. EAR_DRAFT -> EAR_REVIEW requires a hop
            # through nothing, which is fine; but some hops are gated),
            # log and stop walking.
            print(f"  ! {p.pr_number}: stopped at {p.stage}, "
                  f"cannot reach {next_stage}: {e}")
            db.rollback()
            return


def _advance_to_stage(p: Project, target_stage: str, db, admin: User,
                      source_bucket: str) -> bool:
    """Advance an existing project from its current stage to `target_stage`
    if the new stage is *forward* in the chain. Returns True iff a
    transition was actually applied.
    """
    if p.stage == target_stage:
        return False
    current_idx = _stage_index(p.stage)
    target_idx = _stage_index(target_stage)
    if target_idx < 0:
        return False
    if current_idx >= 0 and target_idx <= current_idx:
        # Don't downgrade. Log the discrepancy in the audit trail.
        from app.models import AuditLog
        db.add(AuditLog(
            project_id=p.id, user_id=admin.id,
            action="import:planner_no_downgrade",
            detail={"ihp_stage": p.stage, "tracker_stage": target_stage,
                    "source_bucket": source_bucket},
        ))
        db.commit()
        return False
    # Target is forward; hop there directly via the workflow
    try:
        workflow.transition(p, target_stage, admin, db,
                            action="import:planner_sync",
                            detail={"source_bucket": source_bucket})
        db.commit()
        return True
    except workflow.WorkflowError as e:
        # If the direct hop is not allowed (e.g. EAR_REVIEW -> CLOSEOUT
        # is not a direct transition), walk one step at a time.
        print(f"  ! {p.pr_number}: direct hop {p.stage} -> {target_stage} "
              f"blocked ({e}); walking chain")
        db.rollback()
        _walk_to_stage(p, target_stage, db, admin)
        return p.stage != target_stage


def import_xlsx(path: Path, dry_run: bool = False,
                from_row: int = 10, only_bucket: str | None = None,
                limit: int | None = None) -> int:
    """Import `path` and return the number of rows processed."""
    print(f"Reading {path} ...")
    # `sheet_rows` reads the .xlsx export (data from `from_row`) AND the
    # markdown dump of the same sheet, so the newest dated tracker works
    # whichever format the Planner exported it in.
    from app.services.tracker_import import sheet_rows
    cell_rows = sheet_rows(Path(path), "Project tasks", start_row=from_row,
                           min_cols=28)
    print(f"Sheet: 'Project tasks' via {Path(path).suffix or '?'} "
          f"({len(cell_rows)} rows)")

    # Snapshot date = the _DDMMYYYY suffix of the source file (fallback: today).
    from app.services.tracker_files import _suffix_date as _file_date
    _d = _file_date(Path(path).stem)
    snapshot_date = (_d or datetime.now()).strftime("%Y-%m-%d")

    bucket_filter = only_bucket.strip().upper() if only_bucket else None
    parsed: list[dict] = []
    skipped = 0
    for row in cell_rows:
        if not any(c is not None for c in row):
            continue
        rec = parse_row(row)
        if rec.get("_skip") or not rec.get("pr_number"):
            skipped += 1
            continue
        if bucket_filter and rec["bucket"] != bucket_filter:
            continue
        parsed.append(rec)
    if limit is not None:
        parsed = parsed[:limit]
    print(f"Parsed {len(parsed)} project rows (skipped {skipped} non-project rows)")
    if not parsed:
        return 0

    # Distribution summary
    bcount = Counter(r["bucket"] for r in parsed)
    print("\nBucket distribution in this import:")
    for b, c in bcount.most_common():
        stage, disp = map_stage(b)
        print(f"  {b!r:>22}: {c:>3}  -> stage={stage:<14} disp={disp}")

    if dry_run:
        print(f"\n[DRY-RUN] First 10 rows:")
        for r in parsed[:10]:
            stage, _ = map_stage(r["bucket"])
            print(f"  {r['pr_number']:<10}  {stage:<14}  "
                  f"pi={r.get('pi_name') or '-':<25}  bldg={r.get('building') or '-'}")
        return len(parsed)

    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.username == "admin"))
        if admin is None:
            print("ERROR: admin user not found. Run scripts.seed_demo first "
                  "to create the standard users.")
            return 0

        created = updated = no_change = 0
        for rec in parsed:
            stage, disposition = map_stage(rec["bucket"])
            description = build_description(rec, sync_date=snapshot_date)
            location = rec.get("building") or rec.get("division")

            existing = db.scalar(
                select(Project).where(Project.pr_number == rec["pr_number"])
            )
            if existing is None:
                p = Project(
                    pr_number=rec["pr_number"],
                    tracking_token=uuid.uuid4().hex,
                    title=rec["title"],
                    description=description,
                    location=location,
                    pi_name=rec.get("pi_name"),
                    funding_source=None,
                    stage=workflow.INTAKE,
                    disposition=disposition,
                    planner_bucket=rec["bucket"] or None,
                    created_by_id=admin.id,
                )
                db.add(p)
                db.flush()  # need p.id
                _walk_to_stage(p, stage, db, admin)
                db.add(_audit(admin, "import:planner_create", p, {
                    "source_bucket": rec["bucket"],
                    "percent": rec.get("percent"),
                    "tracker_name": rec.get("name"),
                }))
                created += 1
            else:
                changed = False
                if existing.title != rec["title"] and rec["title"]:
                    existing.title = rec["title"]; changed = True
                if existing.description != description and description:
                    existing.description = description; changed = True
                if existing.location != location and location:
                    existing.location = location; changed = True
                if existing.pi_name != rec.get("pi_name") and rec.get("pi_name"):
                    existing.pi_name = rec["pi_name"]; changed = True
                if (disposition is not None
                        and existing.disposition != disposition):
                    existing.disposition = disposition; changed = True
                if rec.get("bucket") and existing.planner_bucket != rec["bucket"]:
                    existing.planner_bucket = rec["bucket"]; changed = True
                advanced = False
                if existing.stage != stage:
                    advanced = _advance_to_stage(
                        existing, stage, db, admin, rec["bucket"])
                    if advanced:
                        changed = True
                if changed:
                    db.add(_audit(admin, "import:planner_update", existing, {
                        "source_bucket": rec["bucket"],
                        "percent": rec.get("percent"),
                    }))
                    updated += 1
                else:
                    no_change += 1
            db.commit()

        print(f"\nDone. created={created} updated={updated} no_change={no_change}")
        # Final stage distribution
        all_p = db.scalars(select(Project)).all()
        sc = Counter(p.stage for p in all_p)
        print(f"\nTotal projects in DB: {len(all_p)}")
        print("Stage distribution:")
        for s, c in sc.most_common():
            print(f"  {s:<16}: {c}")
        return len(parsed)
    finally:
        db.close()


def _audit(user: User, action: str, project: Project, detail: dict | None = None):
    from app.models import AuditLog
    return AuditLog(
        project_id=project.id, user_id=user.id,
        action=action, detail=detail or {},
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xlsx", type=Path, help="Path to the tracker xlsx")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse and print the table without touching the DB")
    p.add_argument("--from-row", type=int, default=10,
                   help="First row to read (default: 10, after the header block)")
    p.add_argument("--only-bucket", type=str, default=None,
                   help="Restrict to a single bucket value (e.g. WCH)")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap the number of rows imported")
    args = p.parse_args()
    if not args.xlsx.exists():
        print(f"ERROR: {args.xlsx} does not exist")
        return 1
    n = import_xlsx(
        args.xlsx,
        dry_run=args.dry_run,
        from_row=args.from_row,
        only_bucket=args.only_bucket,
        limit=args.limit,
    )
    return 0 if n >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
