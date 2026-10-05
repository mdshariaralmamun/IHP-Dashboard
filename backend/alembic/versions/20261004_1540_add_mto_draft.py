"""add the materials take-off draft table

Revision ID: 20261004_1540
Revises: f3a4b5c6d7e8
Create Date: 2026-10-04 15:40:00.000000

A project's MTO is built up over days and must not vanish between sessions.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '20261004_1540'
down_revision: str | None = 'f3a4b5c6d7e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'mto_draft_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('trade', sa.String(length=32), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('unit', sa.String(length=32), nullable=True),
        sa.Column('qty', sa.String(length=32), nullable=True),
        sa.Column('item_code', sa.String(length=64), nullable=True),
        sa.Column('unit_price', sa.Float(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_mto_draft_items_project_id', 'mto_draft_items', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_mto_draft_items_project_id', table_name='mto_draft_items')
    op.drop_table('mto_draft_items')
