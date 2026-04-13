"""add performance indexes for workouts and platform connections

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-13

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Speed up workout insights queries (sport-type filtering, time-range scans)
    op.create_index(
        "ix_workouts_user_sport_type",
        "workouts",
        ["user_id", "sport_type"],
    )
    op.create_index(
        "ix_workouts_user_started_at",
        "workouts",
        ["user_id", "started_at"],
    )

    # Speed up webhook-driven lookups by platform user ID
    op.create_index(
        "ix_platform_connections_platform_user_id",
        "platform_connections",
        ["platform", "platform_user_id"],
    )

    # Speed up session emailer query
    op.create_index(
        "ix_workout_sessions_email_pending",
        "workout_sessions",
        ["email_scheduled_at"],
        postgresql_where="email_sent_at IS NULL",
    )


def downgrade() -> None:
    op.drop_index("ix_workout_sessions_email_pending", table_name="workout_sessions")
    op.drop_index("ix_platform_connections_platform_user_id", table_name="platform_connections")
    op.drop_index("ix_workouts_user_started_at", table_name="workouts")
    op.drop_index("ix_workouts_user_sport_type", table_name="workouts")
