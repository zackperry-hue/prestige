"""add activity context, zones, and sleep to workout_sessions

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-24

Adds richer signals so the post-workout insight can know:
- the athlete's intent (Strava workout_type, name, description)
- whether it was a group activity (athlete_count)
- time in HR/power zones (so intensity can be classified)
- daily sleep context (Whoop)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workout_sessions", sa.Column("sleep_hours", sa.Float(), nullable=True))
    op.add_column("workout_sessions", sa.Column("sleep_performance", sa.Float(), nullable=True))
    op.add_column("workout_sessions", sa.Column("workout_subtype", sa.String(50), nullable=True))
    op.add_column("workout_sessions", sa.Column("activity_name", sa.String(255), nullable=True))
    op.add_column("workout_sessions", sa.Column("activity_description", sa.Text(), nullable=True))
    op.add_column("workout_sessions", sa.Column("athlete_count", sa.Integer(), nullable=True))
    op.add_column("workout_sessions", sa.Column("hr_zone_durations", postgresql.JSONB, nullable=True))
    op.add_column("workout_sessions", sa.Column("power_zone_durations", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("workout_sessions", "power_zone_durations")
    op.drop_column("workout_sessions", "hr_zone_durations")
    op.drop_column("workout_sessions", "athlete_count")
    op.drop_column("workout_sessions", "activity_description")
    op.drop_column("workout_sessions", "activity_name")
    op.drop_column("workout_sessions", "workout_subtype")
    op.drop_column("workout_sessions", "sleep_performance")
    op.drop_column("workout_sessions", "sleep_hours")
