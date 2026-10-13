"""add assistant_messages: the Project Delivery Assistant transcript

Revision ID: 20261013_1000
Revises: 20261012_1000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261013_1000"
down_revision: str | None = "20261012_1000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        # action id, artifacts [{kind,label,filename,url,panel}], elapsed_ms, gate
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_assistant_messages_project_id", "assistant_messages", ["project_id"])
    op.create_index(
        "ix_assistant_messages_project_id_id", "assistant_messages", ["project_id", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_project_id_id", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_project_id", table_name="assistant_messages")
    op.drop_table("assistant_messages")
