"""SQLAlchemy 2.0 models (typed Mapped style).

Portable column types only (no Postgres-only types) so the same models run
on SQLite (dev/tests) and PostgreSQL (production).
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Roles
ROLE_ADMIN = "admin"
ROLE_TRADE = "trade"
ROLE_PLANNING = "planning"
ROLE_CONSTRUCTION_MANAGER = "construction_manager"
ROLE_TEAM_MEMBER = "team_member"
#: Read-only account: sees dashboards and the register, changes nothing.
ROLE_VIEWER = "viewer"
ROLES = {
    ROLE_ADMIN,
    ROLE_TRADE,
    ROLE_PLANNING,
    ROLE_CONSTRUCTION_MANAGER,
    ROLE_TEAM_MEMBER,
    ROLE_VIEWER,
}

#: Roles a visitor may ask for on the public "request access" form. Admin is
#: never self-service - it is granted only from inside the app.
REQUESTABLE_ROLES: dict[str, str] = {
    ROLE_VIEWER: "Viewer - read-only dashboards and project register",
    ROLE_TEAM_MEMBER: "Team member - view + comment on assigned work",
    ROLE_TRADE: "Trade engineer - submit input for one trade",
    ROLE_PLANNING: "Planning - trackers, imports and schedule",
    ROLE_CONSTRUCTION_MANAGER: "Construction manager - field execution",
}

# Trades (nullable; only meaningful for role == "trade")
TRADES = {
    "civil_arch",
    "electrical",
    "low_current",
    "plumbing",
    "fire_protection",
    "hvac",
}

# Source tags for the data traceability engine (Master Prompt §3):
# DOC = extracted from an uploaded document, PLANNER = confirmed by the
# Planner, SITE = confirmed to exist at site, TBC = pending input,
# ASSUMPTION = AI inference (never promoted without Planner approval).
SOURCE_TAGS = {"DOC", "PLANNER", "SITE", "TBC", "ASSUMPTION"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200), default="")  # job title
    email: Mapped[str] = mapped_column(String(200), default="")
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default=ROLE_TEAM_MEMBER)
    trade: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Per-user capability override. NULL = fall back to the role defaults
    # (see core.rbac.ROLE_DEFAULT_PERMISSIONS); a stored list is the exact
    # effective set (an explicit [] therefore grants nothing).
    permissions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    pr_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ear_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tracking_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pi_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pi_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    funding_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stage: Mapped[str] = mapped_column(String(32), default="INTAKE")
    disposition: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Raw MS-Project Bucket from the IHP planner tracker (EAR, DESIGN,
    #: PTW/WICF, CONSTRUCTION, QUALITY INSPECTION, WCH, WCC, MOM, INTAKE).
    #: Drives the project-register Bucket filter (planner's own grouping).
    planner_bucket: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    #: The Project Summary (EAR) lifecycle, tracked like the MOM: NULL/none,
    #: draft (being written), sent (with the PI), acknowledged.
    summary_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Who on the IHP side owns this project right now (boards "assign to").
    owner_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: The current follow-up note - what the board shows under "what to do".
    followup_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: The single "next step" plan for this PR: which lifecycle stage comes
    #: next, in which Planner bucket it is followed up, who owns it and when
    #: it is due. One row per project (not per stage) so the whole picture is
    #: readable at a glance; the sub-tasks live in ProjectTodo.
    next_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_stage_bucket: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_stage_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    next_stage_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    next_step_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Cancellation record. Cancelling is terminal: the PI re-initiates under
    #: a NEW PR, so the reason, the written justification and the date the PI
    #: was told are the only things that keep the decision auditable.
    cancel_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cancel_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    todos: Mapped[list["ProjectTodo"]] = relationship(
        back_populates="project", order_by="ProjectTodo.id",
        cascade="all, delete-orphan",
    )
    #: The PR data room: every raw file the engineer / PI / supplier sent.
    sources: Mapped[list["SourceDocument"]] = relationship(
        back_populates="project", order_by="SourceDocument.id",
        cascade="all, delete-orphan",
    )
    #: Versioned AI readings of that data room.
    source_briefs: Mapped[list["SourceBrief"]] = relationship(
        back_populates="project", order_by="SourceBrief.id",
        cascade="all, delete-orphan",
    )
    plan_markers: Mapped[list["PlanMarker"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="project", order_by="Attachment.id", cascade="all, delete-orphan"
    )
    mom: Mapped["MomRecord | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    # Stage 2-6 deliverables (one row per stage-relationship, optional)
    ear: Mapped["EarRecord | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    sow_records: Mapped[list["SowRecord"]] = relationship(
        back_populates="project", order_by="SowRecord.id", cascade="all, delete-orphan"
    )
    boq_items: Mapped[list["BoqMtoItem"]] = relationship(
        back_populates="project", order_by="BoqMtoItem.id", cascade="all, delete-orphan"
    )
    # Construction MTO is reconciled against the design BOQ/MTO.
    construction_mto_items: Mapped[list["ConstructionMtoItem"]] = relationship(
        back_populates="project",
        order_by="ConstructionMtoItem.id",
        cascade="all, delete-orphan",
    )
    construction: Mapped["ConstructionRecord | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    closeout: Mapped["CloseoutRecord | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    # ICR branch: MTO -> Project Control hand-off -> Equipment Assessment
    # Team install/follow-up. These are scoped to disposition == "ICR".
    icr_handoffs: Mapped[list["IcrHandoff"]] = relationship(
        back_populates="project", order_by="IcrHandoff.id", cascade="all, delete-orphan"
    )
    # Source-tagged data points (traceability engine, Master Prompt §3).
    data_points: Mapped[list["DataPoint"]] = relationship(
        back_populates="project", order_by="DataPoint.id", cascade="all, delete-orphan"
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(600))
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="attachments")




class PlanMarker(Base):
    """A labelled pin on a floor-plan drawing.

    The plan itself is an ordinary project attachment (a PDF export of the
    AutoCAD drawing); a marker points at a spot on it, expressed in percent of
    the rendered page so it survives re-rendering at any size. The label
    carries the PI (names change), an optional PR reference and a note - a
    location that used to be one PI's becomes two markers when it is divided,
    and the history of who held what is the audit trail, not a guess.
    """

    __tablename__ = "plan_markers"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    #: The attachment this pin belongs to (the plan PDF), when chosen.
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True
    )
    #: Page of the PDF the coordinates refer to (1-based).
    page: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(200))
    pi_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pr_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Position as a percent of the page (0-100), origin top-left.
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="plan_markers")


class MomRecord(Base):
    """Minutes of Meeting record - exactly one per project (upserted on regenerate)."""

    __tablename__ = "mom_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), unique=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    docx_filename: Mapped[str] = mapped_column(String(300))
    pdf_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    email_subject: Mapped[str] = mapped_column(String(400), default="")
    email_body: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # KAUST MOM template fields: meeting_title/location/number/date/time,
    # attendees [{name,title,email}], agenda [{scope,action,etc}].
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="mom")


class CorpusDocument(Base):
    """An ingested document in the AI retrieval corpus.

    `source` is "upload" (direct corpus upload) or "attachment" (ingested
    from a project attachment, which scopes it via `project_id`).
    """

    __tablename__ = "corpus_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(32))
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    chunks: Mapped[list["CorpusChunk"]] = relationship(
        back_populates="document", order_by="CorpusChunk.chunk_index"
    )


class CorpusChunk(Base):
    """One text chunk of a corpus document, with an optional embedding.

    `project_id` is denormalized from the document for scoped retrieval
    (no FK; NULL means global/unscoped). `embedding` is NULL when the AI
    provider was offline at ingest time — retrieval then falls back to
    keyword scoring.
    """

    __tablename__ = "corpus_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("corpus_documents.id"), index=True
    )
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # none_as_null=True: a missing vector must be SQL NULL, not the JSON literal
    # "null" - otherwise "WHERE embedding IS NULL" (the backfill query) never
    # matches and every chunk looks embedded.
    embedding: Mapped[list[float] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )

    document: Mapped[CorpusDocument] = relationship(back_populates="chunks")


class AuditLog(Base):
    """Append-only audit trail. `detail` is JSON (works on SQLite + Postgres)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class DataPoint(Base):
    """One source-tagged project data point (traceability engine, §3).

    Generic provenance row: any stage panel or AI extraction can register a
    data point carrying a DOC / PLANNER / SITE / TBC / ASSUMPTION tag. The
    CONFIRM action (data.confirm capability) promotes a pending tag
    (TBC / ASSUMPTION) to PLANNER — stamped here and audited in AuditLog.
    Editing the value voids the stamp so nothing stale reads as confirmed.
    """

    __tablename__ = "data_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    #: UI grouping, e.g. "utility", "cost", "schedule", "general".
    category: Mapped[str] = mapped_column(String(32), default="general")
    #: Stable machine key, e.g. "utility.electricity.voltage".
    field_key: Mapped[str] = mapped_column(String(128))
    #: Human label shown in tables and generated documents.
    label: Mapped[str] = mapped_column(String(300))
    value: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: One of SOURCE_TAGS.
    source_tag: Mapped[str] = mapped_column(String(16), default="TBC")
    #: Provenance for DOC-tagged points: filename + page/sheet reference.
    source_file: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Set by the CONFIRM action (tag promoted to PLANNER).
    confirmed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="data_points")
    confirmed_by: Mapped["User | None"] = relationship(
        foreign_keys=[confirmed_by_id], lazy="selectin"
    )
    created_by: Mapped["User"] = relationship(
        foreign_keys=[created_by_id], lazy="selectin"
    )


