"""users.permissions column (per-user capability override; NULL = role defaults)

Revision ID: d4e8a1c06f27
Revises: c7a2e5f91b04
Create Date: 2026-09-04 22:27:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8a1c06f27'
down_revision: str | None = 'c7a2e5f91b04'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('permissions', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'permissions')
