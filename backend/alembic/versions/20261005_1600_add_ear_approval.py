"""add the EAR approval record

Revision ID: 20261005_1600
Revises: 20261005_1300
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '20261005_1600'
down_revision: str | None = '20261005_1300'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('ear_approval_status', sa.String(length=24), nullable=True))
    op.add_column('projects', sa.Column('ear_approval_date', sa.String(length=20), nullable=True))
    op.add_column('projects', sa.Column('ear_approval_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'ear_approval_note')
    op.drop_column('projects', 'ear_approval_date')
    op.drop_column('projects', 'ear_approval_status')