# --- Stages 2-6 deliverable records -----------------------------------------
#
# Per Section 2 of the v2 upgrade spec, MTO is split into two separate,
# trackable documents:
#   - Design MTO = the BOQ/MTO line items produced at SOW/BOQ time
#     (BoqMtoItem, owned by Planning/Trade).
#   - Construction MTO = the as-awarded/as-built take-off used during
#     construction (ConstructionMtoItem, owned by Construction Department),
#     which reconciles back to the design MTO and flags variances.
# ICR-classified projects route straight to ConstructionMtoItem without ever
# producing a BoqMtoItem (no SOW, no design BOQ).


class EarRecord(Base):
    """Engineering Assessment Report — one per project.

    Created on first read of /api/projects/{id}/ear; the ICR branch never
    produces one.
    """

    __tablename__ = "ear_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), unique=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    summary: Mapped[str] = mapped_column(Text, default="")
    recommendations: Mapped[str] = mapped_column(Text, default="")
    #: { rates: {overhead, contingency, profit, escalation},
    #:   trade_budgets: {trade: {materials, manpower}},
    #:   billing_type: "pi_baseline" | "asepc_ihp" }
    budget_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: List of {trade, type, description, citation, resolution} findings from
    #: the AI compliance review.
    ai_review_findings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    docx_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pdf_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="ear")
    trade_inputs: Mapped[list["EarTradeInput"]] = relationship(
        back_populates="ear", order_by="EarTradeInput.id", cascade="all, delete-orphan"
    )


