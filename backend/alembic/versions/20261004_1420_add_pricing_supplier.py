"""add master_pricing.supplier

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-10-04 14:20:00.000000

The store's quotation export names the supplier for every item, and the BOQ
reviewer needs to see where a rate came from.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a4b5c6d7e8'
down_revision: str | None = 'e2f3a4b5c6d7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'master_pricing',
        sa.Column('supplier', sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('master_pricing', 'supplier')
