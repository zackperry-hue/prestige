"""add insight_logs table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insight_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("input_payload", postgresql.JSONB, nullable=True),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("user_prompt", sa.Text, nullable=True),
        sa.Column("output_markdown", sa.Text, nullable=True),
        sa.Column("input_chars", sa.Integer, nullable=True),
        sa.Column("output_chars", sa.Integer, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_insight_logs_session_id", "insight_logs", ["session_id"])
    op.create_index("ix_insight_logs_user_id", "insight_logs", ["user_id"])
    op.create_index("ix_insight_logs_created_at", "insight_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_insight_logs_created_at", table_name="insight_logs")
    op.drop_index("ix_insight_logs_user_id", table_name="insight_logs")
    op.drop_index("ix_insight_logs_session_id", table_name="insight_logs")
    op.drop_table("insight_logs")