class EarTradeInput(Base):
    """One trade's proposal contribution to the EAR."""

    __tablename__ = "ear_trade_inputs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ear_id: Mapped[int] = mapped_column(
        ForeignKey("ear_records.id"), index=True
    )
    trade: Mapped[str] = mapped_column(String(64))
    proposal: Mapped[str] = mapped_column(Text, default="")
    comments: Mapped[str] = mapped_column(Text, default="")
    missing_info: Mapped[str] = mapped_column(Text, default="")
    has_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    conflict_reason_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    conflict_resolution_note: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    estimated_materials_cost: Mapped[float] = mapped_column(default=0.0)
    estimated_manpower_cost: Mapped[float] = mapped_column(default=0.0)
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    ear: Mapped[EarRecord] = relationship(back_populates="trade_inputs")


class SowRecord(Base):
    """A single SOW revision (Rev-0, Rev-1, ...)."""

    __tablename__ = "sow_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    revision_name: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    scope_text: Mapped[str] = mapped_column(Text, default="")
    trade_sections: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    procore_comments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="sow_records")


class BoqMtoItem(Base):
    """Design-stage BOQ / MTO line item.

    Produced during SOW/BOQ stage. Reused as the Design MTO that the
    Construction MTO (ConstructionMtoItem) reconciles against.
    """

    __tablename__ = "boq_mto_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    #: "design" (default) or "construction" — kept on the row so a single
    #: table can hold both, with the BOQ/MTO panel defaulting to design
    #: lines. See also ConstructionMtoItem for the construction-as-built
    #: split.
    mto_kind: Mapped[str] = mapped_column(String(16), default="design")
    trade: Mapped[str] = mapped_column(String(64))
    item_code: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[float] = mapped_column(default=0.0)
    unit_rate: Mapped[float] = mapped_column(default=0.0)
    total_rate: Mapped[float] = mapped_column(default=0.0)
    material_spec: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="boq_items")


