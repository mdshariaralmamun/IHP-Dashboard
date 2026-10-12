"""add procore_comments + Procore submittal tracking on projects

Revision ID: 20261012_1000
Revises: 20261011_1200
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '20261012_1000'
down_revision: str | None = '20261011_1200'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'procore_comments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('item_no', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('reviewer', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('department', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('discipline', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('comment', sa.Text(), nullable=False, server_default=''),
        sa.Column('ihp_response', sa.Text(), nullable=True),
        sa.Column('action_taken', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='open'),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_procore_comments_project_id', 'procore_comments', ['project_id'])
    op.create_index('ix_procore_comments_status', 'procore_comments', ['status'])
    op.add_column('projects', sa.Column('procore_status', sa.String(length=48), nullable=True))
    op.add_column('projects', sa.Column('procore_submittal_date', sa.Date(), nullable=True))
    op.add_column(
        'projects',
        sa.Column('procore_revision', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('projects', 'procore_revision')
    op.drop_column('projects', 'procore_submittal_date')
    op.drop_column('projects', 'procore_status')
    op.drop_index('ix_procore_comments_status', table_name='procore_comments')
    op.drop_index('ix_procore_comments_project_id', table_name='procore_comments')
    op.drop_table('procore_comments')
