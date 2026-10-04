"""add projects summary_status / owner_username / followup_note

Revision ID: c9d3e7a5b2c8
Revises: f8a2c6d4e1b9
Create Date: 2026-10-02 23:40:00.000000

The EAR/Design/Procore boards track two documents per project (the MOM and
the Project Summary) and who owns the next move. Whose court it is decides
what the board shows and what blinks.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d3e7a5b2c8'
down_revision: str | None = 'f8a2c6d4e1b9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('projects',
                  sa.Column('summary_status', sa.String(length=16), nullable=True))
    op.add_column('projects',
                  sa.Column('owner_username', sa.String(length=100), nullable=True))
    op.add_column('projects',
                  sa.Column('followup_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'followup_note')
    op.drop_column('projects', 'owner_username')
    op.drop_column('projects', 'summary_status')
