"""add projects.wbs_number and projects.cost_estimate_usd

Revision ID: 20261005_1300
Revises: 20261005_1100
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '20261005_1300'
down_revision: str | None = '20261005_1100'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('wbs_number', sa.String(length=120), nullable=True))
    op.add_column('projects', sa.Column('cost_estimate_usd', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'cost_estimate_usd')
    op.drop_column('projects', 'wbs_number')