class ConstructionMtoItem(Base):
    """Construction-stage MTO line (as-awarded / as-built).

    Reconciled against BoqMtoItem rows by item_code; variance fields
    (variance_qty, variance_reason) capture quantity and spec drift.
    """

    __tablename__ = "construction_mto_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    trade: Mapped[str] = mapped_column(String(64))
    item_code: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[float] = mapped_column(default=0.0)
    unit_rate: Mapped[float] = mapped_column(default=0.0)
    total_rate: Mapped[float] = mapped_column(default=0.0)
    material_spec: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Set when this row is the actual quantity vs the design row; +N = over,
    #: -N = under, NULL = not yet reconciled.
    variance_qty: Mapped[float | None] = mapped_column(nullable=True)
    variance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="construction_mto_items")


class ConstructionRecord(Base):
    """Construction execution record (one per Project)."""

    __tablename__ = "construction_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="planned")
    #: Free-form trade-wise execution chart data:
    #: { trade: [{task, start, end, assignee, pct_complete}] }
    schedule_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: Work-permit / WCF tracking numbers, dates, attachments references.
    wcf_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="construction")


class CloseoutRecord(Base):
    """Closeout & punch list (per Section 2: as-builts, O&M, warranty, signoff)."""

    __tablename__ = "closeout_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="open")
    testing_commissioning_notes: Mapped[str] = mapped_column(Text, default="")
    as_built_drawings_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    o_and_m_manuals_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    warranty_start_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    warranty_end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    warranty_provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    warranty_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_signoff_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    client_signoff_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="closeout")
    punch_items: Mapped[list["PunchListItem"]] = relationship(
        back_populates="closeout",
        order_by="PunchListItem.id",
        cascade="all, delete-orphan",
    )


class PunchListItem(Base):
    """One row on the project's punch list."""

    __tablename__ = "punch_list_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    closeout_id: Mapped[int] = mapped_column(
        ForeignKey("closeout_records.id"), index=True
    )
    trade: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    severity: Mapped[str] = mapped_column(String(32), default="minor")
    status: Mapped[str] = mapped_column(String(32), default="open")
    assigned_to: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    closeout: Mapped[CloseoutRecord] = relationship(back_populates="punch_items")


class IcrHandoff(Base):
    """ICR-branch hand-off record (Project Control / Equipment Assessment Team).

    Only created when project.disposition == "ICR". Tracks:
    - MTO sent to Project Control (date, who, materials list)
    - Materials ordered/received status
    - Equipment Assessment Team install status
    - Follow-up notes

    Distinct from the Construction dashboard; never reaches the construction
    department, never requires a WCF / work permit.
    """

    __tablename__ = "icr_handoffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    #: "mto_to_project_control", "materials_ordered", "materials_received",
    #: "eat_install_scheduled", "eat_installed", "follow_up", "closed".
    milestone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="icr_handoffs")


