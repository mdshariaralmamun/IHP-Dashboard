"""AI retrieval corpus tables (corpus_documents + corpus_chunks)

Revision ID: e5f9b2d17a38
Revises: d4e8a1c06f27
Create Date: 2026-09-04 23:15:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f9b2d17a38'
down_revision: str | None = 'd4e8a1c06f27'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'corpus_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=300), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'corpus_chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        # Denormalized scope column: no FK, indexed for scoped retrieval.
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('embedding', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['corpus_documents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_corpus_chunks_document_id'), 'corpus_chunks', ['document_id']
    )
    op.create_index(
        op.f('ix_corpus_chunks_project_id'), 'corpus_chunks', ['project_id']
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_corpus_chunks_project_id'), table_name='corpus_chunks')
    op.drop_index(op.f('ix_corpus_chunks_document_id'), table_name='corpus_chunks')
    op.drop_table('corpus_chunks')
    op.drop_table('corpus_documents')
