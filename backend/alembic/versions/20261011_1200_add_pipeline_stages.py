"""add pipeline_stages: the five-stage delivery spine

Revision ID: 20261011_1200
Revises: 20261005_1600
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '20261011_1200'
down_revision: str | None = '20261005_1600'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'pipeline_stages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('stage', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='not_started'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('project_id', 'stage', name='uq_pipeline_project_stage'),
    )
    op.create_index('ix_pipeline_stages_project_id', 'pipeline_stages', ['project_id'])
    op.create_index('ix_pipeline_stages_status', 'pipeline_stages', ['status'])


def downgrade() -> None:
    op.drop_index('ix_pipeline_stages_status', table_name='pipeline_stages')
    op.drop_index('ix_pipeline_stages_project_id', table_name='pipeline_stages')
    op.drop_table('pipeline_stages')
