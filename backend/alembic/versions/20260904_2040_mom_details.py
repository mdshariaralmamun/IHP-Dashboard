"""mom_records.details column (KAUST MOM template fields)

Revision ID: b3f1c9d2e4a6
Revises: a74589215df7
Create Date: 2026-09-04 20:40:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f1c9d2e4a6'
down_revision: str | None = 'a74589215df7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('mom_records', sa.Column('details', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('mom_records', 'details')
