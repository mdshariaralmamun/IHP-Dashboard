"""add data_points (source-tag provenance, master prompt v1.1 module 12)

Revision ID: 9a3f1c2d4e5b
Revises: 3c68dffcb604
Create Date: 2026-09-15 10:30:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a3f1c2d4e5b'
down_revision: str | None = '3c68dffcb604'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('data_points',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('field_key', sa.String(length=128), nullable=False),
    sa.Column('label', sa.String(length=300), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('unit', sa.String(length=64), nullable=True),
    sa.Column('source_tag', sa.String(length=16), nullable=False),
    sa.Column('source_file', sa.String(length=300), nullable=True),
    sa.Column('source_location', sa.String(length=128), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('confirmed_by_id', sa.Integer(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['confirmed_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_data_points_project_id'), 'data_points', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_data_points_project_id'), table_name='data_points')
    op.drop_table('data_points')
