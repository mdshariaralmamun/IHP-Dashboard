"""Seed the local dev database with a small, representative portfolio.

Why this exists
---------------
The dashboard and project pages look empty with no data. This script inserts
four projects at four different points in the lifecycle so every panel on
the project detail page has something realistic to show:

  * PR-12623 (T1 thermal evaporator)         INTAKE          stage 1
  * PR-12643 (Chilled water connection)      MOM_CONFIRMED   stage 2
  * PR-20001 (Lab gas manifold rebuild)      SOW_APPROVED    stage 4-5
  * PR-20002 (BSL-3 air handler retrofit)    CLOSEOUT        stage 7
  * PR-20003 (Cryo transfer line)            ICR (MTO_APPROVED) — ICR branch

The seed is idempotent: re-running it wipes the demo rows and re-inserts
them. Real (non-demo) rows are left alone. Run with:

    cd backend
    .venv/Scripts/python.exe -m scripts.seed_demo

It uses the same SQLAlchemy SessionLocal the app uses, so it stays in sync
with the live dev.db without needing alembic.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

# Make `app.*` importable when running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Attachment,
    AuditLog,
    BoqMtoItem,
    CloseoutRecord,
    ConstructionRecord,
    EarRecord,
    IcrHandoff,
    MomRecord,
    Project,
    PunchListItem,
    SowRecord,
    User,
)
from app.services import workflow  # noqa: E402


DEMO_PR_NUMBERS = {"PR-12623", "PR-12643", "PR-20001", "PR-20002", "PR-20003"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_users(db) -> dict[str, User]:
    """Create the standard IHP team if missing. Returns username -> User."""
    team = [
        ("admin", "Platform Administrator", "admin", "admin123"),
        ("chris.asis", "Chris Asis", "trade", "demo-pass-1"),
        ("abdulkader.rokaya", "Abdulkader Rokaya", "project_supervisor", "demo-pass-1"),
        ("nadia.haddad", "Nadia Haddad", "engineering", "demo-pass-1"),
        ("ahmed.alam", "Ahmed Alam", "procurement", "demo-pass-1"),
    ]
    out: dict[str, User] = {}
    for username, full_name, role, pw in team:
        u = db.scalar(select(User).where(User.username == username))
        if u is None:
            u = User(
                username=username,
                full_name=full_name,
                email=f"{username}@kaust.edu.sa",
                hashed_password=hash_password(pw),
                role=role,
                is_active=True,
            )
            db.add(u)
            db.flush()
            print(f"  + user {username} ({role})")
        out[username] = u
    db.flush()
    return out


def _wipe_demo(db) -> None:
    """Remove anything attached to the demo PR numbers. Real rows untouched."""
    demo_projects = db.scalars(
        select(Project).where(Project.pr_number.in_(DEMO_PR_NUMBERS))
    ).all()
    if not demo_projects:
        return
    pids = [p.id for p in demo_projects]
    for model in (
        AuditLog, IcrHandoff, PunchListItem, CloseoutRecord, ConstructionRecord,
        BoqMtoItem, SowRecord, EarRecord, MomRecord, Attachment,
    ):
        if hasattr(model, "project_id"):
            db.execute(delete(model).where(model.project_id.in_(pids)))
    db.execute(delete(Project).where(Project.id.in_(pids)))
    db.flush()
    print(f"  wiped {len(pids)} demo projects + their child rows")


def _new_project(db, users, pr_number, title, location, pi, funding, stage, disposition=None) -> Project:
    p = Project(
        pr_number=pr_number,
        tracking_token=uuid.uuid4().hex,
        title=title,
        description=f"Auto-seeded demo project: {title}",
        location=location,
        pi_name=pi,
        pi_email=f"{pi.split()[0].lower()}@kaust.edu.sa",
        funding_source=funding,
        stage=stage,
        disposition=disposition,
        created_by_id=users["admin"].id,
    )
    db.add(p)
    db.flush()
    return p


def _audit(db, user, action, project, detail=None):
    db.add(AuditLog(
        project_id=project.id if project else None,
        user_id=user.id,
        action=action,
        detail=detail or {},
    ))


# ---------------------------------------------------------------------------
# Per-project seeders
# ---------------------------------------------------------------------------

def seed_intake(db, users):
    """PR-12623: brand new PR, still in INTAKE — only the metadata card and audit trail are populated."""
    p = _new_project(db, users, "PR-12623",
        "T1 thermal evaporator replacement",
        location="Bldg 9 / Cleanroom",
        pi="Abdulrahman El Labban",
        funding="Capital - Equipment Replacement",
        stage=workflow.INTAKE)
    _audit(db, users["admin"], "project:create", p, {
        "pr_number": p.pr_number, "title": p.title})
    _audit(db, users["nadia.haddad"], "intake:pr_received", p, {
        "received_at": _utcnow().isoformat(),
        "channel": "email"})
    return p


def seed_mom_confirmed(db, users):
    """PR-12643: through stage 1 (MOM confirmed), waiting on disposition."""
    p = _new_project(db, users, "PR-12643",
        "Chilled water connection for new chiller",
        location="Bldg 5 / Mechanical Room",
        pi="Sara Al Saud",
        funding="O&M - Utilities",
        stage=workflow.INTAKE)
    mom = MomRecord(
        project_id=p.id,
        version=1,
        status="confirmed",
        docx_filename="PR-12643_MOM_v1.docx",
        pdf_filename="PR-12643_MOM_v1.pdf",
        email_subject="Minutes of Meeting — PR-12643 chiller tap",
        email_body=(
            "Attendees: Sara Al Saud (PI), Nadia Haddad (IHP Engineering), "
            "Chris Asis (Trade). Decisions: 4-inch chilled water tap off the "
            "east main; new isolation valves; coordinate shutdown with "
            "Facilities for 6-hour window."
        ),
        note="All action items closed.",
        details={
            "meeting_date": "2026-08-22",
            "attendees": ["Sara Al Saud", "Nadia Haddad", "Chris Asis"],
            "action_items": [
                {"owner": "Nadia Haddad", "item": "Confirm valve spec", "due": "2026-08-29"},
                {"owner": "Chris Asis", "item": "Schedule shutdown", "due": "2026-09-05"},
            ],
        },
        updated_by_id=users["nadia.haddad"].id,
    )
    db.add(mom)
    _audit(db, users["admin"], "project:create", p)
    _audit(db, users["nadia.haddad"], "mom:draft", p, {"version": 1})
    workflow.transition(p, workflow.MOM_SENT, users["nadia.haddad"], db)
    workflow.transition(p, workflow.MOM_CONFIRMED, users["admin"], db,
                        detail={"confirmed_by": "PI", "version": 1})
    return p


def seed_sow_approved(db, users):
    """PR-20001: a project far enough along to exercise SOW, BOQ, MTO, construction wip."""
    p = _new_project(db, users, "PR-20001",
        "Lab gas manifold rebuild — Bldg 5",
        location="Bldg 5 / Lab 5-204",
        pi="Khalid Othman",
        funding="Capital - Lab Safety",
        stage=workflow.INTAKE,
        disposition="PROJECT")
    # Walk through earlier stages to populate the audit trail realistically
    for to_stage, user_key in [
        (workflow.MOM_SENT, "nadia.haddad"),
        (workflow.MOM_CONFIRMED, "admin"),
        (workflow.DISPOSITION, "nadia.haddad"),
        (workflow.EAR_DRAFT, "nadia.haddad"),
        (workflow.EAR_REVIEW, "nadia.haddad"),
        (workflow.EAR_APPROVED, "admin"),
        (workflow.SOW_DRAFT, "nadia.haddad"),
        (workflow.SOW_REVIEW, "nadia.haddad"),
        (workflow.SOW_APPROVED, "admin"),
    ]:
        try:
            workflow.transition(p, to_stage, users[user_key], db)
        except workflow.WorkflowError as e:
            # Some transitions may already be set by the constructor; ignore.
            print(f"  (skip {p.stage}->{to_stage}: {e})")

    # EAR record (draft + AI findings)
    import json
    db.add(EarRecord(
        project_id=p.id, version=1, status="approved",
        summary=(
            "Existing manifold is end-of-life (installed 2009, multiple pin-hole "
            "leaks). Replace with a 4-stainless-header assembly feeding N2, Ar, "
            "CDA, and house vacuum. Coordinate isolation with lab users; install "
            "during a single 16-hour weekend window."
        ),
        recommendations=json.dumps([
            "Replace manifold assembly, retain existing branch valves",
            "Add dedicated vent for purge cycle",
            "Coordinate lab shutdown with PI one week in advance",
        ]),
        budget_data={
            "material_estimate_sar": 145_000,
            "labor_estimate_sar": 62_000,
            "contingency_pct": 15,
            "total_sar": 238_150,
        },
        ai_review_findings=[
            {"rule": "hazardous_isolation", "status": "pass",
             "note": "Lockout/tagout plan referenced in scope."},
            {"rule": "lab_shutdown_notice", "status": "warn",
             "note": "Shutdown window must be confirmed with PI in writing."},
        ],
        docx_filename="PR-20001_EAR_v1.docx",
        pdf_filename="PR-20001_EAR_v1.pdf",
        updated_by_id=users["nadia.haddad"].id,
    ))

    # SOW (approved, one revision)
    db.add(SowRecord(
        project_id=p.id, revision_name="Rev 1", status="approved",
        scope_text=(
            "Demolish existing manifold, install new 4-header stainless assembly "
            "with branch valves, run certified tie-in to existing lab outlets, "
            "perform 24-hour leak test at 1.5x operating pressure, restore lab "
            "services, and submit as-built drawings."
        ),
        trade_sections={
            "Mechanical": ["Demolition", "Header installation", "Pressure test"],
            "Plumbing": ["N2, Ar, CDA, vacuum tie-ins"],
            "Electrical": ["Valve actuator power"],
        },
        procore_comments={"approver": "Procurement + EHS", "approved_on": "2026-09-01",
                          "notes": "Approved as submitted."},
        created_by_id=users["nadia.haddad"].id,
    ))

    # BOQ / MTO design lines (filtered by mto_kind="design" in the UI)
    db.add_all([
        BoqMtoItem(
            project_id=p.id, mto_kind="design", trade="Mechanical",
            item_code="M-104", description='4" SS header, 4-way',
            unit="ea", quantity=1, unit_rate=42_000, total_rate=42_000,
            material_spec='316L SS, 1/2" flare outlets',
            supplier_lead_time_days=21, delivery_status="delivered",
        ),
        BoqMtoItem(
            project_id=p.id, mto_kind="design", trade="Mechanical",
            item_code="M-105", description='Branch ball valve, 1/2" NPT',
            unit="ea", quantity=12, unit_rate=320, total_rate=3_840,
            material_spec="Swagelok SS-83KS4",
            supplier_lead_time_days=10, delivery_status="delivered",
        ),
        BoqMtoItem(
            project_id=p.id, mto_kind="design", trade="Plumbing",
            item_code="P-201", description='N2 tie-in, certified, including permit',
            unit="ls", quantity=1, unit_rate=18_000, total_rate=18_000,
            material_spec="per KAUST plumbing std",
            supplier_lead_time_days=7, delivery_status="in_transit",
        ),
        BoqMtoItem(
            project_id=p.id, mto_kind="design", trade="Mechanical",
            item_code="M-110", description='Pressure gauge panel',
            unit="ea", quantity=1, unit_rate=4_500, total_rate=4_500,
            material_spec="0-300 psi, ASCO-rated",
            supplier_lead_time_days=14, delivery_status="ordered",
        ),
        BoqMtoItem(
            project_id=p.id, mto_kind="design", trade="Plumbing",
            item_code="P-205", description='House vacuum line extension',
            unit="m", quantity=14, unit_rate=180, total_rate=2_520,
            material_spec='1/2" copper, brazed',
            supplier_lead_time_days=5, delivery_status="pending",
        ),
    ])

    # Construction record (planned, with one filed WCF)
    db.add(ConstructionRecord(
        project_id=p.id, status="planned",
        schedule_data={
            "trades": [
                {"trade": "Mechanical", "start": "2026-10-05", "end": "2026-10-09"},
                {"trade": "Plumbing", "start": "2026-10-09", "end": "2026-10-12"},
                {"trade": "Electrical", "start": "2026-10-12", "end": "2026-10-14"},
                {"trade": "Commissioning", "start": "2026-10-15", "end": "2026-10-16"},
            ]
        },
        wcf_data={
            "filed_at": "2026-09-04T08:30:00+03:00",
            "filed_by": "Chris Asis",
            "permit_number": "WCF-2026-0847",
            "scope": "Hot work for copper brazing on vacuum line extension.",
        },
        updated_by_id=users["chris.asis"].id,
    ))
    return p


def seed_closeout(db, users):
    """PR-20002: a finished project in CLOSEOUT so the closeout panel has content."""
    p = _new_project(db, users, "PR-20002",
        "BSL-3 air handler retrofit",
        location="Bldg 3 / BSL-3 Suite",
        pi="Layla Karimi",
        funding="Capital - Life Safety",
        stage=workflow.INTAKE,
        disposition="PROJECT")
    # Walk all the way through to CLOSEOUT
    chain = [
        (workflow.MOM_SENT, "nadia.haddad"),
        (workflow.MOM_CONFIRMED, "admin"),
        (workflow.DISPOSITION, "nadia.haddad"),
        (workflow.EAR_DRAFT, "nadia.haddad"),
        (workflow.EAR_REVIEW, "nadia.haddad"),
        (workflow.EAR_APPROVED, "admin"),
        (workflow.SOW_DRAFT, "nadia.haddad"),
        (workflow.SOW_REVIEW, "nadia.haddad"),
        (workflow.SOW_APPROVED, "admin"),
        (workflow.MTO_DRAFT, "ahmed.alam"),
        (workflow.MTO_APPROVED, "admin"),
        (workflow.PROCUREMENT, "ahmed.alam"),
        (workflow.WORK_PERMIT, "chris.asis"),
        (workflow.CONSTRUCTION, "chris.asis"),
        (workflow.CLOSEOUT, "abdulkader.rokaya"),
    ]
    for to_stage, user_key in chain:
        try:
            workflow.transition(p, to_stage, users[user_key], db)
        except workflow.WorkflowError as e:
            print(f"  (skip {p.stage}->{to_stage}: {e})")

    cr = CloseoutRecord(
        project_id=p.id, status="in_progress",
        testing_commissioning_notes=(
            "HEPA filter DOP test passed 2026-08-20. Airflow pattern verified. "
            "Exhaust stack velocity within spec. Magnehelic gauge calibrations "
            "completed and recorded."
        ),
        as_built_drawings_submitted=True,
        o_and_m_manuals_submitted=True,
        warranty_start_date=date(2026, 8, 25),
        warranty_end_date=date(2027, 8, 25),
        warranty_provider="Carrier Saudi",
        warranty_notes="Standard 12-month parts + labor.",
        client_signoff_by="Layla Karimi",
        client_signoff_date=date(2026, 8, 26),
        client_feedback="All acceptance criteria met.",
        updated_by_id=users["abdulkader.rokaya"].id,
    )
    db.add(cr)
    db.flush()
    # A few punch items, mix of resolved and open
    db.add_all([
        PunchListItem(
            project_id=p.id, closeout_id=cr.id, trade="Mechanical",
            description="Re-torque exhaust fan bolts to spec per OEM memo.",
            location="AHU-1", severity="minor", status="resolved",
            assigned_to="Chris Asis", due_date=date(2026, 8, 30),
            resolved_at=datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc),
            resolution_notes="Re-torqued; recorded on commissioning log.",
        ),
        PunchListItem(
            project_id=p.id, closeout_id=cr.id, trade="Electrical",
            description="Label breaker B-12 per updated as-built.",
            location="MDP room", severity="minor", status="open",
            assigned_to="Chris Asis", due_date=date(2026, 9, 10),
        ),
        PunchListItem(
            project_id=p.id, closeout_id=cr.id, trade="Controls",
            description="Trend log retention to be extended to 30 days.",
            location="BAS panel", severity="minor", status="verified",
            assigned_to="Nadia Haddad", due_date=date(2026, 8, 28),
            resolved_at=datetime(2026, 8, 25, 10, 30, tzinfo=timezone.utc),
            resolution_notes="Set retention to 30 days on 2026-08-25.",
        ),
    ])

    # Mark the construction record as completed
    db.add(ConstructionRecord(
        project_id=p.id, status="completed",
        schedule_data={"trades": [
            {"trade": "Mechanical", "start": "2026-07-01", "end": "2026-07-18"},
            {"trade": "Electrical", "start": "2026-07-15", "end": "2026-07-25"},
            {"trade": "Controls", "start": "2026-07-22", "end": "2026-08-05"},
            {"trade": "Commissioning", "start": "2026-08-05", "end": "2026-08-20"},
        ]},
        wcf_data={
            "filed_at": "2026-06-28T07:00:00+03:00",
            "filed_by": "Chris Asis",
            "permit_number": "WCF-2026-0512",
            "scope": "Hot work for AHU motor replacement.",
        },
        started_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 20, 17, 0, tzinfo=timezone.utc),
        updated_by_id=users["chris.asis"].id,
    ))
    return p


def seed_icr(db, users):
    """PR-20003: ICR branch — straight to MTO, then MTO_APPROVED, no construction."""
    p = _new_project(db, users, "PR-20003",
        "Cryo transfer line replacement",
        location="Bldg 4 / Cryo pad",
        pi="Omar Bilal",
        funding="Capital - Process Support",
        stage=workflow.INTAKE,
        disposition="ICR")
    for to_stage, user_key in [
        (workflow.MOM_SENT, "nadia.haddad"),
        (workflow.MOM_CONFIRMED, "admin"),
        (workflow.DISPOSITION, "nadia.haddad"),
        (workflow.MTO_DRAFT, "ahmed.alam"),
        (workflow.MTO_APPROVED, "admin"),
    ]:
        try:
            workflow.transition(p, to_stage, users[user_key], db)
        except workflow.WorkflowError as e:
            print(f"  (skip {p.stage}->{to_stage}: {e})")

    # ICR hand-off milestones
    db.add_all([
        IcrHandoff(
            project_id=p.id, milestone="MTO_REVIEW",
            status="completed", recorded_by_id=users["ahmed.alam"].id,
            note="Materials list validated by Procurement on 2026-08-30.",
        ),
        IcrHandoff(
            project_id=p.id, milestone="PROJECT_CONTROL_ASSIGN",
            status="in_progress", recorded_by_id=users["ahmed.alam"].id,
            note="Awaiting assignment of project controller (target: 2026-09-12).",
        ),
        IcrHandoff(
            project_id=p.id, milestone="EAT_SCHEDULED",
            status="pending", recorded_by_id=users["ahmed.alam"].id,
            note="EAT walk-down not yet scheduled.",
        ),
    ])
    return p


def main() -> int:
    print(f"DB: {engine.url}")
    db = SessionLocal()
    try:
        print("\n[1/2] Ensuring users exist ...")
        users = _ensure_users(db)

        print("\n[2/2] Wiping prior demo rows ...")
        _wipe_demo(db)

        print("\n[3/5] Seeding PR-12623 (INTAKE) ...")
        seed_intake(db, users)
        print("Seeding PR-12643 (MOM_CONFIRMED) ...")
        seed_mom_confirmed(db, users)
        print("Seeding PR-20001 (SOW_APPROVED + WCF) ...")
        seed_sow_approved(db, users)
        print("Seeding PR-20002 (CLOSEOUT) ...")
        seed_closeout(db, users)
        print("Seeding PR-20003 (ICR, MTO_APPROVED) ...")
        seed_icr(db, users)

        db.commit()
        print("\nDone. Demo portfolio:")
        for p in db.scalars(select(Project).order_by(Project.id)).all():
            title = p.title.encode("ascii", "replace").decode()
            print(f"  #{p.id:>3}  {p.pr_number}  {p.stage:<14}  {p.disposition or '-':<8}  {title}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
