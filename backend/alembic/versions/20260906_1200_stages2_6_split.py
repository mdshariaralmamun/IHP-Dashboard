"""Stages 2-6 + MTO Design/Construction split (v2 upgrade spec Section 2).

Revision ID: a1b2c3d4e5f6
Revises: 7e4a1f8c9b02
Create Date: 2026-09-06 12:00:00.000000

Adds:
- ear_records, ear_trade_inputs        (Stage 3 EAR, Project-branch only)
- sow_records                          (Stage 4 SOW, Project-branch only)
- boq_mto_items                        (Stage 4 Design BOQ / Design MTO)
- construction_mto_items               (Stage 6 Construction MTO, with
                                        variance_qty / variance_reason
                                        so it can be reconciled against
                                        the design MTO)
- construction_records                 (Stage 6 execution + WCF + schedule)
- icr_handoffs                         (ICR branch: MTO -> Project Control
                                        -> Equipment Assessment Team;
                                        never touches the construction
                                        department)
- closeout_records, punch_list_items   (Stage 7 — already added by the
                                        stage-7 closeout migration, so
                                        we only create them if missing)

The MTO Design/Construction split is the v2 spec's load-bearing change:
BoqMtoItem.mto_kind = 'design' (default) or 'construction', and
ConstructionMtoItem holds the as-built/as-awarded lines that reconcile
back to the design table by item_code.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "7e4a1f8c9b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ---- EAR ----
    if "ear_records" not in existing:
        op.create_table(
            "ear_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("recommendations", sa.Text(), nullable=False, server_default=""),
            sa.Column("budget_data", sa.JSON(), nullable=True),
            sa.Column("ai_review_findings", sa.JSON(), nullable=True),
            sa.Column("docx_filename", sa.String(length=300), nullable=True),
            sa.Column("pdf_filename", sa.String(length=300), nullable=True),
            sa.Column("updated_by_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", name="uq_ear_records_project_id"),
        )
        op.create_index("ix_ear_records_project_id", "ear_records", ["project_id"], unique=True)

    if "ear_trade_inputs" not in existing:
        op.create_table(
            "ear_trade_inputs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ear_id", sa.Integer(), nullable=False),
            sa.Column("trade", sa.String(length=64), nullable=False),
            sa.Column("proposal", sa.Text(), nullable=False, server_default=""),
            sa.Column("comments", sa.Text(), nullable=False, server_default=""),
            sa.Column("missing_info", sa.Text(), nullable=False, server_default=""),
            sa.Column("has_conflict", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("conflict_reason_code", sa.String(length=64), nullable=True),
            sa.Column("conflict_resolution_note", sa.Text(), nullable=True),
            sa.Column("estimated_materials_cost", sa.Float(), nullable=False, server_default="0"),
            sa.Column("estimated_manpower_cost", sa.Float(), nullable=False, server_default="0"),
            sa.Column("updated_by_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["ear_id"], ["ear_records.id"]),
            sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ear_trade_inputs_ear_id", "ear_trade_inputs", ["ear_id"])

    # ---- SOW ----
    if "sow_records" not in existing:
        op.create_table(
            "sow_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("revision_name", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
            sa.Column("scope_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("trade_sections", sa.JSON(), nullable=True),
            sa.Column("procore_comments", sa.JSON(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sow_records_project_id", "sow_records", ["project_id"])

    # ---- Design BOQ / MTO ----
    if "boq_mto_items" not in existing:
        op.create_table(
            "boq_mto_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            # mto_kind: "design" (default) or "construction". The Construction
            # MTO is also stored here when it ties to a design row by
            # item_code; the standalone as-built lines live in
            # construction_mto_items.
            sa.Column("mto_kind", sa.String(length=16), nullable=False, server_default="design"),
            sa.Column("trade", sa.String(length=64), nullable=False),
            sa.Column("item_code", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("unit", sa.String(length=32), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
            sa.Column("unit_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("total_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("material_spec", sa.Text(), nullable=True),
            sa.Column("supplier_lead_time_days", sa.Integer(), nullable=True),
            sa.Column("delivery_status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_boq_mto_items_project_id", "boq_mto_items", ["project_id"])

    # ---- Construction MTO (separate table, reconciled by item_code) ----
    if "construction_mto_items" not in existing:
        op.create_table(
            "construction_mto_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("trade", sa.String(length=64), nullable=False),
            sa.Column("item_code", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("unit", sa.String(length=32), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
            sa.Column("unit_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("total_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("material_spec", sa.Text(), nullable=True),
            sa.Column("variance_qty", sa.Float(), nullable=True),
            sa.Column("variance_reason", sa.Text(), nullable=True),
            sa.Column("delivery_status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_construction_mto_items_project_id", "construction_mto_items", ["project_id"])

    # ---- Construction record (WCF, schedule, status) ----
    if "construction_records" not in existing:
        op.create_table(
            "construction_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
            sa.Column("schedule_data", sa.JSON(), nullable=True),
            sa.Column("wcf_data", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("updated_by_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", name="uq_construction_records_project_id"),
        )
        op.create_index("ix_construction_records_project_id", "construction_records", ["project_id"], unique=True)

    # ---- ICR branch hand-offs (Project Control / EAT) ----
    if "icr_handoffs" not in existing:
        op.create_table(
            "icr_handoffs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("milestone", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("recorded_by_id", sa.Integer(), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_icr_handoffs_project_id", "icr_handoffs", ["project_id"])


def downgrade() -> None:
    for tbl in (
        "icr_handoffs",
        "construction_records",
        "construction_mto_items",
        "boq_mto_items",
        "sow_records",
        "ear_trade_inputs",
        "ear_records",
    ):
        op.drop_table(tbl)
