"""Pydantic v2 DTOs - the API contract the frontend builds against."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from .core.rbac import ROLE_DEFAULT_PERMISSIONS
from .models import ROLES, TRADES


def normalize_code(value: str) -> str:
    """Normalize a free-text role/trade to a lowercase_underscore code."""
    return "_".join(value.strip().lower().split())


# ---------- Master Pricing (MACC import) ----------


class MasterPricingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_code: str
    description: str
    trade: str | None
    unit: str
    base_unit_rate: float
    currency: str
    description_ar: str | None
    is_active: bool
    created_date: datetime
    last_updated: datetime

    @classmethod
    def from_orm(cls, obj):
        return cls(
            id=obj.id,
            item_code=obj.item_code,
            description=obj.description,
            trade=obj.trade,
            unit=obj.unit,
            base_unit_rate=obj.base_unit_rate,
            currency=obj.currency,
            description_ar=obj.description_ar,
            is_active=obj.is_active,
            created_date=obj.created_date,
            last_updated=obj.last_updated,
        )


class MasterPricingIn(BaseModel):
    item_code: str
    description: str
    trade: str | None = None
    unit: str = "EA"
    base_unit_rate: float
    currency: str = "SAR"
    description_ar: str | None = None
    is_active: bool = True
    notes: str | None = None


class ProjectBudgetSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    stage_at_snapshot: str
    snapshot_date: datetime
    subtotal_sar: float = 0.0
    vat_sar: float = 0.0
    total_sar: float = 0.0
    total_usd: float = 0.0
    items_count: int = 0


class ProjectStageBudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    stage: str
    budget_sar: float = 0.0
    estimated_sar: float = 0.0
    committed_sar: float = 0.0
    remaining_sar: float = 0.0
    created_date: datetime
    updated_date: datetime


# ---------- auth ----------
class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- users ----------
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    email: str
    role: str
    trade: str | None
    title: str = ""
    is_active: bool
    permissions: list[str]

    @field_validator("permissions", mode="before")
    @classmethod
    def _effective_permissions(cls, value, info: ValidationInfo) -> list[str]:
        """The ORM column is the raw override (None = use role defaults);
        the API always exposes the effective set, sorted."""
        if value is None:
            role = info.data.get("role", "")
            return sorted(ROLE_DEFAULT_PERMISSIONS.get(role, set()))
        return sorted(set(value))


class UserCreate(BaseModel):
    username: str
    full_name: str
    email: str
    password: str
    # Free-text role/trade: standard values (admin, trade, planning, ...) or
    # any custom label the admin defines. Normalized to lowercase_underscore.
    role: str = "team_member"
    trade: str | None = None
    title: str = ""
    permissions: list[str] | None = None

    @field_validator("role")
    @classmethod
    def _normalize_role(cls, value: str) -> str:
        return normalize_code(value) or "team_member"

    @field_validator("trade")
    @classmethod
    def _normalize_trade(cls, value: str | None) -> str | None:
        return normalize_code(value) if value else None


class UserUpdate(BaseModel):
    """PATCH-style admin edit: only provided fields are applied."""

    full_name: str | None = None
    email: str | None = None
    title: str | None = None
    role: str | None = None
    trade: str | None = None
    password: str | None = None
    is_active: bool | None = None
    permissions: list[str] | None = None

    @field_validator("role")
    @classmethod
    def _normalize_role(cls, value: str | None) -> str | None:
        return normalize_code(value) if value else None

    @field_validator("trade")
    @classmethod
    def _normalize_trade(cls, value: str | None) -> str | None:
        return normalize_code(value) if value else None


class ProfileUpdate(BaseModel):
    """Self-service profile edit — users can change their own name, email, title."""

    full_name: str | None = None
    email: str | None = None
    title: str | None = None


class ChangePassword(BaseModel):
    """Self-service password change — requires current password for verification."""

    current_password: str
    new_password: str


# ---------- projects ----------
class ProjectCreate(BaseModel):
    pr_number: str
    ear_number: str | None = None
    title: str
    description: str | None = None
    location: str | None = None
    pi_name: str | None = None
    pi_email: str | None = None
    funding_source: str | None = None


class ProjectUpdate(BaseModel):
    """PATCH-style project edit: only provided fields are applied."""

    title: str | None = None
    pr_number: str | None = None
    ear_number: str | None = None
    description: str | None = None
    location: str | None = None
    pi_name: str | None = None
    pi_email: str | None = None
    funding_source: str | None = None
    # Tracker metadata editable from the bucket dashboards.
    planner_bucket: str | None = None
    disposition: str | None = None


class ProjectListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pr_number: str
    ear_number: str | None = None
    tracking_token: str | None = None
    title: str
    pi_name: str | None
    location: str | None
    funding_source: str | None
    stage: str
    disposition: str | None
    created_at: datetime
    # Tracker-derived fields (parsed from description by the API; None
    # for projects with no tracker import). Drives the project-register
    # filters.
    project_type: str | None = None
    trades: list[str] = []
    division: str | None = None
    priority: str | None = None
    completion_pct: int | None = None
    source: str | None = None  # "planner" | "om" | "manual" | "demo"
    #: Raw IHP planner Bucket (EAR, DESIGN, PTW/WICF, CONSTRUCTION, WCH,
    #: WCC, ...). Drives the register Bucket filter.
    planner_bucket: str | None = None
    #: Notes/Labels analysis (services/planner_status.py). `latest_status`
    #: is the CURRENT state read from the last milestone in the Notes log.
    latest_status: str | None = None
    latest_status_date: str | None = None
    status_timeline: list[str] = []
    flags: list[str] = []
    checklist: str | None = None
    #: Lifecycle division: "EAR" | "Design" | "Construction" | "Close-up".
    phase: str | None = None
    #: EAR-only funnel step: "on_hold" | "ear_approved" | "ear_issued" |
    #: "wbs_request" | "awaiting_summary" | "site_visit" | "in_progress".
    ear_substatus: str | None = None
    #: The date the EAR was approved (read from the "EAR approved on ..." note).
    ear_approved_date: str | None = None
    #: Planner schedule fields.
    start_date: str | None = None
    finish_date: str | None = None
    effort: str | None = None
    duration: str | None = None
    #: Date of the Planner snapshot this row came from (from the file name).
    planner_sync_date: str | None = None
    #: True when the row is present in the NEWEST Planner snapshot. Stale
    #: rows (removed/cancelled PRs) are excluded from the live counts.
    in_latest_planner: bool = False


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    stage: str
    filename: str
    content_type: str | None
    size_bytes: int
    version: int
    uploaded_by_id: int
    created_at: datetime


class MomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    version: int
    status: str
    docx_filename: str
    pdf_filename: str | None
    email_subject: str
    email_body: str
    note: str | None
    details: dict | None = None
    updated_by_id: int
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectListItem):
    description: str | None
    pi_email: str | None
    created_by_id: int
    updated_at: datetime
    attachments: list[AttachmentOut] = []
    mom: MomOut | None = None
    #: Stage 2-7 deliverables inlined into the project detail so panels can
    #: read them from a single getProject() round-trip. Optional; the related
    #: rows are created lazily by their own endpoints as the project advances.
    ear: "EarOut | None" = None
    sow_records: list["SowOut"] = []
    boq_items: list["BoqItemOut"] = []
    construction: "ConstructionOut | None" = None
    closeout: "CloseoutOut | None" = None
    icr_handoffs: list["IcrHandoffOut"] = []


# ---------- MOM status ----------
class MomStatusUpdate(BaseModel):
    status: Literal["sent", "acknowledged", "disputed"]
    note: str | None = None


# ---------- MOM meeting details (KAUST template) ----------
class MomAttendee(BaseModel):
    name: str = ""
    title: str = ""
    email: str = ""


class MomAgendaItem(BaseModel):
    scope: str = ""
    action: str = ""
    etc: str = ""
    # Trade label: "Civil/Architectural", "Electrical", "Plumbing", "HVAC",
    # or a free-text custom trade ("Others").
    trade: str | None = None


class MomDetails(BaseModel):
    meeting_title: str | None = None
    meeting_location: str | None = None
    meeting_number: str | None = None
    meeting_date: str | None = None
    meeting_time: str | None = None
    attendees: list[MomAttendee] = []
    agenda: list[MomAgendaItem] = []


# ---------- audit ----------
class AuditOut(BaseModel):
    id: int
    user: str  # username
    action: str
    detail: dict | None
    created_at: datetime


# ---------- Stage 2: Disposition ----------
class DispositionUpdate(BaseModel):
    disposition: Literal["ICR", "PROJECT"]
    justification: str | None = None


# ---------- Stage 3: EAR ----------
class EarUpdate(BaseModel):
    summary: str | None = None
    recommendations: str | None = None
    status: Literal["draft", "under_review", "approved"] | None = None


class EarTradeInputCreate(BaseModel):
    trade: str
    proposal: str = ""
    comments: str = ""
    missing_info: str = ""
    has_conflict: bool = False
    conflict_reason_code: str | None = None
    conflict_resolution_note: str | None = None
    estimated_materials_cost: float = 0.0
    estimated_manpower_cost: float = 0.0


class EarTradeInputOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ear_id: int
    trade: str
    proposal: str
    comments: str
    missing_info: str
    has_conflict: bool
    conflict_reason_code: str | None
    conflict_resolution_note: str | None
    estimated_materials_cost: float
    estimated_manpower_cost: float
    updated_by_id: int
    updated_at: datetime


class EarBudgetUpdate(BaseModel):
    rates: dict | None = None
    trade_budgets: dict | None = None
    billing_type: Literal["pi_baseline", "asepc_ihp"]


class EarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    version: int
    status: str
    summary: str
    recommendations: str
    budget_data: dict | None
    ai_review_findings: list | None
    docx_filename: str | None
    pdf_filename: str | None
    updated_by_id: int
    created_at: datetime
    updated_at: datetime


# ---------- Stage 4: SOW ----------
class SowRevisionCreate(BaseModel):
    revision_name: str | None = None
    scope_text: str | None = None
    trade_sections: dict | None = None
    procore_comments: dict | None = None


class SowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    revision_name: str
    status: str
    scope_text: str
    trade_sections: dict | None
    procore_comments: dict | None
    created_by_id: int
    created_at: datetime
    updated_at: datetime


# ---------- Stage 4: BOQ / Design MTO + Stage 5: Construction MTO ----------
# Note: BoqMtoItem and ConstructionMtoItem are split tables, but share an
# essentially identical line-item shape. The two schemas below are
# deliberately separate so the API can express which table the row lives in.


class BoqItemCreate(BaseModel):
    trade: str
    item_code: str
    description: str = ""
    unit: str
    quantity: float
    unit_rate: float
    material_spec: str | None = None
    supplier_lead_time_days: int | None = None
    #: "design" (default) or "construction" — routes to the right table.
    mto_kind: Literal["design", "construction"] = "design"


class BoqItemUpdate(BaseModel):
    trade: str | None = None
    item_code: str | None = None
    description: str | None = None
    unit: str | None = None
    quantity: float | None = None
    unit_rate: float | None = None
    material_spec: str | None = None
    supplier_lead_time_days: int | None = None
    delivery_status: Literal[
        "pending", "ordered", "in_transit", "delivered", "cancelled"
    ] | None = None


class BoqItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    mto_kind: str
    trade: str
    item_code: str
    description: str
    unit: str
    quantity: float
    unit_rate: float
    total_rate: float
    material_spec: str | None
    supplier_lead_time_days: int | None
    delivery_status: str
    created_at: datetime
    updated_at: datetime


BoqMtoItemOut = BoqItemOut


class ConstructionMtoItemCreate(BaseModel):
    trade: str
    item_code: str
    description: str = ""
    unit: str
    quantity: float
    unit_rate: float
    material_spec: str | None = None


class ConstructionMtoItemUpdate(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_rate: float | None = None
    material_spec: str | None = None
    delivery_status: Literal[
        "pending", "ordered", "in_transit", "delivered", "cancelled"
    ] | None = None


class ConstructionMtoItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    trade: str
    item_code: str
    description: str
    unit: str
    quantity: float
    unit_rate: float
    total_rate: float
    material_spec: str | None
    variance_qty: float | None
    variance_reason: str | None
    delivery_status: str
    created_at: datetime
    updated_at: datetime


# ---------- Stage 6: Construction ----------
class ConstructionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    status: str
    schedule_data: dict | None
    wcf_data: dict | None
    started_at: datetime | None
    completed_at: datetime | None
    updated_by_id: int
    created_at: datetime
    updated_at: datetime


class ConstructionUpdate(BaseModel):
    status: str | None = None
    schedule_data: dict | None = None
    wcf_data: dict | None = None


# ---------- Cross-project construction dashboard ----------
class ConstructionDashboardKpis(BaseModel):
    total_projects: int
    active_construction_projects: int
    total_materials_tracked: int
    materials_delivered: int
    active_work_permits: int
    delivery_rate: float


class ConstructionProjectSummary(BaseModel):
    id: int
    pr_number: str
    title: str
    stage: str
    location: str | None
    pi_name: str | None
    disposition: str | None
    created_at: datetime
    permits_count: int
    active_permits_count: int
    materials_count: int
    materials_delivered_count: int
    team_count: int


# ---------- Stage 7: Closeout ----------
class PunchListItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    closeout_id: int
    trade: str
    description: str
    location: str
    severity: str
    status: str
    assigned_to: str | None
    due_date: datetime | None
    resolved_at: datetime | None
    resolution_notes: str | None
    created_at: datetime
    updated_at: datetime


class CloseoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    status: str
    testing_commissioning_notes: str
    as_built_drawings_submitted: bool
    o_and_m_manuals_submitted: bool
    warranty_start_date: datetime | None
    warranty_end_date: datetime | None
    warranty_provider: str | None
    warranty_notes: str | None
    client_signoff_by: str | None
    client_signoff_date: datetime | None
    client_feedback: str | None
    updated_by_id: int
    created_at: datetime
    updated_at: datetime
    #: Inlined punch list so the closeout panel can render without a second
    #: round-trip. Empty list until punch items are added.
    punch_items: list["PunchListItemOut"] = []


# ---------- ICR branch hand-off ----------
class IcrHandoffCreate(BaseModel):
    milestone: Literal[
        "mto_to_project_control",
        "materials_ordered",
        "materials_received",
        "eat_install_scheduled",
        "eat_installed",
        "follow_up",
        "closed",
    ]
    status: Literal["pending", "in_progress", "done", "blocked"] = "pending"
    note: str | None = None


class IcrHandoffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    milestone: str
    status: str
    note: str | None
    recorded_by_id: int
    recorded_at: datetime


# ---------- Source-tagged data points (traceability, master prompt §3) ----------
class DataPointCreate(BaseModel):
    category: str = "general"
    field_key: str
    label: str
    value: str = ""
    unit: str | None = None
    source_tag: Literal["DOC", "PLANNER", "SITE", "TBC", "ASSUMPTION"] = "TBC"
    source_file: str | None = None
    source_location: str | None = None
    note: str | None = None


class DataPointUpdate(BaseModel):
    """PATCH-style edit: only provided fields are applied. Changing `value`
    (or dropping back to a pending tag) voids the confirmation stamp."""

    category: str | None = None
    field_key: str | None = None
    label: str | None = None
    value: str | None = None
    unit: str | None = None
    source_tag: Literal["DOC", "PLANNER", "SITE", "TBC", "ASSUMPTION"] | None = None
    source_file: str | None = None
    source_location: str | None = None
    note: str | None = None


class DataPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    category: str
    field_key: str
    label: str
    value: str
    unit: str | None
    source_tag: str
    source_file: str | None
    source_location: str | None
    note: str | None
    confirmed_by_id: int | None
    #: Username of the confirming Planner (None until CONFIRM).
    confirmed_by: str | None = None
    confirmed_at: datetime | None
    created_by_id: int
    #: Username of the creator.
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dp(cls, dp) -> "DataPointOut":
        """Build the DTO from the ORM row, resolving username labels."""
        return cls(
            id=dp.id,
            project_id=dp.project_id,
            category=dp.category,
            field_key=dp.field_key,
            label=dp.label,
            value=dp.value,
            unit=dp.unit,
            source_tag=dp.source_tag,
            source_file=dp.source_file,
            source_location=dp.source_location,
            note=dp.note,
            confirmed_by_id=dp.confirmed_by_id,
            confirmed_by=dp.confirmed_by.username if dp.confirmed_by else None,
            confirmed_at=dp.confirmed_at,
            created_by_id=dp.created_by_id,
            created_by=dp.created_by.username if dp.created_by else None,
            created_at=dp.created_at,
            updated_at=dp.updated_at,
        )


__all__ = [
    "TokenOut",
    "UserOut",
    "UserCreate",
    "UserUpdate",
    "ProjectCreate",
    "ProjectUpdate",
    "ProjectListItem",
    "ProjectDetail",
    "AttachmentOut",
    "MomOut",
    "MomStatusUpdate",
    "MomAttendee",
    "MomAgendaItem",
    "MomDetails",
    "AuditOut",
    "DispositionUpdate",
    "EarUpdate",
    "EarTradeInputCreate",
    "EarTradeInputOut",
    "EarBudgetUpdate",
    "EarOut",
    "SowRevisionCreate",
    "SowOut",
    "BoqItemCreate",
    "BoqItemUpdate",
    "BoqItemOut",
    "BoqMtoItemOut",
    "ConstructionMtoItemCreate",
    "ConstructionMtoItemUpdate",
    "ConstructionMtoItemOut",
    "ConstructionOut",
    "ConstructionUpdate",
    "CloseoutOut",
    "PunchListItemOut",
    "IcrHandoffCreate",
    "IcrHandoffOut",
    "DataPointCreate",
    "DataPointUpdate",
    "DataPointOut",
    "MasterPricingIn",
    "MasterPricingOut",
    "ProjectBudgetSummaryOut",
    "ProjectStageBudgetOut",
    "ROLES",
    "TRADES",
]
