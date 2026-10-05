"""add brief_questions: the answers to the AI's open questions

Revision ID: 20261005_1100
Revises: 20261004_1540
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '20261005_1100'
down_revision: str | None = '20261004_1540'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'brief_questions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('who_can_answer', sa.String(length=64), nullable=True),
        sa.Column('blocking', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='open'),
        sa.Column('answered_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('answered_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_brief_questions_project_id', 'brief_questions', ['project_id'])
    op.create_index('ix_brief_questions_status', 'brief_questions', ['status'])


def downgrade() -> None:
    op.drop_index('ix_brief_questions_status', table_name='brief_questions')
    op.drop_index('ix_brief_questions_project_id', table_name='brief_questions')
    op.drop_table('brief_questions')
