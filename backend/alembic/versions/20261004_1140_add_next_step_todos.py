"""add next-step plan, cancellation record and the project to-do list

Revision ID: d1e2f3a4b5c6
Revises: c9d3e7a5b2c8
Create Date: 2026-10-04 11:40:00.000000

Every PR now carries one next-step plan (which lifecycle stage comes next, in
which follow-up bucket, who owns it, when it is due) and any number of to-do
rows. Cancelling keeps its own record: reason, justification and the date the
PI was notified.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: str | None = 'c9d3e7a5b2c8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('projects',
                  sa.Column('next_stage', sa.String(length=32), nullable=True))
    op.add_column('projects',
                  sa.Column('next_stage_bucket', sa.String(length=32), nullable=True))
    op.add_column('projects',
                  sa.Column('next_stage_date', sa.String(length=20), nullable=True))
    op.add_column('projects',
                  sa.Column('next_stage_owner', sa.String(length=100), nullable=True))
    op.add_column('projects',
                  sa.Column('next_step_note', sa.Text(), nullable=True))
    op.add_column('projects',
                  sa.Column('cancel_reason', sa.String(length=200), nullable=True))
    op.add_column('projects',
                  sa.Column('cancel_justification', sa.Text(), nullable=True))
    op.add_column('projects',
                  sa.Column('cancel_notified_at', sa.DateTime(), nullable=True))

    op.create_table(
        'project_todos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('bucket', sa.String(length=32), nullable=True),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('stage', sa.String(length=32), nullable=True),
        sa.Column('assignee_username', sa.String(length=100), nullable=True),
        sa.Column('due_date', sa.String(length=20), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False,
                  server_default='open'),
        sa.Column('created_by_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_by_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('ix_project_todos_project_id', 'project_todos', ['project_id'])
    op.create_index('ix_project_todos_bucket', 'project_todos', ['bucket'])
    op.create_index('ix_project_todos_assignee_username', 'project_todos',
                    ['assignee_username'])
    op.create_index('ix_project_todos_status', 'project_todos', ['status'])


def downgrade() -> None:
    op.drop_index('ix_project_todos_status', table_name='project_todos')
    op.drop_index('ix_project_todos_assignee_username', table_name='project_todos')
    op.drop_index('ix_project_todos_bucket', table_name='project_todos')
    op.drop_index('ix_project_todos_project_id', table_name='project_todos')
    op.drop_table('project_todos')
    op.drop_column('projects', 'cancel_notified_at')
    op.drop_column('projects', 'cancel_justification')
    op.drop_column('projects', 'cancel_reason')
    op.drop_column('projects', 'next_step_note')
    op.drop_column('projects', 'next_stage_owner')
    op.drop_column('projects', 'next_stage_date')
    op.drop_column('projects', 'next_stage_bucket')
    op.drop_column('projects', 'next_stage')
