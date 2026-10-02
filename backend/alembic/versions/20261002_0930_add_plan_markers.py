"""add plan_markers (labelled pins on floor-plan drawings)

Revision ID: f8a2c6d4e1b9
Revises: a7c1e4b90d21
Create Date: 2026-10-02 09:30:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a2c6d4e1b9'
down_revision: str | None = 'a7c1e4b90d21'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'plan_markers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'project_id', sa.Integer(),
            sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column(
            'attachment_id', sa.Integer(),
            sa.ForeignKey('attachments.id', ondelete='SET NULL'), nullable=True,
        ),
        sa.Column('page', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('label', sa.String(length=200), nullable=False),
        sa.Column('pi_name', sa.String(length=200), nullable=True),
        sa.Column('pr_ref', sa.String(length=64), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('x', sa.Float(), nullable=False),
        sa.Column('y', sa.Float(), nullable=False),
        sa.Column(
            'created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False
        ),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_plan_markers_project_id', 'plan_markers', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_plan_markers_project_id', table_name='plan_markers')
    op.drop_table('plan_markers')
