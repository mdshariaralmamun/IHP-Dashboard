"""add the PR data room: source documents + AI briefs

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-04 13:10:00.000000

Every PR now keeps its raw source files (engineer row data, PI emails, the
utility matrix, the specification, drawings, quotations) with the extracted
text cached next to them, plus the versioned AI brief built from that room.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e2f3a4b5c6d7'
down_revision: str | None = 'd1e2f3a4b5c6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'source_documents',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False,
                  server_default='99_Unsorted'),
        sa.Column('doc_type', sa.String(length=32), nullable=False,
                  server_default='other'),
        sa.Column('filename', sa.String(length=300), nullable=False),
        sa.Column('stored_path', sa.String(length=600), nullable=False),
        sa.Column('text_path', sa.String(length=600), nullable=True),
        sa.Column('content_type', sa.String(length=200), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('text_chars', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('text_excerpt', sa.Text(), nullable=True),
        sa.Column('extraction_note', sa.String(length=300), nullable=True),
        sa.Column('uploaded_by_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_source_documents_project_id', 'source_documents', ['project_id'])
    op.create_index('ix_source_documents_category', 'source_documents', ['category'])
    op.create_index('ix_source_documents_doc_type', 'source_documents', ['doc_type'])

    op.create_table(
        'source_briefs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=16), nullable=False,
                  server_default='running'),
        sa.Column('model', sa.String(length=200), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_source_briefs_project_id', 'source_briefs', ['project_id'])
    op.create_index('ix_source_briefs_status', 'source_briefs', ['status'])


def downgrade() -> None:
    op.drop_index('ix_source_briefs_status', table_name='source_briefs')
    op.drop_index('ix_source_briefs_project_id', table_name='source_briefs')
    op.drop_table('source_briefs')
    op.drop_index('ix_source_documents_doc_type', table_name='source_documents')
    op.drop_index('ix_source_documents_category', table_name='source_documents')
    op.drop_index('ix_source_documents_project_id', table_name='source_documents')
    op.drop_table('source_documents')
