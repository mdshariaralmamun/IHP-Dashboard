"""Add access_requests (public dashboard access requests)

Revision ID: a7c1e4b90d21
Revises: 20260917_2055_add_rbac_tables
Create Date: 2026-09-26 20:10:00.000000

The public site is a read-only dashboard; visitors ask for an account here and
an admin approves it inside the app, which then produces a one-time invite link.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7c1e4b90d21'
down_revision = '20260917_2055_add_rbac_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'access_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.Column('phone', sa.String(length=64), nullable=True),
        sa.Column('company', sa.String(length=200), nullable=True),
        sa.Column('requested_role', sa.String(length=32), nullable=False,
                  server_default='viewer'),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False,
                  server_default='pending'),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('decided_by_id', sa.Integer(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('invite_token', sa.String(length=64), nullable=True),
        sa.Column('invite_expires_at', sa.DateTime(), nullable=True),
        sa.Column('invite_used_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('source_ip', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['decided_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_access_requests_email', 'access_requests', ['email'])
    op.create_index('ix_access_requests_status', 'access_requests', ['status'])
    op.create_index('ix_access_requests_invite_token', 'access_requests', ['invite_token'])
    op.create_index('ix_access_requests_created_at', 'access_requests', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_access_requests_created_at', table_name='access_requests')
    op.drop_index('ix_access_requests_invite_token', table_name='access_requests')
    op.drop_index('ix_access_requests_status', table_name='access_requests')
    op.drop_index('ix_access_requests_email', table_name='access_requests')
    op.drop_table('access_requests')