class MasterPricing(Base):
    """Master pricing item imported from MACC or managed by admin."""

    __tablename__ = "master_pricing"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    trade: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit: Mapped[str] = mapped_column(String(32), default="EA")
    base_unit_rate: Mapped[float] = mapped_column(default=0.0)
    currency: Mapped[str] = mapped_column(String(16), default="SAR")
    #: Who quoted it (the store's quotation export carries the supplier).
    supplier: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class AiMaterialsProposal(Base):
    """An AI/keyword-coordinated draft materials list for a project.

    Generated from the project request + assessment scope against the
    materials master list (master_pricing). Every item in `items` is an
    AI/keyword SUGGESTION — an ASSUMPTION under the §3 traceability
    rules — until a Planner accepts the proposal, at which point the
    accepted lines become design BoqMtoItem rows priced from the master.
    """

    __tablename__ = "ai_materials_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    #: "EAR" (assessment budget section) or "MTO" (MTO draft)
    stage_target: Mapped[str] = mapped_column(String(8), default="MTO")
    #: draft -> accepted | rejected
    status: Mapped[str] = mapped_column(String(16), default="draft")
    #: "ai" (LLM-coordinated selection) | "keyword" (deterministic fallback)
    mode: Mapped[str] = mapped_column(String(16), default="keyword")
    #: [{item_code, description, trade, unit, unit_rate, qty, line_total,
    #:   reason, origin: "ai"|"keyword"}]
    items: Mapped[list] = mapped_column(JSON, default=list)
    subtotal_sar: Mapped[float] = mapped_column(default=0.0)
    vat_sar: Mapped[float] = mapped_column(default=0.0)
    total_sar: Mapped[float] = mapped_column(default=0.0)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    project: Mapped["Project"] = relationship()



class ProjectBudgetSummary(Base):
    """Project budget snapshot across workflow stages."""

    __tablename__ = "project_budget_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    stage_at_snapshot: Mapped[str] = mapped_column(String(32), default="INTAKE")
    snapshot_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    subtotal_sar: Mapped[float] = mapped_column(default=0.0)
    vat_sar: Mapped[float] = mapped_column(default=0.0)
    total_sar: Mapped[float] = mapped_column(default=0.0)
    total_usd: Mapped[float] = mapped_column(default=0.0)
    items_count: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "stage_at_snapshot": self.stage_at_snapshot,
            "snapshot_date": self.snapshot_date.isoformat() if self.snapshot_date else None,
            "subtotal_sar": self.subtotal_sar,
            "vat_sar": self.vat_sar,
            "total_sar": self.total_sar,
            "total_usd": self.total_usd,
            "items_count": self.items_count,
        }


class ProjectStageBudget(Base):
    """Stage budget tracking for committed vs remaining budget."""

    __tablename__ = "project_stage_budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    stage: Mapped[str] = mapped_column(String(32))
    budget_sar: Mapped[float] = mapped_column(default=0.0)
    estimated_sar: Mapped[float] = mapped_column(default=0.0)
    committed_sar: Mapped[float] = mapped_column(default=0.0)
    remaining_sar: Mapped[float] = mapped_column(default=0.0)
    created_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_date: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "stage": self.stage,
            "budget_sar": self.budget_sar,
            "estimated_sar": self.estimated_sar,
            "committed_sar": self.committed_sar,
            "remaining_sar": self.remaining_sar,
            "created_date": self.created_date.isoformat() if self.created_date else None,
            "updated_date": self.updated_date.isoformat() if self.updated_date else None,
        }
class CrewAssignment(Base):
    """One person's work allocation to a project for one day and shift.

    The construction day is two 4-hour shifts - AM (07:00-11:00) and
    PM (12:00-16:00) - so a fully loaded person is 8 hours. Assignments
    drive the live work-load board: per person per day, per project totals,
    and the over-allocation warnings when somebody is booked past 8 hours.
    """

    __tablename__ = "crew_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    person_name: Mapped[str] = mapped_column(String(200), index=True)
    person_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    person_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    work_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    #: "AM" (07:00-11:00), "PM" (12:00-16:00) or "FULL" for both.
    shift: Mapped[str] = mapped_column(String(8), default="FULL")
    hours: Mapped[float] = mapped_column(Float, default=8.0)
    task: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Notification bookkeeping (email / whatsapp / sms).
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notify_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notify_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    project: Mapped["Project"] = relationship()


