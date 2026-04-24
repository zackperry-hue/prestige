"""WorkoutSession groups workouts from multiple platforms into a single session."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sport_type: Mapped[str | None] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Best-of merged fields (populated from whichever platform has the data)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    distance_meters: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[float | None] = mapped_column(Float)
    avg_heart_rate: Mapped[float | None] = mapped_column(Float)
    max_heart_rate: Mapped[float | None] = mapped_column(Float)
    elevation_gain: Mapped[float | None] = mapped_column(Float)
    avg_power_watts: Mapped[float | None] = mapped_column(Float)

    # Whoop-specific (only populated when Whoop data exists)
    strain_score: Mapped[float | None] = mapped_column(Float)
    recovery_score: Mapped[float | None] = mapped_column(Float)
    hrv_rmssd: Mapped[float | None] = mapped_column(Float)  # HRV from recovery
    sleep_hours: Mapped[float | None] = mapped_column(Float)
    sleep_performance: Mapped[float | None] = mapped_column(Float)

    # Activity context (the athlete's intent — Strava workout_type, name, description)
    workout_subtype: Mapped[str | None] = mapped_column(String(50))
    activity_name: Mapped[str | None] = mapped_column(String(255))
    activity_description: Mapped[str | None] = mapped_column(Text)
    athlete_count: Mapped[int | None] = mapped_column(Integer)  # >1 ⇒ group ride/run

    # Time-in-zone (list of seconds per zone, lowest → highest)
    hr_zone_durations: Mapped[list[int] | None] = mapped_column(JSONB)
    power_zone_durations: Mapped[list[int] | None] = mapped_column(JSONB)

    # Platforms that contributed to this session
    platforms: Mapped[str] = mapped_column(String(100), default="")  # comma-separated: "strava,whoop"

    # Email tracking
    email_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_ready: Mapped[bool] = mapped_column(Boolean, default=False)  # True when delay has passed
    email_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship()  # noqa: F821
