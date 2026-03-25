"""Core pipeline: fetch workout from platform → normalize → save → email."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workout import Workout
from app.schemas.workout import NormalizedWorkout
from app.services.email_service import send_workout_email
from app.services.workout_insights import generate_highlights

logger = logging.getLogger(__name__)


async def save_workout(
    db: AsyncSession,
    user_id: uuid.UUID,
    normalized: NormalizedWorkout,
) -> Workout | None:
    """Save a normalized workout to the database. Returns None if duplicate."""
    existing = await db.execute(
        select(Workout).where(
            Workout.platform == normalized.platform,
            Workout.platform_workout_id == normalized.platform_workout_id,
        )
    )
    if existing.scalar_one_or_none():
        logger.info(
            "Duplicate workout %s/%s, skipping",
            normalized.platform,
            normalized.platform_workout_id,
        )
        return None

    workout = Workout(
        user_id=user_id,
        platform=normalized.platform,
        platform_workout_id=normalized.platform_workout_id,
        sport_type=normalized.sport_type,
        started_at=normalized.started_at,
        ended_at=normalized.ended_at,
        duration_seconds=normalized.duration_seconds,
        distance_meters=normalized.distance_meters,
        calories=normalized.calories,
        avg_heart_rate=normalized.avg_heart_rate,
        max_heart_rate=normalized.max_heart_rate,
        strain_score=normalized.strain_score,
        elevation_gain=normalized.elevation_gain,
        avg_power_watts=normalized.avg_power_watts,
        raw_data=normalized.raw_data,
    )
    db.add(workout)
    await db.commit()
    await db.refresh(workout)
    logger.info("Saved workout %s from %s", workout.id, normalized.platform)
    return workout


async def process_workout(
    db: AsyncSession,
    user_id: uuid.UUID,
    normalized: NormalizedWorkout,
) -> None:
    """Full pipeline: save workout and send email notification."""
    workout = await save_workout(db, user_id, normalized)
    if workout is None:
        return

    # Fetch user for email
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.error("User %s not found, skipping email", user_id)
        return

    highlights = await generate_highlights(db, user_id, normalized)
    await send_workout_email(db, user, normalized, workout.id, highlights)
    workout.email_sent_at = datetime.now(UTC)
    await db.commit()