class AccessRequest(Base):
    """A visitor's request for an account, decided by an admin in the app.

    The public site is a read-only dashboard; nothing else is reachable without
    an account. A visitor asks for access here, the request shows up in the
    admin inbox, and approving it creates the user plus a one-time invite link
    that the admin sends on whichever channel they prefer. The token is stored
    on this row (single use, expiring) so no change to the users table is
    needed.
    """

    __tablename__ = "access_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Role the visitor asked for (see REQUESTABLE_ROLES).
    requested_role: Mapped[str] = mapped_column(String(32), default=ROLE_VIEWER)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: pending | approved | rejected
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    #: Admin note shown in the inbox (why it was rejected, etc).
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Set on approval: the one-time link that lets the invitee set a password.
    invite_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invite_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: The account created on approval.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    #: Client metadata for the admin inbox (rate limiting + traceability).
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

class ProjectTodo(Base):
    """One follow-up task on a PR, filed under the bucket it belongs to.

    A project has exactly one *next step* (see Project.next_stage) and any
    number of tasks that get it there. The bucket is the Planner bucket the
    task is followed up in (EAR, DESIGN, PROCORE, PTW/WICF, CONSTRUCTION,
    SHUTDOWN, QUALITY INSPECTION, WCC, WCH, MTO/ICR, ...), so the global
    to-do list can show the whole picture grouped the way the team works.
    """

    __tablename__ = "project_todos"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    #: Planner bucket for follow-up (free text, kept uppercase).
    bucket: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    #: Optional target workflow stage for this task.
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assignee_username: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: open | done
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    project: Mapped[Project] = relationship(back_populates="todos")

class SourceDocument(Base):
    """One raw file in a PR data room.

    The engineer's raw data arrives in any format: the PR form, a utility
    matrix, the technical specification, drawings, supplier quotations, PI
    emails, costing sheets. The file is stored verbatim and its text is
    cached next to it, so the AI can read it and the reviewer can see which
    file said what. `category` mirrors the archive taxonomy the team already
    files by (01_Initiation ... 11_Reports); `doc_type` is what the document
    is.
    """

    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    category: Mapped[str] = mapped_column(String(32), default="99_Unsorted", index=True)
    doc_type: Mapped[str] = mapped_column(String(32), default="other", index=True)
    filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(600))
    #: Where the extracted plain text is cached (None when there is none).
    text_path: Mapped[str | None] = mapped_column(String(600), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    text_chars: Mapped[int] = mapped_column(Integer, default=0)
    text_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="sources")


class SourceBrief(Base):
    """The AI's structured reading of a PR data room (one row per run).

    Versioned: every analysis is kept, so a brief that contradicts the
    previous one is visible instead of silently overwriting it. `payload`
    holds scope-by-trade, the utility matrix, the line items, the open
    technical questions and the documents the model actually saw.
    """

    __tablename__ = "source_briefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    #: running | ready | failed
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="source_briefs")


class BriefQuestion(Base):
    """One open question from the AI brief, with the answer kept on it.

    The briefs are versioned and replaced; the answers are not. A question is
    matched on its text, so re-running the analysis keeps every answer that was
    already written and only adds the new questions.
    """

    __tablename__ = "brief_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    who_can_answer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    #: The answer written by the engineer / PI, and who wrote it.
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: open | answered | closed
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    answered_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class MtoDraftItem(Base):
    """One line of a project's materials take-off draft.

    The take-off is built up over days: pick a valve from the price master
    today, type in the item the supplier quoted tomorrow, generate the file
    when the scope settles. The draft is therefore stored per project and
    survives reloads, deploys and restarts - the MTO never disappears.
    """

    __tablename__ = "mto_draft_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    #: Display order inside the take-off.
    position: Mapped[int] = mapped_column(Integer, default=0)
    trade: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    qty: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: The price-master row this line was picked from, when it was picked.
    item_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

