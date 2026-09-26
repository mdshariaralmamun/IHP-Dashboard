"""add projects.planner_bucket (IHP planner Bucket register filter)

Revision ID: c4d8e1f2a6b0
Revises: b7e2a9c1d3f4
Create Date: 2026-09-16 14:40:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d8e1f2a6b0'
down_revision: str | None = 'b7e2a9c1d3f4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('projects',
                  sa.Column('planner_bucket', sa.String(length=32), nullable=True))
    op.create_index(op.f('ix_projects_planner_bucket'),
                    'projects', ['planner_bucket'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_projects_planner_bucket'), table_name='projects')
    op.drop_column('projects', 'planner_bucket')
