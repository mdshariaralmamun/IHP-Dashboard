"""users.title column (job title, shown as contributor on MOM items)

Revision ID: c7a2e5f91b04
Revises: b3f1c9d2e4a6
Create Date: 2026-09-04 22:10:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a2e5f91b04'
down_revision: str | None = 'b3f1c9d2e4a6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('title', sa.String(length=200), server_default='', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'title')
