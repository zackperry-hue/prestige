"""add user_profiles table for onboarding questionnaire

Revision ID: a1b2c3d4e5f6
Revises: 415a56ddd831
Create Date: 2026-03-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "415a56ddd831"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("fitness_goals", sa.Text(), nullable=True),
        sa.Column("experience_level", sa.String(20), nullable=True),
        sa.Column("primary_sports", sa.Text(), nullable=True),
        sa.Column("weekly_target", sa.Integer(), nullable=True),
        sa.Column("target_event_name", sa.String(200), nullable=True),
        sa.Column("target_event_date", sa.String(20), nullable=True),
        sa.Column("additional_context", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
