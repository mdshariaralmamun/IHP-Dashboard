"""Stage 7 Closeout & Punch List tables

Revision ID: 7e4a1f8c9b02
Revises: e5f9b2d17a38
Create Date: 2026-09-05 12:30:00.000000

Note: original chain had this migration depend on f6a0c3e28b49 (the
lost Stage 2-6 initial migration). After the v2 upgrade we re-thread
the chain to depend on the ai_corpus migration (e5f9b2d17a38), and
all of Stages 2-6 are created by the new a1b2c3d4e5f6 migration that
follows this one.

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e4a1f8c9b02'
down_revision: str | None = 'e5f9b2d17a38'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'closeout_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('testing_commissioning_notes', sa.Text(), nullable=False),
        sa.Column('as_built_drawings_submitted', sa.Boolean(), nullable=False),
        sa.Column('o_and_m_manuals_submitted', sa.Boolean(), nullable=False),
        sa.Column('warranty_start_date', sa.DateTime(), nullable=True),
        sa.Column('warranty_end_date', sa.DateTime(), nullable=True),
        sa.Column('warranty_provider', sa.String(length=200), nullable=True),
        sa.Column('warranty_notes', sa.Text(), nullable=True),
        sa.Column('client_signoff_by', sa.String(length=200), nullable=True),
        sa.Column('client_signoff_date', sa.DateTime(), nullable=True),
        sa.Column('client_feedback', sa.Text(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_closeout_records_project_id'), 'closeout_records', ['project_id'], unique=True)

    op.create_table(
        'punch_list_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('closeout_id', sa.Integer(), nullable=False),
        sa.Column('trade', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('location', sa.String(length=200), nullable=False),
        sa.Column('severity', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('assigned_to', sa.String(length=200), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['closeout_id'], ['closeout_records.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_punch_list_items_project_id'), 'punch_list_items', ['project_id'])
    op.create_index(op.f('ix_punch_list_items_closeout_id'), 'punch_list_items', ['closeout_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_punch_list_items_closeout_id'), table_name='punch_list_items')
    op.drop_index(op.f('ix_punch_list_items_project_id'), table_name='punch_list_items')
    op.drop_table('punch_list_items')
    op.drop_index(op.f('ix_closeout_records_project_id'), table_name='closeout_records')
    op.drop_table('closeout_records')
