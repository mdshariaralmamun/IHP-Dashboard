"""add ai_materials_proposals (AI-coordinated draft materials lists)

Revision ID: b7e2a9c1d3f4
Revises: 9a3f1c2d4e5b
Create Date: 2026-09-16 13:15:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2a9c1d3f4'
down_revision: str | None = '9a3f1c2d4e5b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_materials_proposals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('stage_target', sa.String(length=8), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('items', sa.JSON(), nullable=False),
    sa.Column('subtotal_sar', sa.Float(), nullable=False),
    sa.Column('vat_sar', sa.Float(), nullable=False),
    sa.Column('total_sar', sa.Float(), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.Column('decided_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_materials_proposals_project_id'),
                    'ai_materials_proposals', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_materials_proposals_project_id'),
                  table_name='ai_materials_proposals')
    op.drop_table('ai_materials_proposals')
