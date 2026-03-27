"""UserProfile model – stores onboarding questionnaire responses."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # Fitness goals (comma-separated): get_faster, build_endurance, lose_weight, get_stronger, stay_consistent, train_for_event
    fitness_goals: Mapped[str | None] = mapped_column(Text)

    # Experience level: beginner, intermediate, advanced
    experience_level: Mapped[str | None] = mapped_column(String(20))

    # Primary sports (comma-separated): running, cycling, swimming, strength, yoga, hiking, other
    primary_sports: Mapped[str | None] = mapped_column(Text)

    # Weekly training target (number of days)
    weekly_target: Mapped[int | None] = mapped_column(Integer)

    # Target event (optional)
    target_event_name: Mapped[str | None] = mapped_column(String(200))
    target_event_date: Mapped[str | None] = mapped_column(String(20))  # stored as YYYY-MM-DD string

    # Free-text: anything else the user wants their coach to know
    additional_context: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="profile")  # noqa: F821
